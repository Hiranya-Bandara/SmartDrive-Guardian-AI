"""Dashboard: active vehicle, instrument cluster, live trends and recent alerts."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from smartdrive.ai.model_registry import CLASSIFIER_NAME
from smartdrive.config.constants import DataSource, Severity, UnitSystem
from smartdrive.core.sensors import SENSOR_BY_KEY
from smartdrive.core.units import MISSING_TEXT
from smartdrive.models.alert import Alert
from smartdrive.models.diagnostic import SEVERITY_RANK, DiagnosticStatus
from smartdrive.models.vehicle import Vehicle
from smartdrive.services.data_source import TelemetryFrame
from smartdrive.ui.context import UiContext
from smartdrive.ui.dialogs.vehicle_dialog import enum_label
from smartdrive.ui.icons import pixmap
from smartdrive.ui.monitoring_controller import MonitoringState
from smartdrive.ui.pages.ai_diagnostics import (
    RUN_STATUS_TEXT,
    STATUS_DISPLAY,
    format_time,
    model_status_pill,
)
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.top_bar import CONNECTION_TEXT, format_age, mode_status
from smartdrive.ui.widgets.base import IconPushButton, label
from smartdrive.ui.widgets.cards import Card, MetricCard
from smartdrive.ui.widgets.charts import ChartContainer
from smartdrive.ui.widgets.gauges import CircularGauge, GaugeBand, LinearGauge
from smartdrive.ui.widgets.health_score import HealthScoreWidget
from smartdrive.ui.widgets.monitoring_controls import MonitoringControls
from smartdrive.ui.widgets.notifications import Banner
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel

TREND_WINDOW_S = 120.0
REFRESH_MS = 250

SEVERITY_LEVEL = {
    Severity.CRITICAL: StatusLevel.CRITICAL,
    Severity.WARNING: StatusLevel.WARNING,
    Severity.NORMAL: StatusLevel.NORMAL,
    Severity.INFORMATION: StatusLevel.INFO,
    Severity.UNKNOWN: StatusLevel.OFFLINE,
}

SIMULATION_NOTICE = "Simulated telemetry. Values are synthetic and do not describe a real vehicle."


def coolant_bands(system: UnitSystem) -> tuple[GaugeBand, ...]:
    spec = SENSOR_BY_KEY["coolant_temp_c"]
    return (
        GaugeBand(spec.to_display(105, system), spec.to_display(115, system), "warning"),
        GaugeBand(spec.to_display(115, system), spec.to_display(130, system), "critical"),
    )


RPM_BANDS = (GaugeBand(5500, 6200, "warning"), GaugeBand(6200, 7000, "critical"))


class VehicleSummary(Card):
    open_garage = Signal()

    def __init__(self, ctx: UiContext) -> None:
        super().__init__("Active vehicle")
        self.ctx = ctx
        row = QHBoxLayout()
        row.setSpacing(16)
        self.image = QLabel()
        self.image.setFixedSize(150, 96)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setAccessibleName("Vehicle illustration")
        details = QVBoxLayout()
        details.setSpacing(4)
        self.name_label = label("No active vehicle", "section-title")
        self.detail_label = label("", "muted", wrap=True)
        self.mileage_label = label("", "muted")
        self.garage_button = IconPushButton("Open garage", "car")
        self.garage_button.clicked.connect(self.open_garage)
        details.addWidget(self.name_label)
        details.addWidget(self.detail_label)
        details.addWidget(self.mileage_label)
        details.addStretch(1)
        details.addWidget(self.garage_button, 0, Qt.AlignmentFlag.AlignLeft)
        row.addWidget(self.image)
        row.addLayout(details, 1)
        self.body.addLayout(row)

    def show_vehicle(self, vehicle: Vehicle | None, palette: ThemePalette) -> None:
        self.garage_button.apply_palette(palette)
        if vehicle is None:
            self.name_label.setText("No active vehicle")
            self.detail_label.setText(
                "Add a vehicle in the garage and set it active to record sessions. "
                "Simulation works without one."
            )
            self.mileage_label.setText("")
            self.garage_button.show()
            self.image.setPixmap(pixmap("car", palette.offline, 72))
            return
        self.garage_button.hide()
        self.name_label.setText(vehicle.name)
        engine = f" · {vehicle.engine_capacity_cc} cc" if vehicle.engine_capacity_cc else ""
        self.detail_label.setText(
            f"{vehicle.year} {vehicle.manufacturer} {vehicle.model} · "
            f"{enum_label(vehicle.fuel_type.value)} · "
            f"{enum_label(vehicle.transmission.value)}{engine}"
        )
        system = self.ctx.app.settings.units.system
        miles = system is UnitSystem.IMPERIAL
        distance = vehicle.mileage_km / 1.609344 if miles else vehicle.mileage_km
        self.mileage_label.setText(f"Odometer: {distance:,.0f} {'mi' if miles else 'km'}")
        image_file = self.ctx.vehicles.image_file(vehicle)
        image = QPixmap(str(image_file)) if image_file else QPixmap()
        if not image.isNull():
            self.image.setPixmap(
                image.scaled(
                    self.image.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.image.setPixmap(pixmap("car", palette.accent, 72))


class AlertsCard(Card):
    def __init__(self) -> None:
        super().__init__("Recent alerts")
        self._list_widget = QWidget()
        self._rows = QVBoxLayout(self._list_widget)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(6)
        self._rows.addStretch(1)
        self.stack = StatefulStack(self._list_widget)
        self.stack.setMinimumHeight(150)
        self.body.addWidget(self.stack)

    def show_alerts(self, alerts: list[Alert]) -> None:
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        if not alerts:
            self.stack.show_empty(
                "No alerts recorded",
                "Warning and critical diagnostic findings for the active vehicle appear here. "
                "The absence of alerts does not mean the vehicle is safe to drive.",
            )
            return
        for alert in alerts:
            row = QHBoxLayout()
            pill = StatusIndicator(alert.severity.value.title(), SEVERITY_LEVEL[alert.severity])
            text = label(f"{alert.title}\n{alert.last_occurrence_at:%Y-%m-%d %H:%M}", wrap=True)
            row.addWidget(pill)
            row.addWidget(text, 1)
            holder = QWidget()
            holder.setLayout(row)
            self._rows.insertWidget(self._rows.count() - 1, holder)
        self.stack.show_content()


class DiagnosticsSummary(Card):
    """Compact view of the latest hybrid assessment, with an explicit state when there is none."""

    open_details = Signal()

    def __init__(self, ctx: UiContext) -> None:
        super().__init__("AI diagnostics (experimental)")
        self.ctx = ctx
        row = QHBoxLayout()
        row.setSpacing(18)
        self.health = HealthScoreWidget(compact=True)
        row.addWidget(self.health, 0, Qt.AlignmentFlag.AlignTop)
        facts = QVBoxLayout()
        facts.setSpacing(6)
        self.status_pill = StatusIndicator(prefix="Diagnostic status: ")
        self.models_pill = StatusIndicator()
        pills = QHBoxLayout()
        pills.addWidget(self.status_pill)
        pills.addWidget(self.models_pill)
        pills.addStretch(1)
        facts.addLayout(pills)
        self.warnings_label = label("", wrap=True)
        self.anomaly_label = label("", "muted", wrap=True)
        self.inference_label = label("", "muted")
        facts.addWidget(self.warnings_label)
        facts.addWidget(self.anomaly_label)
        facts.addWidget(self.inference_label)
        row.addLayout(facts, 2)
        findings = QVBoxLayout()
        findings.addWidget(label("Current findings", "card-title"))
        self.findings_label = label("", wrap=True)
        findings.addWidget(self.findings_label)
        findings.addStretch(1)
        self.details_button = IconPushButton("Open AI Diagnostics", "cpu", variant="ghost")
        self.details_button.clicked.connect(self.open_details)
        findings.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignRight)
        row.addLayout(findings, 3)
        self.body.addLayout(row)
        ctx.diagnostics.assessment_changed.connect(lambda _a: self.refresh_view())
        ctx.diagnostics.models_changed.connect(self.refresh_view)
        ctx.monitoring.state_changed.connect(lambda _s: self.refresh_view())
        self.refresh_view()

    def refresh_view(self) -> None:
        ctx = self.ctx
        latest = ctx.diagnostics.latest
        self.health.set_health(latest.health if latest else None)
        classifier_text, classifier_level = model_status_pill(ctx, CLASSIFIER_NAME, "Models")
        self.models_pill.set_status(classifier_text, classifier_level)
        self.inference_label.setText(
            f"Last inference: {format_time(ctx.diagnostics.last_inference_at)}"
        )
        if latest is None:
            idle = (
                "Monitoring stopped"
                if not ctx.monitoring.is_active
                else "Loading models"
                if ctx.diagnostics.models_loading
                else "Collecting telemetry"
            )
            self.status_pill.set_status(idle, StatusLevel.OFFLINE)
            self.warnings_label.setText("Active warnings: —")
            self.anomaly_label.setText("Anomaly detection: —")
            self.findings_label.setText("No assessment yet.")
            return
        self.status_pill.set_status(*STATUS_DISPLAY[latest.status])
        self.warnings_label.setText(f"Active warnings: {latest.warning_count}")
        anomaly = latest.anomaly
        if anomaly.score is None:
            self.anomaly_label.setText(f"Anomaly detection: {RUN_STATUS_TEXT[anomaly.status]}")
        else:
            state = (
                "persistent unusual pattern"
                if anomaly.persistent
                else ("unusual reading" if anomaly.is_anomalous else "within normal range")
            )
            self.anomaly_label.setText(f"Anomaly detection: {state} (score {anomaly.score:.3f})")
        if latest.findings:
            ordered = sorted(latest.findings, key=lambda f: SEVERITY_RANK[f.severity], reverse=True)
            self.findings_label.setText(
                "\n".join(f"{f.severity.value.title()} — {f.title}" for f in ordered[:4])
            )
        elif latest.status is DiagnosticStatus.INSUFFICIENT_DATA:
            self.findings_label.setText(f"Insufficient data: {latest.quality.reason}")
        elif latest.status is DiagnosticStatus.STALE:
            self.findings_label.setText("Telemetry is stale; no current assessment.")
        else:
            self.findings_label.setText(
                "No abnormality detected. This does not mean the vehicle is safe to drive."
            )

    def apply_palette(self, palette: ThemePalette) -> None:
        self.details_button.apply_palette(palette)


class DashboardPage(Page):
    key = "dashboard"
    title = "Dashboard"
    subtitle = "Instrument cluster and recent activity"
    navigate = Signal(str)

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._dirty = False

        self.banner = Banner(SIMULATION_NOTICE, StatusLevel.SIMULATION)
        self.banner.hide()
        self.content.addWidget(self.banner)

        top = QHBoxLayout()
        top.setSpacing(16)
        self.vehicle_card = VehicleSummary(ctx)
        self.vehicle_card.open_garage.connect(lambda: self.navigate.emit("garage"))
        top.addWidget(self.vehicle_card, 3)

        control_card = Card("Monitoring")
        self.controls = MonitoringControls(ctx)
        self.mode_pill = StatusIndicator(prefix="Source: ")
        self.connection_pill = StatusIndicator()
        self.freshness_label = label("No data yet", "muted")
        pills = QHBoxLayout()
        pills.addWidget(self.mode_pill)
        pills.addWidget(self.connection_pill)
        pills.addStretch(1)
        control_card.body.addWidget(self.controls)
        control_card.body.addLayout(pills)
        control_card.body.addWidget(self.freshness_label)
        top.addWidget(control_card, 2)
        self.content.addLayout(top)

        cluster = Card("Instrument cluster")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(12)
        system = ctx.app.settings.units.system
        coolant = SENSOR_BY_KEY["coolant_temp_c"]
        low, high = coolant.display_range(system)
        self.coolant_gauge = CircularGauge(
            "Coolant temperature", coolant.unit(system), low, high, bands=coolant_bands(system)
        )
        self.rpm_gauge = CircularGauge("Engine speed", "rpm", 0, 7000, bands=RPM_BANDS)

        speed_box = QVBoxLayout()
        speed_box.setSpacing(0)
        speed_box.addStretch(1)
        self.speed_value = label(MISSING_TEXT, "hero-value")
        self.speed_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speed_value.setAccessibleName("Vehicle speed")
        self.speed_unit = label(SENSOR_BY_KEY["speed_kph"].unit(system), "metric-unit")
        self.speed_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_caption = label("Vehicle speed", "muted")
        speed_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_box.addWidget(self.speed_value)
        speed_box.addWidget(self.speed_unit)
        speed_box.addWidget(speed_caption)
        speed_box.addStretch(1)

        side = QVBoxLayout()
        side.setSpacing(12)
        self.fuel_gauge = LinearGauge("Fuel level", "%", low_band=15.0)
        self.load_gauge = LinearGauge("Engine load", "%")
        self.voltage_card = MetricCard("Control module voltage", "V")
        side.addWidget(self.fuel_gauge)
        side.addWidget(self.load_gauge)
        side.addWidget(self.voltage_card)
        side.addStretch(1)

        grid.addWidget(self.coolant_gauge, 0, 0)
        grid.addWidget(self.rpm_gauge, 0, 1)
        grid.addLayout(speed_box, 0, 2)
        grid.addLayout(side, 0, 3)
        for column, stretch in enumerate((3, 3, 2, 3)):
            grid.setColumnStretch(column, stretch)
        cluster.body.addLayout(grid)
        self.content.addWidget(cluster)

        self.diagnostics_card = DiagnosticsSummary(ctx)
        self.diagnostics_card.open_details.connect(lambda: self.navigate.emit("diagnostics"))
        self.content.addWidget(self.diagnostics_card)

        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        self.speed_chart = ChartContainer(
            "Vehicle speed — last 2 minutes", SENSOR_BY_KEY["speed_kph"].unit(system)
        )
        self.speed_chart.add_curve("speed_kph", "Speed")
        self.coolant_chart = ChartContainer(
            "Coolant temperature — last 2 minutes", coolant.unit(system)
        )
        self.coolant_chart.add_curve("coolant_temp_c", "Coolant", "warning")
        self.alerts_card = AlertsCard()
        bottom.addWidget(self.speed_chart, 3)
        bottom.addWidget(self.coolant_chart, 3)
        bottom.addWidget(self.alerts_card, 2)
        self.content.addLayout(bottom)
        self.content.addStretch(1)

        monitoring = ctx.monitoring
        monitoring.frame_received.connect(self._on_frame)
        monitoring.state_changed.connect(self._refresh_status)
        monitoring.connection_changed.connect(self._refresh_status)
        ctx.state.active_vehicle_changed.connect(lambda _v: self._refresh_vehicle())
        ctx.state.settings_changed.connect(lambda _s: self._apply_units())
        ctx.diagnostics.alerts_raised.connect(lambda _a: self._refresh_alerts())
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._refresh_live)
        self._timer.start()
        self._apply_units()
        self._refresh_status()

    def on_shown(self) -> None:
        self._refresh_vehicle()
        self._render_values()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._refresh_vehicle()

    def _on_frame(self, frame: object) -> None:
        if isinstance(frame, TelemetryFrame):
            self._dirty = True

    def _refresh_vehicle(self) -> None:
        vehicle = self.ctx.state.active_vehicle
        self.vehicle_card.show_vehicle(vehicle, self.ctx.theme.palette)
        self._refresh_alerts()

    def _refresh_alerts(self) -> None:
        vehicle = self.ctx.state.active_vehicle
        alerts = self.ctx.telemetry.recent_alerts(vehicle_id=vehicle.id if vehicle else None)
        self.alerts_card.show_alerts(alerts)

    def _apply_units(self) -> None:
        system = self.ctx.app.settings.units.system
        coolant = SENSOR_BY_KEY["coolant_temp_c"]
        low, high = coolant.display_range(system)
        self.coolant_gauge.configure(
            unit=coolant.unit(system), minimum=low, maximum=high, bands=coolant_bands(system)
        )
        self.speed_unit.setText(SENSOR_BY_KEY["speed_kph"].unit(system))
        self.speed_chart.set_y_label(SENSOR_BY_KEY["speed_kph"].unit(system))
        self.coolant_chart.set_y_label(coolant.unit(system))
        animations = self.ctx.app.settings.appearance.animations_enabled
        for gauge in (self.coolant_gauge, self.rpm_gauge, self.fuel_gauge, self.load_gauge):
            gauge.animations_enabled = animations
        self._refresh_vehicle()
        self._render_values()

    def _refresh_status(self, *_: object) -> None:
        monitoring = self.ctx.monitoring
        self.mode_pill.set_status(*mode_status(monitoring.state, monitoring.data_source))
        self.connection_pill.set_status(*CONNECTION_TEXT[monitoring.connection])
        is_sim = monitoring.data_source is DataSource.SIMULATION
        self.banner.setVisible(is_sim)
        if monitoring.state is MonitoringState.STOPPED:
            self._render_values()

    def _refresh_live(self) -> None:
        monitoring = self.ctx.monitoring
        age = monitoring.data_age_s()
        self.freshness_label.setText(
            "Monitoring stopped"
            if not monitoring.is_active and age is not None
            else format_age(age)
        )
        if self._dirty and self.isVisible():
            self._dirty = False
            self._render_values()

    def _render_values(self) -> None:
        system = self.ctx.app.settings.units.system
        monitoring = self.ctx.monitoring
        sample = monitoring.buffer.latest if monitoring.is_active else None

        def value(key: str) -> float | None:
            raw = getattr(sample, key) if sample is not None else None
            return None if raw is None else SENSOR_BY_KEY[key].to_display(raw, system)

        self.coolant_gauge.set_value(value("coolant_temp_c"))
        self.rpm_gauge.set_value(value("rpm"))
        speed = value("speed_kph")
        self.speed_value.setText(MISSING_TEXT if speed is None else f"{speed:.0f}")
        self.fuel_gauge.set_value(value("fuel_level_pct"))
        self.load_gauge.set_value(value("engine_load_pct"))
        voltage = value("control_module_voltage_v")
        self.voltage_card.set_value(
            None if voltage is None else f"{voltage:.2f}",
            "V",
            "" if sample is not None else "Not monitoring",
        )
        if not monitoring.is_active:
            self.speed_chart.clear_data()
            self.coolant_chart.clear_data()
            return
        for chart, key in ((self.speed_chart, "speed_kph"), (self.coolant_chart, "coolant_temp_c")):
            spec = SENSOR_BY_KEY[key]
            times, values = monitoring.buffer.window(key, TREND_WINDOW_S)
            chart.set_data(key, times, [spec.to_display(v, system) for v in values])
            if times:
                chart.set_x_window(times[-1], TREND_WINDOW_S)
