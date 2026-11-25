"""Turns application events into notifications and delivers them.

Every notification is stored first (deduplicated and rate-limited by
:class:`NotificationService`). Only a *new* notification is delivered: an in-app toast (always),
a desktop notification through the system tray when enabled and supported, an optional system
sound, and an optional offline voice announcement on a dedicated speech thread.

Delivery other than the in-app list is best effort. A desktop notification can be suppressed by
the operating system and voice output can be unavailable; the Alert Centre keeps the record
either way. Notification severity (information/success/warning/critical) is an application
level and is kept separate from diagnostic severity.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Final

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from smartdrive import APP_NAME
from smartdrive.ai.model_registry import LoadStatus
from smartdrive.config.constants import NotificationCategory, NotificationSeverity, Severity
from smartdrive.config.settings import AppSettings
from smartdrive.models.diagnostic import DiagnosticAssessment, Finding
from smartdrive.models.maintenance import ScheduleState, ScheduleStatus
from smartdrive.models.notification import Notification
from smartdrive.models.vehicle import Vehicle
from smartdrive.obd.session import ConnectionReport
from smartdrive.services.maintenance_service import MaintenanceService
from smartdrive.services.notification_service import NotificationService
from smartdrive.services.voice import Announcement, VoiceInfo
from smartdrive.ui.diagnostics_controller import DiagnosticsController
from smartdrive.ui.icons import icon
from smartdrive.ui.monitoring_controller import MonitoringController
from smartdrive.ui.themes.palette import DARK
from smartdrive.ui.vehicle_connection_controller import VehicleConnectionController
from smartdrive.ui.workers.task_runner import TaskRunner
from smartdrive.ui.workers.voice_worker import VoiceConfig, VoiceWorker
from smartdrive.utils.exceptions import SmartDriveError

logger = logging.getLogger(__name__)

THREAD_JOIN_TIMEOUT_MS: Final = 10_000
MAINTENANCE_CHECK_MS: Final = 60 * 60 * 1000
MAINTENANCE_COOLDOWN_S: Final = 24 * 3600.0
DESKTOP_MESSAGE_MS: Final = 8000

_TRAY_ICONS: Final = {
    NotificationSeverity.INFORMATION: QSystemTrayIcon.MessageIcon.Information,
    NotificationSeverity.SUCCESS: QSystemTrayIcon.MessageIcon.Information,
    NotificationSeverity.WARNING: QSystemTrayIcon.MessageIcon.Warning,
    NotificationSeverity.CRITICAL: QSystemTrayIcon.MessageIcon.Critical,
}
_MAINTENANCE_STATES: Final = {
    ScheduleState.OVERDUE: NotificationSeverity.WARNING,
    ScheduleState.DUE: NotificationSeverity.WARNING,
    ScheduleState.UPCOMING: NotificationSeverity.INFORMATION,
}


def desktop_supported() -> bool:
    return QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()


class NotificationController(QObject):
    delivered = Signal(object)  # Notification, newly created or escalated
    changed = Signal()  # the stored list or unread count changed
    voice_ready = Signal(bool, str)  # available, reason when unavailable
    voice_failed = Signal(str)
    _voice_configure = Signal(object)
    _voice_enqueue = Signal(object)
    _voice_test = Signal(str)

    def __init__(
        self,
        settings: AppSettings,
        service: NotificationService,
        maintenance: MaintenanceService,
        tasks: TaskRunner,
        *,
        voice_worker: VoiceWorker | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.service = service
        self._maintenance = maintenance
        self._tasks = tasks
        self._vehicle: Vehicle | None = None
        self._closed = False
        self._maintenance_job: int | None = None
        self._last_model_state: tuple[str, ...] | None = None
        self.voice_available: bool | None = None
        self.voice_unavailable_reason = ""
        self.voices: list[VoiceInfo] = []
        self.desktop_failures = 0
        self._tray: QSystemTrayIcon | None = None
        self._diagnostics: DiagnosticsController | None = None

        self._voice = voice_worker or VoiceWorker()
        self._voice_thread = QThread()
        self._voice_thread.setObjectName("smartdrive-voice")
        self._voice.moveToThread(self._voice_thread)
        self._voice_thread.started.connect(self._voice.start)
        self._voice_configure.connect(self._voice.configure)
        self._voice_enqueue.connect(self._voice.enqueue)
        self._voice_test.connect(self._voice.test_voice)
        self._voice.ready.connect(self._on_voice_ready)
        self._voice.failed.connect(self._on_voice_failed)
        self._voice_thread.start()

        self._maintenance_timer = QTimer(self)
        self._maintenance_timer.setInterval(MAINTENANCE_CHECK_MS)
        self._maintenance_timer.timeout.connect(self.check_maintenance)
        self._maintenance_timer.start()
        tasks.finished.connect(self._on_job_finished)
        tasks.failed.connect(self._on_job_failed)
        self.apply_settings()

    # -- wiring -------------------------------------------------------------------------------

    def attach(
        self,
        diagnostics: DiagnosticsController,
        connection: VehicleConnectionController,
        monitoring: MonitoringController,
    ) -> None:
        self._diagnostics = diagnostics
        diagnostics.alerts_raised.connect(self._on_alerts)
        diagnostics.assessment_changed.connect(self._on_assessment)
        diagnostics.models_changed.connect(self._on_models)
        connection.link_lost.connect(self._on_link_lost)
        connection.link_restored.connect(self._on_link_restored)
        connection.link_failed.connect(self._on_link_failed)
        connection.report_changed.connect(self._on_report)
        monitoring.trip_completed.connect(self._on_trip_completed)

    def set_vehicle(self, vehicle: object) -> None:
        self._vehicle = vehicle if isinstance(vehicle, Vehicle) else None
        self.check_maintenance()

    def apply_settings(self, *_: object) -> None:
        alerts = self._settings.alerts
        self._voice_configure.emit(
            VoiceConfig(
                enabled=alerts.voice_notifications,
                voice_id=alerts.voice_id,
                rate=alerts.voice_rate,
                volume=alerts.voice_volume,
                cooldown_s=float(alerts.voice_cooldown_seconds),
            )
        )
        self._sync_tray()

    # -- posting ------------------------------------------------------------------------------

    def post(
        self,
        severity: NotificationSeverity,
        category: NotificationCategory,
        title: str,
        message: str = "",
        *,
        dedup_key: str | None = None,
        vehicle_id: int | None = None,
        alert_id: int | None = None,
        cooldown_s: float | None = None,
        speak: str | None = None,
    ) -> Notification | None:
        """Store a notification and deliver it if it is new. ``speak`` is the voice text."""
        if self._closed:
            return None
        cooldown = (
            float(self._settings.alerts.notification_cooldown_seconds)
            if cooldown_s is None
            else cooldown_s
        )
        try:
            outcome = self.service.notify(
                severity,
                category,
                title,
                message,
                dedup_key=dedup_key,
                vehicle_id=vehicle_id,
                alert_id=alert_id,
                cooldown_s=cooldown,
            )
        except SmartDriveError as exc:
            logger.warning("Notification could not be stored", extra={"error": str(exc)})
            return None
        self.changed.emit()
        if not outcome.is_new:
            return outcome.notification
        notification = outcome.notification
        self.delivered.emit(notification)
        self._deliver_desktop(notification)
        if self._settings.alerts.notification_sounds and severity in (
            NotificationSeverity.WARNING,
            NotificationSeverity.CRITICAL,
        ):
            QApplication.beep()
        if speak and self._wants_voice(severity, category):
            priority = 10 if severity is NotificationSeverity.CRITICAL else 5
            self._voice_enqueue.emit(Announcement(notification.dedup_key, speak, priority))
        return notification

    def _wants_voice(self, severity: NotificationSeverity, category: NotificationCategory) -> bool:
        alerts = self._settings.alerts
        if not alerts.voice_notifications:
            return False
        if category is NotificationCategory.MAINTENANCE:
            return alerts.voice_maintenance
        if severity is NotificationSeverity.CRITICAL:
            return alerts.voice_critical
        if severity is NotificationSeverity.WARNING:
            return alerts.voice_warnings
        return False

    def test_voice(self) -> None:
        self._voice_test.emit("SmartDrive Guardian voice notifications are working.")

    def unread_count(self) -> int:
        try:
            return self.service.unread_count()
        except SmartDriveError:
            return 0

    def mark_read(self, notification_id: int) -> None:
        self.service.mark_read(notification_id)
        self.changed.emit()

    def mark_all_read(self) -> int:
        count = self.service.mark_all_read()
        self.changed.emit()
        return count

    def acknowledge(self, notification_id: int) -> None:
        self.service.acknowledge(notification_id)
        self.changed.emit()

    def acknowledge_alert(self, alert_id: int) -> None:
        self.service.acknowledge_alert(alert_id)
        self.changed.emit()

    def purge_old(self) -> None:
        days = self._settings.alerts.notification_retention_days
        self._tasks.submit(
            "Remove old notifications", lambda: self.service.purge(older_than_days=days)
        )

    # -- desktop and voice --------------------------------------------------------------------

    def _sync_tray(self) -> None:
        wanted = self._settings.alerts.desktop_notifications and desktop_supported()
        if wanted and self._tray is None:
            self._tray = QSystemTrayIcon(icon("shield", DARK.accent), self)
            self._tray.setToolTip(APP_NAME)
            self._tray.show()
        elif not wanted and self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None

    @property
    def desktop_active(self) -> bool:
        return self._tray is not None

    def _deliver_desktop(self, notification: Notification) -> None:
        if self._tray is None:
            return
        try:
            self._tray.showMessage(
                notification.title,
                notification.message[:240] or notification.title,
                _TRAY_ICONS[notification.severity],
                DESKTOP_MESSAGE_MS,
            )
        except RuntimeError:
            self.desktop_failures += 1
            logger.warning("Desktop notification could not be shown", exc_info=True)

    def _on_voice_ready(self, available: bool, reason: str, voices: object) -> None:
        self.voice_available = available
        self.voice_unavailable_reason = reason
        self.voices = (
            [v for v in voices if isinstance(v, VoiceInfo)] if isinstance(voices, list) else []
        )
        self.voice_ready.emit(available, reason)

    def _on_voice_failed(self, message: str) -> None:
        self.voice_failed.emit(message)

    # -- event sources ------------------------------------------------------------------------

    def _vehicle_id(self) -> int | None:
        return self._vehicle.id if self._vehicle is not None else None

    def _on_alerts(self, findings: object) -> None:
        if not isinstance(findings, tuple):
            return
        vehicle_id = self._vehicle_id()
        for finding in findings:
            if not isinstance(finding, Finding):
                continue
            critical = finding.severity is Severity.CRITICAL
            alert_key = f"v{vehicle_id}:{finding.key}" if vehicle_id is not None else None
            alert_id = None
            if alert_key is not None:
                try:
                    alert_id = self.service.latest_alert_id(alert_key)
                except SmartDriveError:
                    alert_id = None
            self.post(
                NotificationSeverity.CRITICAL if critical else NotificationSeverity.WARNING,
                NotificationCategory.DIAGNOSTIC,
                finding.title,
                finding.explanation,
                dedup_key=f"diag:{alert_key or finding.key}",
                vehicle_id=vehicle_id,
                alert_id=alert_id,
                cooldown_s=float(self._settings.alerts.cooldown_seconds),
                speak=f"{'Critical' if critical else 'Warning'}: {finding.title}.",
            )

    def _on_assessment(self, assessment: object) -> None:
        if not isinstance(assessment, DiagnosticAssessment):
            return
        anomaly = assessment.anomaly
        if anomaly.persistent:
            self.post(
                NotificationSeverity.INFORMATION,
                NotificationCategory.DIAGNOSTIC,
                "Unusual telemetry pattern",
                "The anomaly detector has flagged the last minute of telemetry as unusual for "
                "several analyses in a row. It does not identify a cause; see AI Diagnostics.",
                dedup_key=f"anomaly:v{assessment.vehicle_id}",
                vehicle_id=assessment.vehicle_id,
            )

    def _on_models(self) -> None:
        models = self._diagnostics.models if self._diagnostics is not None else None
        if models is None:
            return
        problems = tuple(
            sorted(
                f"{name}:{status.value}"
                for name, status in models.status.items()
                if status is not LoadStatus.AVAILABLE
            )
        )
        if problems == self._last_model_state:
            return
        self._last_model_state = problems
        if problems:
            self.post(
                NotificationSeverity.WARNING,
                NotificationCategory.MODEL,
                "Machine-learning models unavailable",
                "Some diagnostic models could not be loaded ("
                + ", ".join(p.replace(":", ": ").replace("_", " ") for p in problems)
                + "). Rule-based diagnostics continue to work.",
                dedup_key="model:unavailable",
            )

    def _on_link_lost(self, message: str) -> None:
        self.post(
            NotificationSeverity.WARNING,
            NotificationCategory.CONNECTION,
            "Connection to the vehicle lost",
            f"{message} Reconnecting automatically (limited attempts).",
            dedup_key="conn:lost",
            vehicle_id=self._vehicle_id(),
            speak="Warning: connection to the vehicle lost.",
        )

    def _on_link_restored(self) -> None:
        self.post(
            NotificationSeverity.SUCCESS,
            NotificationCategory.CONNECTION,
            "Connection to the vehicle restored",
            dedup_key="conn:restored",
            vehicle_id=self._vehicle_id(),
            cooldown_s=60.0,
        )

    def _on_link_failed(self, message: str) -> None:
        self.post(
            NotificationSeverity.WARNING,
            NotificationCategory.CONNECTION,
            "Vehicle connection closed",
            f"{message} Reconnect from the Vehicle Connection page when ready.",
            dedup_key="conn:failed",
            vehicle_id=self._vehicle_id(),
        )

    def _on_report(self, report: object) -> None:
        if not isinstance(report, ConnectionReport) or report.capabilities is None:
            return
        missing = report.capabilities.missing_sample_fields
        if not missing:
            return
        self.post(
            NotificationSeverity.INFORMATION,
            NotificationCategory.TELEMETRY,
            "Some sensors are not available",
            f"The vehicle does not report {len(missing)} of the parameters SmartDrive can show "
            "over standard OBD-II. They are shown as unavailable, never estimated.",
            dedup_key=f"telemetry:unsupported:{report.port}",
            vehicle_id=self._vehicle_id(),
            cooldown_s=MAINTENANCE_COOLDOWN_S,
        )

    def _on_trip_completed(self, session_id: int) -> None:
        self.post(
            NotificationSeverity.SUCCESS,
            NotificationCategory.TRIP,
            "Trip recorded",
            f"Trip #{session_id} was saved. Its summary is available in Trip History.",
            dedup_key=f"trip:{session_id}",
            vehicle_id=self._vehicle_id(),
        )

    # -- maintenance --------------------------------------------------------------------------

    def check_maintenance(self) -> None:
        vehicle = self._vehicle
        if (
            self._closed
            or vehicle is None
            or not self._settings.maintenance.reminders_enabled
            or self._maintenance_job is not None
        ):
            return
        stale_days = self._settings.maintenance.odometer_stale_days
        vehicle_id = vehicle.id
        self._maintenance_job = self._tasks.submit(
            "Check maintenance schedules",
            lambda: (
                vehicle_id,
                self._maintenance.statuses(
                    vehicle_id, today=date.today(), odometer_stale_days=stale_days
                ),
            ),
        )

    def _post_maintenance(self, vehicle_id: int, statuses: list[ScheduleStatus]) -> None:
        if self._vehicle_id() != vehicle_id:
            return
        for status in statuses:
            severity = _MAINTENANCE_STATES.get(status.state)
            if severity is None:
                continue
            schedule = status.schedule
            when: list[str] = []
            if status.due_date is not None:
                when.append(f"date {status.due_date.isoformat()}")
            if status.due_km is not None:
                when.append(f"odometer {status.due_km:,.0f} km")
            due = f" (due by {' or '.join(when)})" if when else ""
            state_text = status.state.label.lower()
            self.post(
                severity,
                NotificationCategory.MAINTENANCE,
                f"{schedule.task_name}: {status.state.label.lower()}",
                f"Maintenance schedule{due}. Intervals are the ones you entered.",
                dedup_key=f"maint:v{vehicle_id}:s{schedule.id}:{status.state.value}",
                vehicle_id=vehicle_id,
                cooldown_s=MAINTENANCE_COOLDOWN_S,
                speak=f"Maintenance reminder: {schedule.task_name} is {state_text}.",
            )

    def _on_job_finished(self, job_id: int, result: object) -> None:
        if job_id != self._maintenance_job:
            return
        self._maintenance_job = None
        if isinstance(result, tuple) and len(result) == 2:
            vehicle_id, statuses = result
            if isinstance(vehicle_id, int) and isinstance(statuses, list):
                self._post_maintenance(vehicle_id, statuses)

    def _on_job_failed(self, job_id: int, message: str) -> None:
        if job_id == self._maintenance_job:
            self._maintenance_job = None
            logger.warning("Maintenance check failed", extra={"error": message})

    # -- shutdown -----------------------------------------------------------------------------

    def voice_thread_running(self) -> bool:
        return self._voice_thread.isRunning()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._maintenance_timer.stop()
        if self._voice_thread.isRunning():
            QMetaObject.invokeMethod(
                self._voice, "shutdown", Qt.ConnectionType.BlockingQueuedConnection
            )
        self._voice_thread.quit()
        if not self._voice_thread.wait(THREAD_JOIN_TIMEOUT_MS):
            logger.error("Voice thread did not stop within timeout")
        if self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None
