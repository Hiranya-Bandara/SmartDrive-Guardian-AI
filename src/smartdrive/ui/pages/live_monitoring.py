"""Live monitoring: per-sensor charts, statistics, sensor selection and refresh/time controls."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from smartdrive.config.constants import DataSource
from smartdrive.core.monitoring import SensorStatistics
from smartdrive.core.sensors import SENSORS, SensorSpec
from smartdrive.core.units import MISSING_TEXT
from smartdrive.services.data_source import TelemetryFrame
from smartdrive.ui.context import UiContext
from smartdrive.ui.monitoring_controller import ConnectionState
from smartdrive.ui.pages.base import Page
from smartdrive.ui.pages.dashboard import SIMULATION_NOTICE
from smartdrive.ui.widgets.base import IconPushButton, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.charts import ChartContainer
from smartdrive.ui.widgets.monitoring_controls import MonitoringControls
from smartdrive.ui.widgets.notifications import Banner
from smartdrive.ui.widgets.status import StatusLevel

REFRESH_OPTIONS_MS = (100, 250, 500, 1000, 2000, 5000)
TIME_RANGE_OPTIONS_S = (30, 60, 120, 300, 600, 1800, 3600)
DEFAULT_SELECTION = ("coolant_temp_c", "rpm", "speed_kph", "engine_load_pct")
CHART_REFRESH_MS = 200
STAT_COLUMNS = ("Sensor", "Current", "Minimum", "Maximum", "Average", "Missing", "Status")


def describe_status(
    spec: SensorSpec,
    stats: SensorStatistics,
    frame: TelemetryFrame | None,
    connection: ConnectionState,
    *,
    active: bool = True,
) -> str:
    if frame is None:
        return "No data"
    if not active:
        return "Stopped"
    if connection is ConnectionState.NO_RESPONSE:
        return "No response"
    if connection is ConnectionState.STALE:
        return "Stale"
    if spec.key in frame.rejected:
        return "Rejected (implausible)"
    if stats.current is None:
        return "Not supported" if stats.valid_count == 0 else "Missing"
    return "OK"


def _time_label(seconds: int) -> str:
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min"


class LiveMonitoringPage(Page):
    key = "monitoring"
    title = "Live Monitoring"
    subtitle = "Real-time telemetry with bounded history"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._dirty = False

        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        self.controls = MonitoringControls(ctx)
        toolbar.addWidget(self.controls, 1)
        toolbar.addWidget(label("Refresh", "muted"))
        self.refresh_combo = QComboBox()
        self.refresh_combo.setAccessibleName("Refresh interval")
        for ms in REFRESH_OPTIONS_MS:
            self.refresh_combo.addItem(f"{ms} ms" if ms < 1000 else f"{ms // 1000} s", ms)
        toolbar.addWidget(self.refresh_combo)
        toolbar.addWidget(label("Time range", "muted"))
        self.range_combo = QComboBox()
        self.range_combo.setAccessibleName("Chart time range")
        toolbar.addWidget(self.range_combo)
        self.content.addLayout(toolbar)

        self.banner = Banner(SIMULATION_NOTICE, StatusLevel.SIMULATION)
        self.banner.hide()
        self.content.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(16)
        sensors_card = Card("Sensors")
        sensors_card.setFixedWidth(250)
        self.sensor_list = QListWidget()
        self.sensor_list.setAccessibleName("Sensor selection")
        self.sensor_list.setMinimumHeight(30 * len(SENSORS) + 12)
        self.sensor_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for spec in SENSORS:
            item = QListWidgetItem(spec.label)
            item.setData(Qt.ItemDataRole.UserRole, spec.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if spec.key in DEFAULT_SELECTION else Qt.CheckState.Unchecked
            )
            self.sensor_list.addItem(item)
        all_button = IconPushButton("All", variant="ghost")
        none_button = IconPushButton("None", variant="ghost")
        all_button.clicked.connect(lambda: self._set_all(True))
        none_button.clicked.connect(lambda: self._set_all(False))
        select_row = QHBoxLayout()
        select_row.addWidget(all_button)
        select_row.addWidget(none_button)
        select_row.addStretch(1)
        sensors_card.body.addWidget(self.sensor_list, 1)
        sensors_card.body.addLayout(select_row)
        body.addWidget(sensors_card, 0, Qt.AlignmentFlag.AlignTop)

        self.charts_widget = QWidget()
        self.charts_grid = QGridLayout(self.charts_widget)
        self.charts_grid.setContentsMargins(0, 0, 0, 0)
        self.charts_grid.setSpacing(16)
        self.charts: dict[str, ChartContainer] = {}
        system = ctx.app.settings.units.system
        for spec in SENSORS:
            chart = ChartContainer(
                spec.label, spec.unit(system), height=170, parent=self.charts_widget
            )
            chart.add_curve(spec.key, spec.label)
            self.charts[spec.key] = chart
        self.empty_selection = label("Select at least one sensor to display its chart.", "muted")
        self.empty_selection.setParent(self.charts_widget)
        body.addWidget(self.charts_widget, 1)
        self.content.addLayout(body)

        stats_card = Card("Statistics for the selected time range")
        self.table = QTableWidget(len(SENSORS), len(STAT_COLUMNS))
        self.table.setHorizontalHeaderLabels(STAT_COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setAccessibleName("Sensor statistics")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(STAT_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(36 * len(SENSORS) + 40)
        stats_card.body.addWidget(self.table)
        self.content.addWidget(stats_card)

        self.sensor_list.itemChanged.connect(lambda _i: self._layout_charts())
        self.refresh_combo.currentIndexChanged.connect(self._on_refresh_changed)
        self.range_combo.currentIndexChanged.connect(lambda _i: self._mark_dirty())
        ctx.monitoring.frame_received.connect(self._mark_dirty)
        ctx.monitoring.state_changed.connect(self._on_state_changed)
        ctx.monitoring.connection_changed.connect(self._mark_dirty)
        ctx.state.settings_changed.connect(self._apply_settings)
        self._timer = QTimer(self)
        self._timer.setInterval(CHART_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._apply_settings()
        self._layout_charts()

    # -- selection and layout -----------------------------------------------------------------

    def selected_keys(self) -> list[str]:
        keys: list[str] = []
        for row in range(self.sensor_list.count()):
            item = self.sensor_list.item(row)
            if item.checkState() is Qt.CheckState.Checked:
                keys.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return keys

    def set_selected(self, keys: list[str]) -> None:
        self.sensor_list.blockSignals(True)
        for row in range(self.sensor_list.count()):
            item = self.sensor_list.item(row)
            checked = item.data(Qt.ItemDataRole.UserRole) in keys
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.sensor_list.blockSignals(False)
        self._layout_charts()

    def _set_all(self, checked: bool) -> None:
        self.set_selected([s.key for s in SENSORS] if checked else [])

    def _layout_charts(self) -> None:
        while self.charts_grid.count():
            self.charts_grid.takeAt(0)
        for chart in self.charts.values():
            chart.hide()
        self.empty_selection.hide()
        keys = self.selected_keys()
        if not keys:
            self.charts_grid.addWidget(self.empty_selection, 0, 0)
            self.empty_selection.show()
        for index, key in enumerate(keys):
            chart = self.charts[key]
            self.charts_grid.addWidget(chart, index // 2, index % 2)
            chart.show()
        self._mark_dirty()

    # -- settings -----------------------------------------------------------------------------

    def _apply_settings(self, *_args: object) -> None:
        settings = self.ctx.app.settings
        self.ctx.monitoring.resize_history()
        self.refresh_combo.blockSignals(True)
        current_ms = settings.monitoring.refresh_interval_ms
        index = self.refresh_combo.findData(current_ms)
        if index < 0:
            self.refresh_combo.addItem(f"{current_ms} ms", current_ms)
            index = self.refresh_combo.count() - 1
        self.refresh_combo.setCurrentIndex(index)
        self.refresh_combo.blockSignals(False)

        history = settings.monitoring.chart_history_seconds
        previous = self.range_combo.currentData()
        self.range_combo.blockSignals(True)
        self.range_combo.clear()
        for seconds in TIME_RANGE_OPTIONS_S:
            if seconds <= history:
                self.range_combo.addItem(_time_label(seconds), seconds)
        if self.range_combo.findData(history) < 0:
            self.range_combo.addItem(f"{_time_label(history)} (all history)", history)
        restore = self.range_combo.findData(previous if previous is not None else 120)
        self.range_combo.setCurrentIndex(restore if restore >= 0 else self.range_combo.count() - 1)
        self.range_combo.blockSignals(False)

        system = settings.units.system
        for spec in SENSORS:
            self.charts[spec.key].set_y_label(spec.unit(system))
        self._mark_dirty()

    def _on_refresh_changed(self, _index: int) -> None:
        interval = self.refresh_combo.currentData()
        if isinstance(interval, int):
            self.ctx.monitoring.set_interval(interval)
            self.ctx.state.save_settings()

    @property
    def time_range_s(self) -> float:
        data = self.range_combo.currentData()
        return float(data) if data is not None else 120.0

    # -- rendering ----------------------------------------------------------------------------

    def _on_state_changed(self, _state: object) -> None:
        self.banner.setVisible(self.ctx.monitoring.data_source is DataSource.SIMULATION)
        self._mark_dirty()

    def _mark_dirty(self, *_args: object) -> None:
        self._dirty = True

    def _refresh(self) -> None:
        if not self._dirty or not self.isVisible():
            return
        self._dirty = False
        self.render_now()

    def render_now(self) -> None:
        monitoring = self.ctx.monitoring
        system = self.ctx.app.settings.units.system
        window = self.time_range_s
        frame = monitoring.last_frame
        active = monitoring.is_active
        selected = set(self.selected_keys())
        for row, spec in enumerate(SENSORS):
            stats = monitoring.buffer.statistics(spec.key, window)
            if frame is None:
                stats = SensorStatistics(None, None, None, None, 0, 0)
            elif not active:
                stats = replace(stats, current=None)
            cells = (
                spec.label,
                spec.format(stats.current, system),
                spec.format(stats.minimum, system),
                spec.format(stats.maximum, system),
                spec.format(stats.average, system),
                str(stats.missing_count) if frame is not None else MISSING_TEXT,
                describe_status(spec, stats, frame, monitoring.connection, active=active),
            )
            for column, text in enumerate(cells):
                item = self.table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, column, item)
                item.setText(text)
            if spec.key not in selected:
                continue
            chart = self.charts[spec.key]
            if frame is None:
                chart.clear_data()
                continue
            times, values = monitoring.buffer.window(spec.key, window)
            chart.set_data(spec.key, times, [spec.to_display(v, system) for v in values])
            if times:
                chart.set_x_window(times[-1], window)
