"""GUI-thread façade for background diagnostics.

Inference runs at most once per ``inference_interval_s`` and never overlaps: while a job is in
flight further ticks are skipped (and counted), so a slow analysis can never build a queue.
A generation counter discards results that belong to a stopped run or a previous vehicle.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import Final

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from smartdrive.ai.model_registry import LoadedModels, LoadStatus, ModelRegistry
from smartdrive.config.settings import AppSettings
from smartdrive.core.rule_engine import VehicleContext
from smartdrive.core.telemetry_window import WINDOW_SECONDS
from smartdrive.database.connection import Database
from smartdrive.models.diagnostic import DiagnosticAssessment
from smartdrive.models.vehicle import Vehicle
from smartdrive.services.diagnostic_service import DiagnosticService
from smartdrive.ui.monitoring_controller import MonitoringController, MonitoringState
from smartdrive.ui.workers.inference_worker import (
    InferenceRequest,
    InferenceResult,
    InferenceWorker,
)

logger = logging.getLogger(__name__)

THREAD_JOIN_TIMEOUT_MS: Final = 10_000
LIVE_TREND_POINTS: Final = 600


class DiagnosticsController(QObject):
    models_changed = Signal(object)
    assessment_changed = Signal(object)
    alerts_raised = Signal(object)
    error_occurred = Signal(str)

    _request_load = Signal()
    _request_analysis = Signal(object)
    _request_reset = Signal()

    def __init__(
        self,
        settings: AppSettings,
        database: Database,
        monitoring: MonitoringController,
        *,
        registry: ModelRegistry | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._monitoring = monitoring
        self._vehicle: Vehicle | None = None
        self.models: LoadedModels | None = None
        self.latest: DiagnosticAssessment | None = None
        self.last_inference_at: datetime | None = None
        self.last_error: str | None = None
        self.skipped_ticks = 0
        self.completed_runs = 0
        self.live_trend: deque[tuple[float, int | None]] = deque(maxlen=LIVE_TREND_POINTS)
        self._generation = 0
        self._busy = False
        self._closed = False

        self._worker = InferenceWorker(registry or ModelRegistry(), DiagnosticService(database))
        self._thread = QThread()
        self._thread.setObjectName("smartdrive-inference")
        self._worker.moveToThread(self._thread)
        self._request_load.connect(self._worker.load_models)
        self._request_analysis.connect(self._worker.analyse)
        self._request_reset.connect(self._worker.reset)
        self._worker.models_loaded.connect(self._on_models_loaded)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()
        self._request_load.emit()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self.apply_settings()
        monitoring.state_changed.connect(self._on_monitoring_state)

    # -- state --------------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._settings.diagnostics.enabled

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def models_loading(self) -> bool:
        return self.models is None

    def model_status(self, name: str) -> LoadStatus | None:
        return None if self.models is None else self.models.status.get(name)

    def thread_running(self) -> bool:
        return self._thread.isRunning()

    # -- configuration ------------------------------------------------------------------------

    def apply_settings(self) -> None:
        self._timer.setInterval(round(self._settings.diagnostics.inference_interval_s * 1000))
        self._update_timer()

    def set_vehicle(self, vehicle: Vehicle | None) -> None:
        previous = self._vehicle.id if self._vehicle else None
        self._vehicle = vehicle
        if (vehicle.id if vehicle else None) != previous:
            self._restart_stream()

    def reload_models(self) -> None:
        self.models = None
        self.models_changed.emit(None)
        self._request_load.emit()

    # -- running ------------------------------------------------------------------------------

    def tick(self) -> bool:
        """Dispatch one analysis if possible. Returns True when a job was sent."""
        monitoring = self._monitoring
        if self._closed or not self.enabled or self.models is None:
            return False
        if monitoring.state is not MonitoringState.RUNNING or monitoring.data_source is None:
            return False
        if self._busy:
            self.skipped_ticks += 1
            return False
        times, series = monitoring.buffer.snapshot(WINDOW_SECONDS)
        vehicle = self._vehicle
        request = InferenceRequest(
            generation=self._generation,
            times=times,
            series=series,
            data_source=monitoring.data_source,
            timestamp=datetime.now(UTC),
            data_age_s=monitoring.data_age_s(),
            stale_after_s=monitoring.stale_threshold_s,
            vehicle_id=vehicle.id if vehicle else None,
            session_id=monitoring.session_id,
            vehicle=VehicleContext(vehicle.fuel_type) if vehicle else None,
            settings=self._settings.diagnostics.model_copy(deep=True),
            alert_cooldown_s=float(self._settings.alerts.cooldown_seconds),
        )
        self._busy = True
        self._request_analysis.emit(request)
        return True

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._thread.quit()
        if not self._thread.wait(THREAD_JOIN_TIMEOUT_MS):
            logger.error("Inference thread did not stop within timeout")

    # -- worker results -----------------------------------------------------------------------

    def _on_models_loaded(self, models: object) -> None:
        if not isinstance(models, LoadedModels):
            return
        self.models = models
        self.models_changed.emit(models)
        self._update_timer()

    def _on_finished(self, result: object) -> None:
        if not isinstance(result, InferenceResult):
            return
        self._busy = False
        if result.generation != self._generation:
            return
        assessment = result.assessment
        if not isinstance(assessment, DiagnosticAssessment):
            return
        self.latest = assessment
        self.last_inference_at = assessment.timestamp
        self.last_error = result.persistence_error
        self.completed_runs += 1
        self.live_trend.append((assessment.elapsed_s, assessment.health.score))
        if result.persistence_error:
            self.error_occurred.emit(result.persistence_error)
        self.assessment_changed.emit(assessment)
        if result.outcome is not None and result.outcome.new_alerts:
            self.alerts_raised.emit(tuple(result.outcome.new_alerts))

    def _on_failed(self, generation: int, message: str) -> None:
        self._busy = False
        if generation != self._generation:
            return
        self.last_error = message
        self.error_occurred.emit(message)

    def _on_monitoring_state(self, state: object) -> None:
        if state is MonitoringState.STOPPED:
            self._restart_stream()
        self._update_timer()

    def _restart_stream(self) -> None:
        self._generation += 1
        self.latest = None
        self.live_trend.clear()
        if not self._closed:
            self._request_reset.emit()
        self.assessment_changed.emit(None)

    def _update_timer(self) -> None:
        should_run = (
            not self._closed
            and self.enabled
            and self.models is not None
            and self._monitoring.is_active
        )
        if should_run and not self._timer.isActive():
            self._timer.start()
        elif not should_run and self._timer.isActive():
            self._timer.stop()
