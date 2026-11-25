"""Simulation laboratory: scenario selection, manual controls and ground-truth labels."""

from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from smartdrive.config.constants import UnitSystem
from smartdrive.core.sensors import SENSOR_BY_KEY
from smartdrive.core.units import MISSING_TEXT
from smartdrive.services.data_source import TelemetryFrame
from smartdrive.services.scenarios import SCENARIOS, ScenarioId, SimulationLabels
from smartdrive.services.simulator import SimulationConfig
from smartdrive.ui.context import UiContext
from smartdrive.ui.pages.base import Page
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label, set_props
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.monitoring_controls import MonitoringControls
from smartdrive.ui.widgets.notifications import Banner
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel

SPEED_FACTORS = (0.5, 1.0, 2.0, 5.0, 10.0)
REFRESH_MS = 250
LAB_NOTICE = (
    "Everything on this page is synthetic. Scenarios are illustrative test conditions, not "
    "calibrated models of any real vehicle."
)


@dataclass(frozen=True, slots=True)
class OverrideSpec:
    key: str
    minimum: int
    maximum: int
    default: int
    scale: float = 1.0  # slider units per sensor unit


OVERRIDES = (
    OverrideSpec("coolant_temp_c", -40, 130, 90),
    OverrideSpec("oil_pressure_kpa", 0, 700, 250),
    OverrideSpec("control_module_voltage_v", 100, 160, 141, scale=10.0),
    OverrideSpec("fuel_level_pct", 0, 100, 50),
    OverrideSpec("intake_air_temp_c", -20, 80, 35),
    OverrideSpec("engine_load_pct", 0, 100, 40),
)


class OverrideRow(QWidget):
    def __init__(self, spec: OverrideSpec, page: SimulationLabPage) -> None:
        super().__init__()
        self.spec = spec
        self._page = page
        sensor = SENSOR_BY_KEY[spec.key]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox(sensor.label)
        self.check.setMinimumWidth(210)
        self.check.setToolTip(f"Force the reported {sensor.label.lower()} value")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(spec.minimum, spec.maximum)
        self.slider.setValue(spec.default)
        self.slider.setEnabled(False)
        self.slider.setAccessibleName(f"{sensor.label} override value")
        self.value_label = label("", "muted")
        self.value_label.setMinimumWidth(80)
        layout.addWidget(self.check)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)
        self.check.toggled.connect(self._changed)
        self.slider.valueChanged.connect(self._changed)
        self._update_label()

    def value(self) -> float:
        return self.slider.value() / self.spec.scale

    def _update_label(self) -> None:
        sensor = SENSOR_BY_KEY[self.spec.key]
        self.value_label.setText(
            f"{self.value():.{sensor.decimals}f} {sensor.unit(UnitSystem.METRIC)}"
        )

    def _changed(self, *_: object) -> None:
        self.slider.setEnabled(self.check.isChecked())
        self._update_label()
        self._page.ctx.monitoring.set_output_override(
            self.spec.key, self.value() if self.check.isChecked() else None
        )


class SimulationLabPage(Page):
    key = "simulation"
    title = "Simulation Laboratory"
    subtitle = "Reproducible synthetic driving scenarios with ground-truth labels"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._dirty = False
        self.content.addWidget(Banner(LAB_NOTICE, StatusLevel.SIMULATION))

        run_card = Card("Run")
        run_row = QHBoxLayout()
        self.controls = MonitoringControls(ctx)
        run_row.addWidget(self.controls, 1)
        run_row.addWidget(label("Simulation speed", "muted"))
        self.speed_combo = QComboBox()
        self.speed_combo.setAccessibleName("Simulation speed")
        for factor in SPEED_FACTORS:
            self.speed_combo.addItem(f"{factor:g}×", factor)
        self.speed_combo.setCurrentIndex(SPEED_FACTORS.index(1.0))
        run_row.addWidget(self.speed_combo)
        self.reset_button = IconPushButton(
            "Reset run", "refresh", tooltip="Restart the scenario from t = 0 with the same seed"
        )
        run_row.addWidget(self.reset_button)
        run_card.body.addLayout(run_row)
        self.content.addWidget(run_card)

        grid = QGridLayout()
        grid.setSpacing(16)

        scenario_card = Card("Scenario")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.scenario_combo = QComboBox()
        self.scenario_combo.setAccessibleName("Scenario")
        for definition in SCENARIOS.values():
            self.scenario_combo.addItem(definition.title, definition.id)
        self.description_label = label("", "muted", wrap=True)
        seed_row = QHBoxLayout()
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2_147_483_647)
        self.seed_spin.setValue(42)
        self.seed_spin.setAccessibleName("Random seed")
        self.random_seed_button = IconPushButton(
            "", "shuffle", variant="ghost", tooltip="Pick a new random seed"
        )
        seed_row.addWidget(self.seed_spin, 1)
        seed_row.addWidget(self.random_seed_button)
        self.noise_slider = QSlider(Qt.Orientation.Horizontal)
        self.noise_slider.setRange(0, 300)
        self.noise_slider.setValue(100)
        self.noise_slider.setAccessibleName("Measurement noise")
        self.noise_label = label("100 %", "muted")
        self.noise_label.setMinimumWidth(52)
        noise_row = QHBoxLayout()
        noise_row.addWidget(self.noise_slider, 1)
        noise_row.addWidget(self.noise_label)
        self.ambient_spin = QSpinBox()
        self.ambient_spin.setRange(-30, 50)
        self.ambient_spin.setValue(30)
        self.ambient_spin.setSuffix(" °C")
        self.ambient_spin.setAccessibleName("Ambient temperature")
        development_row = QHBoxLayout()
        self.development_check = QCheckBox("Override")
        self.development_spin = QSpinBox()
        self.development_spin.setRange(0, 3600)
        self.development_spin.setValue(120)
        self.development_spin.setSuffix(" s")
        self.development_spin.setEnabled(False)
        self.development_spin.setAccessibleName("Abnormality development time")
        self.development_check.toggled.connect(self.development_spin.setEnabled)
        development_row.addWidget(self.development_check)
        development_row.addWidget(self.development_spin, 1)
        self.apply_button = IconPushButton("Apply scenario", "check", variant="primary")
        form.addRow("Scenario", self.scenario_combo)
        form.addRow("", self.description_label)
        form.addRow("Random seed", seed_row)
        form.addRow("Measurement noise", noise_row)
        form.addRow("Ambient temperature", self.ambient_spin)
        form.addRow("Abnormality development", development_row)
        scenario_card.body.addLayout(form)
        scenario_card.body.addWidget(self.apply_button, 0, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(scenario_card, 0, 0)

        truth_card = Card("Ground truth")
        self.elapsed_label = label("Not running", "section-title")
        self.scenario_pill = StatusIndicator(prefix="Scenario: ")
        self.link_pill = StatusIndicator(prefix="Data link: ")
        self.faults_box = QVBoxLayout()
        self.faults_box.setSpacing(6)
        self.no_faults_label = label("No abnormalities injected at this moment.", "muted")
        self.faults_box.addWidget(self.no_faults_label)
        self.fault_rows: dict[str, tuple[QWidget, QProgressBar, QLabel]] = {}
        self.dropped_label = label("", "muted", wrap=True)
        self.overridden_label = label("", "muted", wrap=True)
        truth_card.body.addWidget(self.elapsed_label)
        pills = QHBoxLayout()
        pills.addWidget(self.scenario_pill)
        pills.addWidget(self.link_pill)
        pills.addStretch(1)
        truth_card.body.addLayout(pills)
        truth_card.body.addWidget(label("Injected abnormalities (severity)", "card-title"))
        truth_card.body.addLayout(self.faults_box)
        truth_card.body.addWidget(self.dropped_label)
        truth_card.body.addWidget(self.overridden_label)
        truth_card.body.addStretch(1)
        grid.addWidget(truth_card, 0, 1)

        manual_card = Card("Manual controls")
        driver_row = QHBoxLayout()
        self.driver_check = QCheckBox("Manual driver — target speed")
        self.driver_check.setMinimumWidth(210)
        self.target_slider = QSlider(Qt.Orientation.Horizontal)
        self.target_slider.setRange(0, 160)
        self.target_slider.setValue(60)
        self.target_slider.setEnabled(False)
        self.target_slider.setAccessibleName("Target speed")
        self.target_label = label("60 km/h", "muted")
        self.target_label.setMinimumWidth(80)
        driver_row.addWidget(self.driver_check)
        driver_row.addWidget(self.target_slider, 1)
        driver_row.addWidget(self.target_label)
        manual_card.body.addLayout(driver_row)
        manual_card.body.addWidget(
            label(
                "Sensor overrides force the reported value; the vehicle model keeps running.",
                "muted",
                wrap=True,
            )
        )
        self.override_rows = [OverrideRow(spec, self) for spec in OVERRIDES]
        for row in self.override_rows:
            manual_card.body.addWidget(row)
        grid.addWidget(manual_card, 1, 0)

        readout_card = Card("Current readings")
        readout = QFormLayout()
        self.readout_labels: dict[str, QLabel] = {}
        for key in (
            "speed_kph",
            "rpm",
            "coolant_temp_c",
            "oil_pressure_kpa",
            "control_module_voltage_v",
            "fuel_rate_lph",
        ):
            value = label(MISSING_TEXT)
            self.readout_labels[key] = value
            readout.addRow(label(SENSOR_BY_KEY[key].label, "muted"), value)
        readout_card.body.addLayout(readout)
        readout_card.body.addStretch(1)
        grid.addWidget(readout_card, 1, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        self.content.addLayout(grid)
        self.content.addStretch(1)

        self.scenario_combo.currentIndexChanged.connect(lambda _i: self._update_description())
        self.random_seed_button.clicked.connect(self._randomise_seed)
        self.noise_slider.valueChanged.connect(lambda v: self.noise_label.setText(f"{v} %"))
        self.apply_button.clicked.connect(self.apply_scenario)
        self.reset_button.clicked.connect(self.reset_run)
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        self.driver_check.toggled.connect(self._on_driver_changed)
        self.target_slider.valueChanged.connect(self._on_driver_changed)
        ctx.monitoring.simulation_changed.connect(self.sync_from_controller)
        ctx.monitoring.frame_received.connect(self._on_frame)
        ctx.monitoring.state_changed.connect(self._render)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self.sync_from_controller()

    def on_shown(self) -> None:
        self.sync_from_controller()

    # -- configuration ------------------------------------------------------------------------

    def sync_from_controller(self) -> None:
        """Show the configuration that is actually in effect."""
        monitoring = self.ctx.monitoring
        self._load_config(monitoring.simulation_config)
        index = self.speed_combo.findData(monitoring.speed_factor)
        self.speed_combo.blockSignals(True)
        if index < 0:
            self.speed_combo.addItem(f"{monitoring.speed_factor:g}×", monitoring.speed_factor)
            index = self.speed_combo.count() - 1
        self.speed_combo.setCurrentIndex(index)
        self.speed_combo.blockSignals(False)
        self._render()

    def _load_config(self, config: SimulationConfig) -> None:
        self.scenario_combo.setCurrentIndex(self.scenario_combo.findData(config.scenario))
        self.seed_spin.setValue(config.seed)
        self.noise_slider.setValue(round(config.noise_scale * 100))
        self.ambient_spin.setValue(round(config.ambient_c))
        self.development_check.setChecked(config.fault_development_s is not None)
        if config.fault_development_s is not None:
            self.development_spin.setValue(round(config.fault_development_s))
        self._update_description()

    def build_config(self) -> SimulationConfig:
        scenario = combo_enum(self.scenario_combo, ScenarioId) or ScenarioId.NORMAL
        return SimulationConfig(
            scenario=scenario,
            seed=self.seed_spin.value(),
            noise_scale=self.noise_slider.value() / 100.0,
            ambient_c=float(self.ambient_spin.value()),
            fault_development_s=float(self.development_spin.value())
            if self.development_check.isChecked()
            else None,
        )

    def apply_scenario(self) -> None:
        config = self.build_config()
        self.ctx.monitoring.configure_simulation(config)
        self.ctx.notifier.notify(
            f"Scenario set: {config.definition.title} (seed {config.seed}).",
            StatusLevel.SIMULATION,
        )
        self._render()

    def reset_run(self) -> None:
        self.ctx.monitoring.reset_simulation()
        self._render()

    def _update_description(self) -> None:
        scenario = combo_enum(self.scenario_combo, ScenarioId)
        self.description_label.setText(SCENARIOS[scenario].description if scenario else "")

    def _randomise_seed(self) -> None:
        self.seed_spin.setValue(random.SystemRandom().randrange(0, 1_000_000))

    def _on_speed_changed(self, _index: int) -> None:
        factor = self.speed_combo.currentData()
        if isinstance(factor, float):
            self.ctx.monitoring.set_speed_factor(factor)

    def _on_driver_changed(self, *_: object) -> None:
        enabled = self.driver_check.isChecked()
        self.target_slider.setEnabled(enabled)
        self.target_label.setText(f"{self.target_slider.value()} km/h")
        self.ctx.monitoring.set_target_speed(float(self.target_slider.value()) if enabled else None)

    # -- live ground truth --------------------------------------------------------------------

    def _on_frame(self, frame: object) -> None:
        if isinstance(frame, TelemetryFrame):
            self._dirty = True

    def _refresh(self) -> None:
        if self._dirty and self.isVisible():
            self._dirty = False
            self._render()

    def _render(self, *_args: object) -> None:
        monitoring = self.ctx.monitoring
        frame = monitoring.last_frame if monitoring.is_active else None
        config = monitoring.simulation_config
        self.scenario_pill.set_status(config.definition.title, StatusLevel.SIMULATION)
        if frame is None or frame.labels is None:
            self.elapsed_label.setText("Not running")
            self.link_pill.set_status("Idle", StatusLevel.OFFLINE)
            self._show_faults(None)
            for value in self.readout_labels.values():
                value.setText(MISSING_TEXT)
            self.dropped_label.setText("")
            self.overridden_label.setText("")
            return
        labels = frame.labels
        minutes, seconds = divmod(int(frame.elapsed_s), 60)
        self.elapsed_label.setText(f"Simulated time {minutes:02d}:{seconds:02d}")
        self.link_pill.set_status(
            "Lost (simulated)" if labels.connection_lost else "Connected",
            StatusLevel.CRITICAL if labels.connection_lost else StatusLevel.NORMAL,
        )
        self._show_faults(labels)
        self.dropped_label.setText(
            "Dropped this reading: "
            + ", ".join(SENSOR_BY_KEY[k].label for k in labels.dropped_sensors)
            if labels.dropped_sensors
            else ""
        )
        self.overridden_label.setText(
            "Manually overridden: "
            + ", ".join(SENSOR_BY_KEY[k].label for k in labels.overridden_sensors)
            if labels.overridden_sensors
            else ""
        )
        system = self.ctx.app.settings.units.system
        for key, value_label in self.readout_labels.items():
            raw = getattr(frame.sample, key) if frame.sample is not None else None
            value_label.setText(SENSOR_BY_KEY[key].format(raw, system))

    def _show_faults(self, labels: SimulationLabels | None) -> None:
        faults = dict(labels.faults) if labels else {}
        for kind, (row, _bar, _text) in list(self.fault_rows.items()):
            if kind not in faults:
                row.hide()
        for kind, severity in faults.items():
            if kind not in self.fault_rows:
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                name = label(kind.value.replace("_", " ").capitalize())
                name.setMinimumWidth(180)
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setAccessibleName(f"{name.text()} severity")
                text = label("", "muted")
                text.setMinimumWidth(48)
                layout.addWidget(name)
                layout.addWidget(bar, 1)
                layout.addWidget(text)
                self.faults_box.addWidget(row)
                self.fault_rows[kind] = (row, bar, text)
            row, bar, text = self.fault_rows[kind]
            percent = round(severity * 100)
            bar.setValue(percent)
            set_props(bar, level="critical" if severity >= 0.75 else "warning")
            text.setText(f"{percent} %")
            row.show()
        self.no_faults_label.setVisible(not faults)
