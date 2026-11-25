"""Trip History: recorded trips, statistics, timelines, charts, export, deletion and replay.

Replay plays a trip's stored samples through the normal monitoring pipeline at 0.5×–4×. It never
records anything, never writes diagnostic history and never talks to an adapter. Findings shown
as "Replay analysis" are recalculated now and are kept apart from the findings recorded at the
time of the trip.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QSlider,
    QVBoxLayout,
)

from smartdrive.config.constants import DataSource, Severity
from smartdrive.core.sensors import SENSORS
from smartdrive.models.diagnostic import DiagnosticAssessment
from smartdrive.reporting.report_templates import ReportRequest, ReportType
from smartdrive.services.replay_service import PLAYBACK_SPEEDS
from smartdrive.services.report_service import CsvDataset
from smartdrive.services.trip_service import TripListItem
from smartdrive.ui.context import UiContext
from smartdrive.ui.dialogs import confirm as confirm_dialogs
from smartdrive.ui.dialogs.files import (
    CSV_FILTER,
    PDF_FILTER,
    choose_save_path,
    default_directory,
)
from smartdrive.ui.monitoring_controller import MonitoringState
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.charts import ChartContainer
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel
from smartdrive.ui.widgets.tables import (
    MISSING,
    SEVERITY_TEXT,
    fill_table,
    local_time,
    make_table,
    number,
    row_data,
    select_data,
)
from smartdrive.utils.exceptions import SmartDriveError

TRIP_COLUMNS = ("Started", "Trip", "Vehicle", "Data", "Duration", "Est. distance", "Events")
SOURCE_TEXT = {
    DataSource.SIMULATION: "Simulated",
    DataSource.LIVE: "Live vehicle",
    DataSource.REPLAY: "Replay",
}
CHART_POINTS = 1500


def duration_text(seconds: float | None) -> str:
    if seconds is None:
        return "In progress"
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def trip_name(item: TripListItem) -> str:
    session = item.session
    if session.name:
        return session.name
    if session.scenario:
        return f"Trip #{session.id} ({session.scenario.replace('_', ' ')})"
    return f"Trip #{session.id}"


def events_text(summary: dict[str, object] | None) -> str:
    if summary is None:
        return "Not summarised"
    warnings, critical = summary["warning_count"], summary["critical_count"]
    return f"{summary['diagnostic_event_count']} ({warnings} warning, {critical} critical)"


class TripHistoryPage(Page):
    key = "trips"
    title = "Trip History"
    subtitle = "Recorded trips, statistics, diagnostic timelines and replay"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._trips: list[TripListItem] = []
        self._export_job: int | None = None
        self._samples_trip: int | None = None
        self._sample_times: list[float] = []
        self._sample_values: dict[str, list[float]] = {}
        self._seeking = False

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search trips")
        self.search_edit.setAccessibleName("Search trips")
        self.search_edit.setClearButtonEnabled(True)
        self.vehicle_filter = QComboBox()
        self.vehicle_filter.setAccessibleName("Filter by vehicle")
        self.source_filter = QComboBox()
        self.source_filter.setAccessibleName("Filter by data source")
        self.source_filter.addItem("All data sources", None)
        self.source_filter.addItem("Simulated", DataSource.SIMULATION)
        self.source_filter.addItem("Live vehicle", DataSource.LIVE)
        self.severity_filter = QComboBox()
        self.severity_filter.setAccessibleName("Filter by severity")
        self.severity_filter.addItem("Any findings", None)
        self.severity_filter.addItem("With warnings or worse", Severity.WARNING)
        self.severity_filter.addItem("With critical findings", Severity.CRITICAL)
        self.date_check = QCheckBox("Dates")
        self.date_check.setToolTip("Only trips that started within the date range")
        self.from_date = QDateEdit(QDate.currentDate().addMonths(-1))
        self.to_date = QDateEdit(QDate.currentDate())
        for edit, name in ((self.from_date, "From date"), (self.to_date, "To date")):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setAccessibleName(name)
            edit.setEnabled(False)
        filters.addWidget(self.search_edit, 2)
        for widget in (
            self.vehicle_filter,
            self.source_filter,
            self.severity_filter,
            self.date_check,
            self.from_date,
            self.to_date,
        ):
            filters.addWidget(widget)
        self.content.addLayout(filters)

        list_card = Card("Trips")
        self.table = make_table(TRIP_COLUMNS, "Recorded trips", stretch=1)
        self.table.setMinimumHeight(220)
        self.list_stack = StatefulStack(self.table)
        list_card.body.addWidget(self.list_stack)
        actions = QHBoxLayout()
        self.replay_button = IconPushButton("Replay", "play", variant="primary")
        self.pdf_button = IconPushButton("Export PDF", "file")
        self.csv_button = IconPushButton("Export telemetry CSV", "file")
        self.delete_button = IconPushButton("Delete trip", "trash", variant="danger")
        for button in (self.replay_button, self.pdf_button, self.csv_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.delete_button)
        list_card.body.addLayout(actions)
        self.content.addWidget(list_card)

        self.replay_card = Card("Replay")
        replay_top = QHBoxLayout()
        self.replay_pill = StatusIndicator("No replay", StatusLevel.OFFLINE)
        self.play_button = IconPushButton("Pause", "pause")
        self.stop_button = IconPushButton("Stop replay", "stop", variant="danger")
        self.speed_combo = QComboBox()
        self.speed_combo.setAccessibleName("Playback speed")
        for speed in PLAYBACK_SPEEDS:
            self.speed_combo.addItem(f"{speed:g}×", speed)
        self.speed_combo.setCurrentIndex(PLAYBACK_SPEEDS.index(1.0))
        replay_top.addWidget(self.replay_pill)
        replay_top.addWidget(self.play_button)
        replay_top.addWidget(self.stop_button)
        replay_top.addWidget(label("Speed", "muted"))
        replay_top.addWidget(self.speed_combo)
        replay_top.addStretch(1)
        self.replay_card.body.addLayout(replay_top)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setAccessibleName("Playback position")
        self.seek_slider.setRange(0, 1000)
        self.replay_card.body.addWidget(self.seek_slider)
        replay_info = QHBoxLayout()
        self.position_label = label("0:00 / 0:00")
        self.original_time_label = label("", "muted")
        self.readout_label = label("", "muted")
        replay_info.addWidget(self.position_label)
        replay_info.addWidget(self.original_time_label)
        replay_info.addStretch(1)
        replay_info.addWidget(self.readout_label)
        self.replay_card.body.addLayout(replay_info)
        analysis_row = QHBoxLayout()
        recalculated = QVBoxLayout()
        recalculated.addWidget(
            label("Replay analysis (recalculated now, not saved)", "section-title")
        )
        self.replay_findings = QListWidget()
        self.replay_findings.setAccessibleName("Replay analysis findings")
        self.replay_findings.setMaximumHeight(120)
        recalculated.addWidget(self.replay_findings)
        analysis_row.addLayout(recalculated, 1)
        self.replay_card.body.addLayout(analysis_row)
        self.replay_card.body.addWidget(
            label(
                "Gauges, Live Monitoring and AI Diagnostics follow the replay and label it as "
                "recorded data. Explanations for the recalculated analysis are on AI Diagnostics.",
                "muted",
                wrap=True,
            )
        )
        self.content.addWidget(self.replay_card)

        detail_row = QHBoxLayout()
        detail_row.setSpacing(16)
        summary_card = Card("Trip summary")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.facts: dict[str, QLabel] = {}
        for key, title in (
            ("name", "Trip"),
            ("vehicle", "Vehicle"),
            ("source", "Data source"),
            ("status", "Recording status"),
            ("times", "Started / ended"),
            ("duration", "Recorded duration"),
            ("samples", "Samples / completeness"),
            ("speed", "Average / maximum speed"),
            ("rpm", "Average / maximum engine speed"),
            ("coolant", "Coolant temperature range"),
            ("distance", "Estimated distance"),
            ("events", "Diagnostic events"),
            ("codes", "Stored codes in trip scans"),
            ("models", "Model versions"),
        ):
            value = label(MISSING, wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.facts[key] = value
            form.addRow(label(title, "muted"), value)
        summary_card.body.addLayout(form)
        detail_row.addWidget(summary_card, 2)

        timeline_card = Card("Diagnostic timeline (recorded)")
        self.timeline = QListWidget()
        self.timeline.setAccessibleName("Diagnostic timeline")
        self.timeline.setMinimumHeight(200)
        timeline_card.body.addWidget(self.timeline)
        detail_row.addWidget(timeline_card, 3)
        self.content.addLayout(detail_row)

        chart_card = Card("Recorded telemetry")
        chart_top = QHBoxLayout()
        self.chart_sensor = QComboBox()
        self.chart_sensor.setAccessibleName("Chart sensor")
        for spec in SENSORS:
            self.chart_sensor.addItem(spec.label, spec.key)
        chart_top.addWidget(self.chart_sensor)
        chart_top.addStretch(1)
        chart_card.body.addLayout(chart_top)
        self.chart = ChartContainer("Selected trip", height=200)
        self.chart.add_curve("trip", "Reading")
        self.health_chart = ChartContainer("Experimental health score", height=150)
        self.health_chart.add_curve("health", "Health score", "normal")
        chart_card.body.addWidget(self.chart)
        chart_card.body.addWidget(self.health_chart)
        self.content.addWidget(chart_card)

        self.search_edit.textChanged.connect(self._on_filters_changed)
        for combo in (self.vehicle_filter, self.source_filter, self.severity_filter):
            combo.currentIndexChanged.connect(self._on_filters_changed)
        self.date_check.toggled.connect(self._on_dates_toggled)
        self.from_date.dateChanged.connect(self._on_filters_changed)
        self.to_date.dateChanged.connect(self._on_filters_changed)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.chart_sensor.currentIndexChanged.connect(self._draw_chart)
        self.replay_button.clicked.connect(self.replay_selected)
        self.pdf_button.clicked.connect(self.export_pdf)
        self.csv_button.clicked.connect(self.export_csv)
        self.delete_button.clicked.connect(self.delete_selected)
        self.play_button.clicked.connect(self.toggle_play)
        self.stop_button.clicked.connect(self.stop_replay)
        self.speed_combo.currentIndexChanged.connect(self._on_speed)
        self.seek_slider.sliderPressed.connect(self._on_seek_started)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        ctx.trips.trips_changed.connect(self.reload)
        ctx.trips.replay_loading.connect(self._refresh_replay)
        ctx.trips.error.connect(self._on_trip_error)
        ctx.state.vehicles_changed.connect(self._load_vehicles)
        ctx.monitoring.state_changed.connect(self._refresh_replay)
        ctx.monitoring.replay_changed.connect(self._refresh_replay)
        ctx.monitoring.frame_received.connect(self._on_frame)
        ctx.diagnostics.assessment_changed.connect(self._on_assessment)
        ctx.tasks.finished.connect(self._on_job_finished)
        ctx.tasks.failed.connect(self._on_job_failed)
        self._load_vehicles()
        self.reload()
        self._refresh_replay()

    # -- list ---------------------------------------------------------------------------------

    def on_shown(self) -> None:
        self.reload()

    def _load_vehicles(self) -> None:
        current = self.vehicle_filter.currentData()
        self.vehicle_filter.blockSignals(True)
        self.vehicle_filter.clear()
        self.vehicle_filter.addItem("All vehicles", None)
        try:
            vehicles = self.ctx.vehicles.list_vehicles()
        except SmartDriveError:
            vehicles = []
        for vehicle in vehicles:
            self.vehicle_filter.addItem(vehicle.name, vehicle.id)
        index = self.vehicle_filter.findData(current)
        self.vehicle_filter.setCurrentIndex(max(0, index))
        self.vehicle_filter.blockSignals(False)
        self.reload()

    def _on_dates_toggled(self, checked: bool) -> None:
        self.from_date.setEnabled(checked)
        self.to_date.setEnabled(checked)
        self.reload()

    def _on_filters_changed(self, *_: object) -> None:
        self.reload()

    def _date_range(self) -> tuple[datetime | None, datetime | None]:
        if not self.date_check.isChecked():
            return None, None
        start_qdate, end_qdate = self.from_date.date(), self.to_date.date()
        start_day = date(start_qdate.year(), start_qdate.month(), start_qdate.day())
        end_day = date(end_qdate.year(), end_qdate.month(), end_qdate.day())
        start = datetime.combine(start_day, time.min).astimezone().astimezone(UTC)
        end = datetime.combine(end_day, time.max).astimezone().astimezone(UTC)
        return start, end

    def reload(self) -> None:
        start, end = self._date_range()
        try:
            self._trips = self.ctx.trips.trips.list_trips(
                vehicle_id=self.vehicle_filter.currentData(),
                data_source=combo_enum(self.source_filter, DataSource),
                start=start,
                end=end,
                min_severity=combo_enum(self.severity_filter, Severity),
                search=self.search_edit.text(),
            )
        except SmartDriveError as exc:
            self.list_stack.show_error("Trips could not be loaded", exc.user_message)
            return
        if not self._trips:
            self.list_stack.show_empty(
                "No trips",
                "Record a session from Live Monitoring or the Simulation Lab (tick Record "
                "session), or relax the filters.",
            )
            self._show_selected()
            return
        rows = []
        for item in self._trips:
            summary = item.summary
            distance = summary.get("distance_km") if summary else None
            rows.append(
                (
                    local_time(item.session.started_at),
                    trip_name(item),
                    item.vehicle_name,
                    SOURCE_TEXT.get(item.session.data_source, item.session.data_source.value),
                    duration_text(item.duration_s),
                    MISSING if distance is None else f"≈ {distance:.2f} km",
                    events_text(summary),
                )
            )
        fill_table(self.table, rows, [t.session.id for t in self._trips])
        self.list_stack.show_content()
        if self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._show_selected()

    def selected_trip(self) -> TripListItem | None:
        session_id = row_data(self.table) if self._trips else None
        return next((t for t in self._trips if t.session.id == session_id), None)

    def select_trip(self, session_id: int) -> bool:
        return select_data(self.table, session_id)

    # -- details ------------------------------------------------------------------------------

    def _show_selected(self) -> None:
        item = self.selected_trip()
        self._refresh_buttons()
        self.timeline.clear()
        if item is None:
            for value in self.facts.values():
                value.setText(MISSING)
            self.chart.clear_data()
            self.health_chart.clear_data()
            self._samples_trip = None
            return
        session = item.session
        summary = item.summary or {}
        self.facts["name"].setText(trip_name(item))
        self.facts["vehicle"].setText(item.vehicle_name)
        provenance = SOURCE_TEXT.get(session.data_source, session.data_source.value)
        if session.scenario == "mock-obd-adapter":
            provenance += " (mock OBD-II adapter)"
        elif session.data_source is DataSource.SIMULATION and session.scenario:
            provenance += f" — scenario {session.scenario.replace('_', ' ')}"
        self.facts["source"].setText(provenance)
        self.facts["status"].setText(session.status.value.title())
        self.facts["times"].setText(
            f"{local_time(session.started_at, seconds=True)} / "
            f"{local_time(session.ended_at, seconds=True)}"
        )
        self.facts["duration"].setText(duration_text(item.duration_s))
        completeness = summary.get("data_completeness")
        self.facts["samples"].setText(
            f"{item.sample_count} · "
            + (MISSING if completeness is None else f"{completeness:.0%} of core sensors")
        )
        self.facts["speed"].setText(
            f"{number(summary.get('avg_speed_kph'))} / {number(summary.get('max_speed_kph'))} km/h"
        )
        self.facts["rpm"].setText(
            f"{number(summary.get('avg_rpm'), 0)} / {number(summary.get('max_rpm'), 0)} rpm"
        )
        self.facts["coolant"].setText(
            f"{number(summary.get('min_coolant_c'))} – {number(summary.get('max_coolant_c'))} °C"
        )
        distance = summary.get("distance_km")
        coverage = summary.get("distance_coverage")
        self.facts["distance"].setText(
            "Not available (no usable speed readings)"
            if distance is None
            else f"≈ {distance:.2f} km — estimated from speed over time; "
            f"{(coverage or 0):.0%} of the recording contributed"
        )
        self.facts["events"].setText(events_text(item.summary))
        dtc = summary.get("dtc_count")
        self.facts["codes"].setText("No scan during this trip" if dtc is None else str(dtc))
        versions = summary.get("model_versions") or {}
        self.facts["models"].setText(
            ", ".join(f"{k} {v}" for k, v in versions.items()) if versions else MISSING
        )
        try:
            events = self.ctx.trips.trips.events(session.id)
        except SmartDriveError:
            events = []
        if not events:
            self.timeline.addItem("No diagnostic events were recorded during this trip.")
        for event in events:
            severity = SEVERITY_TEXT.get(event.severity, event.severity.value)
            detail = f" — {event.detail}" if event.detail else ""
            self.timeline.addItem(
                f"{local_time(event.occurred_at, seconds=True)}  {severity}  "
                f"{event.title} [{event.source or 'event'}]{detail}"
            )
        self._load_series(session.id)

    def _load_series(self, session_id: int) -> None:
        if self._samples_trip == session_id:
            self._draw_chart()
            return
        try:
            samples = self.ctx.telemetry.load_samples(session_id)
            health = self.ctx.trips.trips.health_history(session_id)
        except SmartDriveError:
            samples, health = [], []
        self._samples_trip = session_id
        step = max(1, len(samples) // CHART_POINTS)
        picked = samples[::step]
        start = samples[0].timestamp if samples else None
        self._sample_times = (
            [(s.timestamp - start).total_seconds() for s in picked] if start else []
        )
        self._sample_values = {
            spec.key: [
                math.nan if getattr(s, spec.key) is None else float(getattr(s, spec.key))
                for s in picked
            ]
            for spec in SENSORS
        }
        self.health_chart.clear_data()
        if start is not None and health:
            times = [(t - start).total_seconds() for t, _ in health]
            values = [math.nan if v is None else float(v) for _, v in health]
            self.health_chart.set_data("health", times, values)
        self._draw_chart()

    def _draw_chart(self, *_: object) -> None:
        key = self.chart_sensor.currentData()
        if not self._sample_times or key not in self._sample_values:
            self.chart.clear_data()
            return
        spec = next(s for s in SENSORS if s.key == key)
        system = self.ctx.app.settings.units.system
        values = [
            v if math.isnan(v) else spec.to_display(v, system) for v in self._sample_values[key]
        ]
        self.chart.set_title(f"{spec.label} ({spec.unit(system)}) — seconds since start")
        self.chart.set_data("trip", self._sample_times, values)

    # -- actions ------------------------------------------------------------------------------

    def replay_selected(self) -> None:
        item = self.selected_trip()
        if item is None:
            return
        if item.sample_count == 0:
            self.ctx.notifier.notify("This trip has no recorded telemetry to replay.")
            return
        self.ctx.trips.start_replay(item.session.id, speed=float(self.speed_combo.currentData()))
        self._refresh_replay()

    def toggle_play(self) -> None:
        monitoring = self.ctx.monitoring
        if monitoring.data_source is not DataSource.REPLAY:
            return
        if monitoring.state is MonitoringState.RUNNING:
            monitoring.pause()
        elif monitoring.replay_finished:
            monitoring.seek_replay(0.0)
            monitoring.resume()
        else:
            monitoring.resume()

    def stop_replay(self) -> None:
        if self.ctx.monitoring.data_source is DataSource.REPLAY:
            self.ctx.monitoring.stop()

    def _on_speed(self, *_: object) -> None:
        if self.ctx.monitoring.data_source is DataSource.REPLAY:
            self.ctx.monitoring.set_replay_speed(float(self.speed_combo.currentData()))

    def _on_seek_started(self) -> None:
        self._seeking = True

    def _on_seek_released(self) -> None:
        self._seeking = False
        monitoring = self.ctx.monitoring
        if monitoring.data_source is not DataSource.REPLAY or monitoring.replay_duration_s <= 0:
            return
        target = self.seek_slider.value() / 1000.0 * monitoring.replay_duration_s
        monitoring.seek_replay(target)
        self.replay_findings.clear()

    def export_pdf(self) -> None:
        item = self.selected_trip()
        if item is None or self._export_job is not None:
            return
        settings = self.ctx.app.settings
        path = choose_save_path(
            self,
            "Export trip report",
            default_directory(settings),
            f"smartdrive-trip-{item.session.id}.pdf",
            PDF_FILTER,
        )
        if path is None:
            return
        request = ReportRequest(
            ReportType.TRIP,
            vehicle_id=item.session.vehicle_id,
            session_id=item.session.id,
            include_identifiers=settings.reports.include_identifiers,
            include_notes=settings.reports.include_notes,
        )
        reports = self.ctx.reports
        self._export_job = self.ctx.tasks.submit(
            "Trip report", lambda: reports.generate_pdf(request, path, overwrite=True)
        )
        self._refresh_buttons()

    def export_csv(self) -> None:
        item = self.selected_trip()
        if item is None or self._export_job is not None:
            return
        path = choose_save_path(
            self,
            "Export trip telemetry",
            default_directory(self.ctx.app.settings),
            f"smartdrive-trip-{item.session.id}-telemetry.csv",
            CSV_FILTER,
        )
        if path is None:
            return
        reports = self.ctx.reports
        session_id, vehicle_id = item.session.id, item.session.vehicle_id
        self._export_job = self.ctx.tasks.submit(
            "Trip telemetry export",
            lambda: reports.export_csv(
                CsvDataset.TELEMETRY,
                path,
                vehicle_id=vehicle_id,
                session_id=session_id,
                overwrite=True,
            ),
        )
        self._refresh_buttons()

    def delete_selected(self) -> None:
        item = self.selected_trip()
        if item is None:
            return
        if self.ctx.monitoring.session_id == item.session.id:
            self.ctx.notifier.notify("Stop recording before deleting this trip.")
            return
        if self.ctx.monitoring.replay_session_id == item.session.id:
            self.ctx.notifier.notify("Stop the replay before deleting this trip.")
            return
        if not confirm_dialogs.confirm(
            self,
            "Delete trip?",
            f"Delete “{trip_name(item)}” and its {item.sample_count} telemetry readings? "
            "Diagnostic history, alerts, trouble codes and maintenance records are kept.",
            confirm_text="Delete trip",
            destructive=True,
            palette=self.ctx.theme.palette,
        ):
            return
        try:
            self.ctx.trips.trips.delete_trip(item.session.id)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self._samples_trip = None
        self.ctx.notifier.notify("Trip deleted.")
        self.reload()

    # -- replay state -------------------------------------------------------------------------

    def _refresh_replay(self, *_: object) -> None:
        monitoring = self.ctx.monitoring
        replaying = monitoring.data_source is DataSource.REPLAY
        loading = self.ctx.trips.replay_loading_active
        if loading:
            self.replay_pill.set_status("Loading trip…", StatusLevel.INFO)
        elif replaying:
            original = monitoring.replay_original_source
            origin = SOURCE_TEXT.get(original, "recorded") if original else "recorded"
            state = (
                "finished"
                if monitoring.replay_finished
                else "paused"
                if monitoring.state is MonitoringState.PAUSED
                else "playing"
            )
            self.replay_pill.set_status(
                f"Replaying trip #{monitoring.replay_session_id} ({origin.lower()} data) — {state}",
                StatusLevel.INFO,
            )
        else:
            self.replay_pill.set_status("No replay", StatusLevel.OFFLINE)
            self.position_label.setText("0:00 / 0:00")
            self.original_time_label.setText("")
            self.readout_label.setText("")
            self.seek_slider.setValue(0)
        paused = monitoring.state is MonitoringState.PAUSED or monitoring.replay_finished
        self.play_button.setText("Play" if paused else "Pause")
        self.play_button.set_icon_name("play" if paused else "pause")
        for widget in (self.play_button, self.stop_button, self.seek_slider, self.speed_combo):
            widget.setEnabled(replaying or widget is self.speed_combo)
        index = self.speed_combo.findData(monitoring.replay_speed if replaying else None)
        if replaying and index >= 0 and index != self.speed_combo.currentIndex():
            self.speed_combo.blockSignals(True)
            self.speed_combo.setCurrentIndex(index)
            self.speed_combo.blockSignals(False)
        if not replaying:
            self.replay_findings.clear()
        self._refresh_buttons()

    def _on_frame(self, frame: object) -> None:
        monitoring = self.ctx.monitoring
        if monitoring.data_source is not DataSource.REPLAY:
            return
        position = monitoring.replay_position_s
        duration = monitoring.replay_duration_s
        self.position_label.setText(f"{duration_text(position)} / {duration_text(duration)}")
        if not self._seeking and duration > 0:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(round(1000 * min(1.0, position / duration)))
            self.seek_slider.blockSignals(False)
        sample = getattr(frame, "sample", None)
        if sample is not None:
            self.original_time_label.setText(
                f"Recorded at {local_time(sample.timestamp, seconds=True)}"
            )
            parts = []
            for key, unit in (("speed_kph", "km/h"), ("rpm", "rpm"), ("coolant_temp_c", "°C")):
                value = getattr(sample, key)
                parts.append(MISSING if value is None else f"{value:.0f} {unit}")
            self.readout_label.setText(" · ".join(parts))

    def _on_assessment(self, assessment: object) -> None:
        if self.ctx.monitoring.data_source is not DataSource.REPLAY:
            return
        self.replay_findings.clear()
        if not isinstance(assessment, DiagnosticAssessment):
            return
        if not assessment.findings:
            self.replay_findings.addItem(
                f"{assessment.status.value.replace('_', ' ').capitalize()} — no findings at "
                "this point of the replay."
            )
        for finding in assessment.findings:
            severity = SEVERITY_TEXT.get(finding.severity, finding.severity.value)
            self.replay_findings.addItem(f"{severity}  {finding.title} ({finding.source.value})")

    def _on_trip_error(self, message: str) -> None:
        self.ctx.notifier.notify(message, StatusLevel.WARNING)
        self._refresh_replay()

    # -- jobs ---------------------------------------------------------------------------------

    def _on_job_finished(self, job_id: int, result: object) -> None:
        if job_id != self._export_job:
            return
        self._export_job = None
        self._refresh_buttons()
        name = getattr(getattr(result, "path", None), "name", "the file")
        self.ctx.notifier.notify(f"Saved {name}.", StatusLevel.NORMAL)

    def _on_job_failed(self, job_id: int, message: str) -> None:
        if job_id != self._export_job:
            return
        self._export_job = None
        self._refresh_buttons()
        self.ctx.notifier.notify(f"Export failed: {message}", StatusLevel.CRITICAL)

    def _refresh_buttons(self, *_: object) -> None:
        item = self.selected_trip()
        monitoring = self.ctx.monitoring
        has = item is not None
        idle = not monitoring.is_active and not self.ctx.trips.replay_loading_active
        self.replay_button.setEnabled(has and idle)
        self.replay_button.setToolTip(
            "Replay this trip" if idle else "Stop monitoring or the current replay first"
        )
        exporting = self._export_job is not None
        self.pdf_button.setEnabled(has and not exporting)
        self.csv_button.setEnabled(has and not exporting)
        self.delete_button.setEnabled(has)

    def apply_palette(self, palette: ThemePalette) -> None:
        self.replay_pill.apply_palette(palette)
