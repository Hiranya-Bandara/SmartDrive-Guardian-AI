"""Top bar: page title, active vehicle selector, operating mode, connection and freshness."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from smartdrive.config.constants import DataSource
from smartdrive.models.vehicle import Vehicle
from smartdrive.ui.context import UiContext
from smartdrive.ui.monitoring_controller import ConnectionState, MonitoringState
from smartdrive.ui.widgets.base import label
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel

CONNECTION_TEXT: dict[ConnectionState, tuple[str, StatusLevel]] = {
    ConnectionState.IDLE: ("Not monitoring", StatusLevel.OFFLINE),
    ConnectionState.CONNECTED: ("Receiving data", StatusLevel.NORMAL),
    ConnectionState.NO_RESPONSE: ("No response", StatusLevel.CRITICAL),
    ConnectionState.STALE: ("Data stale", StatusLevel.WARNING),
}


def mode_status(state: MonitoringState, source: DataSource | None) -> tuple[str, StatusLevel]:
    if state is MonitoringState.STOPPED or source is None:
        return "Stopped", StatusLevel.OFFLINE
    name = {
        DataSource.SIMULATION: "Simulation",
        DataSource.LIVE: "Live vehicle",
        DataSource.REPLAY: "Replay",
    }[source]
    if state is MonitoringState.PAUSED:
        return f"{name} · paused", StatusLevel.WARNING
    level = StatusLevel.SIMULATION if source is DataSource.SIMULATION else StatusLevel.INFO
    return name, level


def format_age(seconds: float | None) -> str:
    if seconds is None:
        return "No data yet"
    if seconds < 1.5:
        return "Updated just now"
    if seconds < 90:
        return f"Updated {seconds:.0f} s ago"
    return f"Updated {seconds / 60:.0f} min ago"


class TopBar(QFrame):
    def __init__(self, ctx: UiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("TopBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = label("")
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = label("")
        self.subtitle_label.setObjectName("PageSubtitle")
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        layout.addLayout(titles, 1)

        self.vehicle_combo = QComboBox()
        self.vehicle_combo.setMinimumWidth(200)
        self.vehicle_combo.setToolTip("Active vehicle")
        self.vehicle_combo.setAccessibleName("Active vehicle")
        self.vehicle_combo.activated.connect(self._on_vehicle_chosen)
        self.mode_indicator = StatusIndicator(prefix="Mode: ")
        self.connection_indicator = StatusIndicator()
        self.freshness_label = label("No data yet", "muted")
        self.freshness_label.setMinimumWidth(130)
        for widget in (
            self.vehicle_combo,
            self.mode_indicator,
            self.connection_indicator,
            self.freshness_label,
        ):
            layout.addWidget(widget)

        monitoring = ctx.monitoring
        monitoring.state_changed.connect(self._refresh_status)
        monitoring.connection_changed.connect(self._refresh_status)
        ctx.state.vehicles_changed.connect(self.reload_vehicles)
        ctx.state.active_vehicle_changed.connect(self._select_active)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh_freshness)
        self._timer.start()
        self.reload_vehicles()
        self._refresh_status()

    def set_page(self, title: str, subtitle: str) -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)

    def reload_vehicles(self) -> None:
        vehicles = self.ctx.vehicles.list_vehicles()
        self.vehicle_combo.blockSignals(True)
        self.vehicle_combo.clear()
        if not vehicles:
            self.vehicle_combo.addItem("No vehicles — add one in the garage", None)
            self.vehicle_combo.setEnabled(False)
        else:
            self.vehicle_combo.setEnabled(True)
            if self.ctx.state.active_vehicle is None:
                self.vehicle_combo.addItem("Select active vehicle…", None)
            for vehicle in vehicles:
                self.vehicle_combo.addItem(vehicle.name, vehicle.id)
        self.vehicle_combo.blockSignals(False)
        self._select_active(self.ctx.state.active_vehicle)

    def _select_active(self, vehicle: object) -> None:
        if isinstance(vehicle, Vehicle):
            index = self.vehicle_combo.findData(vehicle.id)
            if index >= 0:
                self.vehicle_combo.setCurrentIndex(index)

    def _on_vehicle_chosen(self, index: int) -> None:
        vehicle_id = self.vehicle_combo.itemData(index)
        if isinstance(vehicle_id, int):
            if self.ctx.monitoring.session_id is not None:
                self.ctx.notifier.notify(
                    "Stop the current recording before changing the active vehicle.",
                    StatusLevel.WARNING,
                )
                self._select_active(self.ctx.state.active_vehicle)
                return
            self.ctx.state.set_active_vehicle(vehicle_id)

    def _refresh_status(self, *_: object) -> None:
        monitoring = self.ctx.monitoring
        self.mode_indicator.set_status(*mode_status(monitoring.state, monitoring.data_source))
        self.connection_indicator.set_status(*CONNECTION_TEXT[monitoring.connection])
        self._refresh_freshness()

    def _refresh_freshness(self) -> None:
        monitoring = self.ctx.monitoring
        if not monitoring.is_active and not monitoring.staleness.has_data:
            self.freshness_label.setText("No data yet")
            return
        age = monitoring.data_age_s()
        text = format_age(age)
        if not monitoring.is_active and age is not None:
            text = "Monitoring stopped"
        self.freshness_label.setText(text)
        self.freshness_label.setToolTip(
            f"Last successful reading: {monitoring.last_update_at:%Y-%m-%d %H:%M:%S} UTC"
            if monitoring.last_update_at
            else "No successful reading yet"
        )
