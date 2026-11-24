"""Start/stop, pause/resume and record controls shared by several pages."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

from smartdrive.ui.context import UiContext
from smartdrive.ui.monitoring_controller import MonitoringState
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton


def toggle_monitoring(ctx: UiContext) -> None:
    """Start monitoring (recording if requested and possible) or stop it."""
    monitoring = ctx.monitoring
    if monitoring.is_active:
        monitoring.stop()
        if monitoring.persisted_count:
            ctx.notifier.notify(f"Session saved with {monitoring.persisted_count} readings.")
        return
    vehicle = ctx.state.active_vehicle
    record = ctx.monitoring.record_requested and vehicle is not None
    monitoring.start(record=record, vehicle_id=vehicle.id if vehicle else None)


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
        self.record_check = QCheckBox("Record session")
        self.record_check.setToolTip("Save telemetry to the active vehicle's history")
        self.record_check.setChecked(ctx.monitoring.record_requested)
        self.record_check.setVisible(show_record)
        layout.addWidget(self.start_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.record_check)
        layout.addStretch(1)

        self.start_button.clicked.connect(lambda: toggle_monitoring(ctx))
        self.pause_button.clicked.connect(lambda: toggle_pause(ctx))
        self.record_check.toggled.connect(self._on_record_toggled)
        ctx.monitoring.state_changed.connect(self.refresh)
        ctx.monitoring.record_requested_changed.connect(self._sync_record)
        ctx.state.active_vehicle_changed.connect(self.refresh)
        self.refresh()

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
