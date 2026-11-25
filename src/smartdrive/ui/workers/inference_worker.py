"""Runs model loading, hybrid diagnostics and diagnostic persistence on a background thread.

The worker owns the :class:`DiagnosticEngine` (whose rule and anomaly state must be updated by
one thread only) and its own :class:`DiagnosticService`. It never touches widgets; results leave
the thread as signals carrying immutable objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Slot

from smartdrive.ai.model_registry import LoadedModels, ModelRegistry
from smartdrive.config.constants import DataSource
from smartdrive.config.settings import DiagnosticSettings
from smartdrive.core.rule_engine import VehicleContext
from smartdrive.core.telemetry_window import TelemetryWindow
from smartdrive.services.diagnostic_engine import DiagnosticEngine
from smartdrive.services.diagnostic_service import DiagnosticService, RecordOutcome
from smartdrive.utils.exceptions import SmartDriveError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    """Everything one analysis needs, copied on the GUI thread."""

    generation: int
    times: list[float]
    series: dict[str, list[float]]
    data_source: DataSource
    timestamp: datetime
    data_age_s: float | None
    stale_after_s: float
    vehicle_id: int | None
    session_id: int | None
    vehicle: VehicleContext | None
    settings: DiagnosticSettings
    alert_cooldown_s: float


@dataclass(frozen=True, slots=True)
class InferenceResult:
    generation: int
    assessment: object  # DiagnosticAssessment (kept generic for the Qt signal)
    outcome: RecordOutcome | None
    persistence_error: str | None = None


class InferenceWorker(QObject):
    models_loaded = Signal(object)
    finished = Signal(object)
    failed = Signal(int, str)

    def __init__(self, registry: ModelRegistry, service: DiagnosticService) -> None:
        super().__init__()
        self._registry = registry
        self._service = service
        self._models: LoadedModels | None = None
        self._engine: DiagnosticEngine | None = None

    @Slot()
    def load_models(self) -> None:
        try:
            models = self._registry.load()
        except Exception as exc:
            logger.exception("Model registry failed")
            models = LoadedModels(None, None, {}, {"registry": str(exc)}, {})
        self._models = models
        try:
            self._service.register_models(models)
        except SmartDriveError:
            logger.exception("Could not record model metadata")
        self.models_loaded.emit(models)

    @Slot()
    def reset(self) -> None:
        if self._engine is not None:
            self._engine.reset()
        self._service.reset_stream()

    @Slot(object)
    def analyse(self, request: object) -> None:
        if not isinstance(request, InferenceRequest):
            return
        try:
            engine = self._engine_for(request)
            window = TelemetryWindow.from_series(request.times, request.series)
            recent_alerts = self._service.recent_alert_count(request.vehicle_id)
            assessment = engine.assess(
                window,
                data_source=request.data_source,
                timestamp=request.timestamp,
                data_age_s=request.data_age_s,
                stale_after_s=request.stale_after_s,
                vehicle_id=request.vehicle_id,
                session_id=request.session_id,
                recent_alerts=recent_alerts,
            )
        except Exception as exc:
            logger.exception("Diagnostic analysis failed")
            self.failed.emit(request.generation, f"Diagnostic analysis failed: {exc}")
            return
        outcome: RecordOutcome | None = None
        persistence_error: str | None = None
        if request.vehicle_id is not None:
            try:
                outcome = self._service.record(
                    assessment,
                    history_interval_s=request.settings.history_interval_s,
                    alert_cooldown_s=request.alert_cooldown_s,
                )
            except SmartDriveError as exc:
                persistence_error = exc.user_message
        self.finished.emit(
            InferenceResult(request.generation, assessment, outcome, persistence_error)
        )

    def _engine_for(self, request: InferenceRequest) -> DiagnosticEngine:
        if self._engine is None:
            self._engine = DiagnosticEngine(self._models, request.settings, request.vehicle)
        else:
            self._engine.configure(request.settings, request.vehicle)
        return self._engine
