"""Shared GUI state and the service container handed to every page."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from smartdrive.app import ApplicationContext
from smartdrive.models.vehicle import Vehicle
from smartdrive.services.diagnostic_service import DiagnosticService
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.vehicle_service import VehicleService
from smartdrive.ui.diagnostics_controller import DiagnosticsController
from smartdrive.ui.monitoring_controller import MonitoringController
from smartdrive.ui.themes.theme_manager import ThemeManager
from smartdrive.ui.widgets.status import StatusLevel
from smartdrive.utils.exceptions import SmartDriveError
from smartdrive.utils.logger import configure_logging

logger = logging.getLogger(__name__)


class Notifier(QObject):
    message = Signal(str, object)

    def notify(self, text: str, level: StatusLevel = StatusLevel.INFO) -> None:
        self.message.emit(text, level)


class AppState(QObject):
    vehicles_changed = Signal()
    active_vehicle_changed = Signal(object)
    settings_changed = Signal(object)

    def __init__(self, app: ApplicationContext, vehicles: VehicleService) -> None:
        super().__init__()
        self._app = app
        self._vehicles = vehicles
        self._active: Vehicle | None = vehicles.get_active()

    @property
    def active_vehicle(self) -> Vehicle | None:
        return self._active

    def set_active_vehicle(self, vehicle_id: int | None) -> None:
        if vehicle_id is None:
            return
        if self._active is not None and self._active.id == vehicle_id:
            return
        self._active = self._vehicles.set_active(vehicle_id)
        self.active_vehicle_changed.emit(self._active)
        self.vehicles_changed.emit()

    def reload(self) -> None:
        """Re-read vehicles after any garage change (add, edit, delete)."""
        previous = self._active.id if self._active else None
        self._active = self._vehicles.get_active()
        self.vehicles_changed.emit()
        current = self._active.id if self._active else None
        if previous != current or self._active is not None:
            self.active_vehicle_changed.emit(self._active)

    def save_settings(self) -> None:
        try:
            self._app.save_settings()
        except SmartDriveError:
            logger.exception("Saving preferences failed")
            raise
        settings = self._app.settings
        configure_logging(
            self._app.paths.log_file,
            level=settings.logging.level,
            redact=settings.privacy.redact_identifiers_in_logs,
        )
        self.settings_changed.emit(settings)


@dataclass(slots=True)
class UiContext:
    app: ApplicationContext
    state: AppState
    theme: ThemeManager
    monitoring: MonitoringController
    vehicles: VehicleService
    telemetry: TelemetryService
    notifier: Notifier
    diagnostics: DiagnosticsController
    diagnostic_history: DiagnosticService
