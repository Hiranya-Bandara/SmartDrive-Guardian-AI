"""Start/stop, pause/resume, source and record controls shared by several pages.

The source selector chooses between the simulator and a connected OBD-II adapter. Selecting
"Live vehicle" never connects to hardware: the adapter must already have been connected on the
Vehicle Connection page. Replay is started from Trip History.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QWidget

from smartdrive.config.constants import DataSource
from smartdrive.ui.context import UiContext
from smartdrive.ui.monitoring_controller import MonitoringState
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum

SOURCE_TEXT = {
    DataSource.SIMULATION: "Simulator",
    DataSource.LIVE: "Live vehicle (OBD-II)",
}


def preferred_source(ctx: UiContext) -> DataSource:
    mode = ctx.monitoring.preferred_mode
    return DataSource.LIVE if mode == "live" else DataSource.SIMULATION


def toggle_monitoring(ctx: UiContext) -> None:
    """Start monitoring from the selected source (recording if requested) or stop it."""
    monitoring = ctx.monitoring
    if monitoring.is_active:
        monitoring.stop()
        if monitoring.persisted_count:
            ctx.notifier.notify(f"Session saved with {monitoring.persisted_count} readings.")
        return
    vehicle = ctx.state.active_vehicle
    record = ctx.monitoring.record_requested and vehicle is not None
    vehicle_id = vehicle.id if vehicle else None
    if preferred_source(ctx) is DataSource.LIVE:
        monitoring.start_live(ctx.connection, record=record, vehicle_id=vehicle_id)
    else:
        monitoring.start(record=record, vehicle_id=vehicle_id)


def toggle_pause(ctx: UiContext) -> None:
    if ctx.monitoring.state is MonitoringState.RUNNING:
        ctx.monitoring.pause()
    elif ctx.monitoring.state is MonitoringState.PAUSED:
        ctx.monitoring.resume()


class MonitoringControls(QWidget):
    def __init__(
        self, ctx: UiContext, *, show_record: bool = True, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.start_button = IconPushButton(
            "Start monitoring",
            "play",
            variant="primary",
            tooltip="Start or stop monitoring (Ctrl+M)",
        )
        self.pause_button = IconPushButton(
            "Pause", "pause", tooltip="Pause or resume monitoring (Ctrl+P)"
        )
        self.source_combo = QComboBox()
        self.source_combo.setAccessibleName("Telemetry source")
        self.source_combo.setToolTip(
            "Simulator, or a vehicle already connected on the Vehicle Connection page"
        )
        for source, text in SOURCE_TEXT.items():
            self.source_combo.addItem(text, source)
        self.record_check = QCheckBox("Record session")
        self.record_check.setToolTip("Save telemetry to the active vehicle's history")
        self.record_check.setChecked(ctx.monitoring.record_requested)
        self.record_check.setVisible(show_record)
        layout.addWidget(self.source_combo)
        layout.addWidget(self.start_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.record_check)
        layout.addStretch(1)

        self.start_button.clicked.connect(lambda: toggle_monitoring(ctx))
        self.pause_button.clicked.connect(lambda: toggle_pause(ctx))
        self.record_check.toggled.connect(self._on_record_toggled)
        self.source_combo.currentIndexChanged.connect(self._on_source_selected)
        ctx.monitoring.state_changed.connect(self.refresh)
        ctx.monitoring.preferred_mode_changed.connect(self.refresh)
        ctx.connection.status_changed.connect(self.refresh)
        ctx.monitoring.record_requested_changed.connect(self._sync_record)
        ctx.state.active_vehicle_changed.connect(self.refresh)
        self.refresh()

    def _on_source_selected(self, _index: int) -> None:
        source = combo_enum(self.source_combo, DataSource)
        mode = "live" if source is DataSource.LIVE else "simulation"
        self.ctx.monitoring.set_preferred_mode(mode)

    def _on_record_toggled(self, checked: bool) -> None:
        self.ctx.monitoring.set_record_requested(checked)

    def _sync_record(self, value: bool) -> None:
        if self.record_check.isChecked() != value:
            self.record_check.setChecked(value)

    def refresh(self, *_: object) -> None:
        state = self.ctx.monitoring.state
        active = state is not MonitoringState.STOPPED
        self.start_button.setText("Stop monitoring" if active else "Start monitoring")
        self.start_button.set_icon_name("stop" if active else "play")
        self.start_button.setProperty("variant", "danger" if active else "primary")
        self.pause_button.setEnabled(active)
        wanted = preferred_source(self.ctx)
        index = self.source_combo.findData(wanted)
        if index >= 0 and index != self.source_combo.currentIndex():
            self.source_combo.blockSignals(True)
            self.source_combo.setCurrentIndex(index)
            self.source_combo.blockSignals(False)
        self.source_combo.setEnabled(not active)
        live_ready = self.ctx.connection.ecu_connected
        can_start = active or wanted is not DataSource.LIVE or live_ready
        self.start_button.setEnabled(can_start)
        self.start_button.setToolTip(
            "Start or stop monitoring (Ctrl+M)"
            if can_start
            else "Connect to the vehicle on the Vehicle Connection page first"
        )
        self.pause_button.setText("Resume" if state is MonitoringState.PAUSED else "Pause")
        self.pause_button.set_icon_name("play" if state is MonitoringState.PAUSED else "pause")
        has_vehicle = self.ctx.state.active_vehicle is not None
        self.record_check.setEnabled(has_vehicle and not active)
        self.record_check.setToolTip(
            "Save telemetry to the active vehicle's history"
            if has_vehicle
            else "Select an active vehicle to record sessions"
        )
        for button in (self.start_button, self.pause_button):
            button.style().unpolish(button)
            button.style().polish(button)
            button.apply_palette(self.ctx.theme.palette)

    def apply_palette(self, palette: ThemePalette) -> None:
        self.start_button.apply_palette(palette)
        self.pause_button.apply_palette(palette)
