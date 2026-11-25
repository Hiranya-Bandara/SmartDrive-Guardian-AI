"""Desktop application lifecycle: Qt setup, service wiring, startup and orderly shutdown."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from smartdrive import APP_NAME, __version__
from smartdrive.ai.model_registry import ModelRegistry
from smartdrive.app import ApplicationContext, bootstrap, shutdown
from smartdrive.config.constants import APP_AUTHOR, APP_ID
from smartdrive.models.vehicle import Vehicle
from smartdrive.services.diagnostic_service import DiagnosticService
from smartdrive.services.maintenance_service import MaintenanceService
from smartdrive.services.notification_service import NotificationService
from smartdrive.services.obd_service import ObdHistoryService
from smartdrive.services.report_service import ReportService
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.threshold_service import ThresholdService
from smartdrive.services.trip_service import TripService
from smartdrive.services.vehicle_service import VehicleService
from smartdrive.ui.context import AppState, Notifier, UiContext
from smartdrive.ui.diagnostics_controller import DiagnosticsController
from smartdrive.ui.dialogs.welcome import show_welcome
from smartdrive.ui.gc_guard import MainThreadGarbageCollector
from smartdrive.ui.icons import app_icon
from smartdrive.ui.main_window import MainWindow
from smartdrive.ui.monitoring_controller import MonitoringController
from smartdrive.ui.notification_controller import NotificationController
from smartdrive.ui.themes.theme_manager import ThemeManager
from smartdrive.ui.trip_controller import TripController
from smartdrive.ui.vehicle_connection_controller import VehicleConnectionController
from smartdrive.ui.widgets.status import StatusLevel
from smartdrive.ui.workers.obd_worker import SessionFactory
from smartdrive.ui.workers.task_runner import TaskRunner
from smartdrive.ui.workers.voice_worker import VoiceWorker
from smartdrive.utils.exceptions import SmartDriveError

logger = logging.getLogger(__name__)

FONT_FAMILIES = ["Segoe UI", "Inter", "Helvetica Neue", "Arial", "sans-serif"]


def ensure_qapplication(argv: Sequence[str] | None = None) -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(list(argv) if argv is not None else sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_AUTHOR)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(10)
    app.setFont(font)
    return app


class GuiApplication:
    """Owns the GUI object graph for one application context."""

    def __init__(
        self,
        app_context: ApplicationContext,
        *,
        install_excepthook: bool = True,
        registry: ModelRegistry | None = None,
        obd_session_factory: SessionFactory | None = None,
        voice_worker: VoiceWorker | None = None,
    ) -> None:
        self.app_context = app_context
        # Before any worker thread exists: cyclic garbage is collected on this thread only.
        self.gc_guard = MainThreadGarbageCollector()
        self.gc_guard.start()
        vehicles = VehicleService(
            app_context.database, app_context.paths.data_dir / "vehicle_images"
        )
        telemetry = TelemetryService(app_context.database)
        recovered = telemetry.close_orphaned_sessions()
        if recovered:
            logger.warning(
                "Closed sessions left open by an unclean shutdown", extra={"sessions": recovered}
            )
        theme = ThemeManager(app_context.settings.appearance.theme)
        theme.apply()
        state = AppState(app_context, vehicles)
        settings = app_context.settings
        database = app_context.database
        tasks = TaskRunner()
        monitoring = MonitoringController(settings, telemetry)
        diagnostics = DiagnosticsController(settings, database, monitoring, registry=registry)
        obd_history = ObdHistoryService(database)
        orphaned = obd_history.close_orphaned_connections()
        if orphaned:
            logger.info("Closed connection records left open", extra={"connections": orphaned})
        connection = VehicleConnectionController(
            settings, obd_history, session_factory=obd_session_factory
        )
        trip_service = TripService(database, telemetry)
        trips = TripController(trip_service, telemetry, monitoring, connection, tasks)
        maintenance = MaintenanceService(database)
        notification_service = NotificationService(database)
        notifications = NotificationController(
            settings, notification_service, maintenance, tasks, voice_worker=voice_worker
        )
        notifications.attach(diagnostics, connection, monitoring)
        reports = ReportService(
            database,
            telemetry=telemetry,
            trips=trip_service,
            obd=obd_history,
            maintenance=maintenance,
            notifications=notification_service,
            registry=registry,
        )
        thresholds = ThresholdService(database)
        self.ui = UiContext(
            app=app_context,
            state=state,
            theme=theme,
            monitoring=monitoring,
            vehicles=vehicles,
            telemetry=telemetry,
            notifier=Notifier(),
            diagnostics=diagnostics,
            diagnostic_history=DiagnosticService(database),
            connection=connection,
            obd_history=obd_history,
            trips=trips,
            maintenance=maintenance,
            notifications=notifications,
            reports=reports,
            thresholds=thresholds,
            tasks=tasks,
        )
        self._on_vehicle_changed(state.active_vehicle)
        state.active_vehicle_changed.connect(self._on_vehicle_changed)
        state.settings_changed.connect(diagnostics.apply_settings)
        state.settings_changed.connect(notifications.apply_settings)
        trips.summarise_unfinished()
        notifications.purge_old()
        try:
            self.window = MainWindow(self.ui)
        except Exception:
            # Stop the worker threads already started before reporting the failure.
            self._stop_controllers()
            self.gc_guard.stop()
            raise
        self._closed = False
        self._previous_hook = sys.excepthook
        self._hook_installed = install_excepthook
        if install_excepthook:
            sys.excepthook = self._handle_exception

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._hook_installed:
            sys.excepthook = self._previous_hook
        self._stop_controllers()
        self.ui.theme.dispose()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.gc_guard.stop()

    def _stop_controllers(self) -> None:
        # Order matters: stop the stream (which ends any recording), then inference, then the
        # adapter link, then speech, and finally the job thread, which lets a running job finish.
        self.ui.monitoring.shutdown()
        self.ui.diagnostics.shutdown()
        self.ui.connection.shutdown()
        self.ui.notifications.shutdown()
        self.ui.tasks.shutdown()

    def _on_vehicle_changed(self, vehicle: object) -> None:
        ui = self.ui
        active = vehicle if isinstance(vehicle, Vehicle) else None
        ui.diagnostics.vehicle_thresholds = {}
        if active is not None:
            try:
                ui.diagnostics.vehicle_thresholds, _note = ui.thresholds.get(active.id)
            except SmartDriveError:
                logger.warning("Could not read vehicle-specific thresholds", exc_info=True)
        ui.diagnostics.on_active_vehicle_changed(active)
        ui.connection.set_vehicle(active.id if active is not None else None)
        ui.notifications.set_vehicle(active)

    def _handle_exception(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        message = (
            exc.user_message
            if isinstance(exc, SmartDriveError)
            else ("An unexpected error occurred. Details were written to the log file.")
        )
        self.ui.notifier.notify(message, StatusLevel.CRITICAL)


def run(
    *,
    home: Path | None = None,
    quit_after_ms: int | None = None,
    argv: Sequence[str] | None = None,
) -> int:
    qt_app = ensure_qapplication(argv)
    try:
        app_context = bootstrap(home=home)
    except SmartDriveError as exc:
        QMessageBox.critical(None, APP_NAME, f"{exc.user_message}\n\n{exc}")
        return 1
    gui = GuiApplication(app_context)
    gui.window.show()
    if not app_context.settings.general.welcome_seen:
        # Non-blocking, so start-up (and the timed smoke test) never waits for it.
        show_welcome(gui.ui, gui.window)
    if quit_after_ms is not None:
        QTimer.singleShot(quit_after_ms, qt_app.quit)
    try:
        code = qt_app.exec()
    finally:
        gui.shutdown()
        shutdown(app_context)
    return int(code)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smartdrive-gui", description=f"Launch {APP_NAME}.")
    parser.add_argument(
        "--home", type=Path, help="Portable data folder (overrides SMARTDRIVE_HOME)."
    )
    parser.add_argument("--quit-after-ms", type=int, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(home=args.home, quit_after_ms=args.quit_after_ms)
