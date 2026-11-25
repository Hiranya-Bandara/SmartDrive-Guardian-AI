"""Reports Centre: PDF reports and CSV exports, generated on the background job thread.

A report is generated only from stored records (and, for the AI assessment, the latest live
analysis if there is one). Generation never reports success unless the file was written; a
failure is shown with its reason and recorded in the export history.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
)

from smartdrive.config.constants import NotificationCategory, NotificationSeverity
from smartdrive.reporting.report_templates import (
    DEFAULT_SECTIONS,
    SECTIONS,
    ReportRequest,
    ReportType,
)
from smartdrive.services.report_service import CsvDataset, ExportHistoryItem, ExportResult
from smartdrive.ui.context import UiContext
from smartdrive.ui.dialogs.files import (
    CSV_FILTER,
    PDF_FILTER,
    choose_directory,
    choose_save_path,
    default_directory,
    open_path,
)
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel
from smartdrive.ui.widgets.tables import fill_table, local_time, make_table, row_data
from smartdrive.utils.exceptions import SmartDriveError

HISTORY_COLUMNS = ("Created", "Report", "Format", "File", "Result")


def _qdate_to_date(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def report_label(kind: str) -> str:
    if kind.startswith("csv:"):
        try:
            return f"CSV: {CsvDataset(kind[4:]).label}"
        except ValueError:
            return kind
    try:
        return ReportType(kind).label
    except ValueError:
        return kind


class ReportsPage(Page):
    key = "reports"
    title = "Reports"
    subtitle = "PDF reports and CSV exports from your stored data"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._job: int | None = None
        self._job_kind = ""
        self.last_result: ExportResult | None = None
        self._history: list[ExportHistoryItem] = []

        top = QHBoxLayout()
        top.setSpacing(16)
        options = Card("Report")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.type_combo = QComboBox()
        self.type_combo.setAccessibleName("Report type")
        for kind in ReportType:
            self.type_combo.addItem(kind.label, kind)
        self.vehicle_combo = QComboBox()
        self.vehicle_combo.setAccessibleName("Vehicle")
        self.trip_combo = QComboBox()
        self.trip_combo.setAccessibleName("Trip")
        dates = QHBoxLayout()
        self.date_check = QCheckBox("Limit to dates")
        self.from_date = QDateEdit(QDate.currentDate().addMonths(-3))
        self.to_date = QDateEdit(QDate.currentDate())
        for edit, name in ((self.from_date, "From date"), (self.to_date, "To date")):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setAccessibleName(name)
            edit.setEnabled(False)
        dates.addWidget(self.date_check)
        dates.addWidget(self.from_date)
        dates.addWidget(self.to_date)
        dates.addStretch(1)
        form.addRow("Type", self.type_combo)
        form.addRow("Vehicle", self.vehicle_combo)
        form.addRow("Trip", self.trip_combo)
        form.addRow("Period", dates)
        options.body.addLayout(form)
        options.body.addWidget(label("Sections", "section-title"))
        sections = QGridLayout()
        self.section_checks: dict[str, QCheckBox] = {}
        for index, (key, title) in enumerate(SECTIONS.items()):
            check = QCheckBox(title)
            self.section_checks[key] = check
            sections.addWidget(check, index // 3, index % 3)
        options.body.addLayout(sections)
        options.body.addWidget(label("Privacy", "section-title"))
        settings = ctx.app.settings.reports
        self.identifiers_check = QCheckBox("Include registration number and VIN")
        self.identifiers_check.setChecked(settings.include_identifiers)
        self.notes_check = QCheckBox("Include the vehicle's notes from the garage")
        self.notes_check.setChecked(settings.include_notes)
        options.body.addWidget(self.identifiers_check)
        options.body.addWidget(self.notes_check)
        top.addWidget(options, 3)

        output = Card("Output")
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(default_directory(ctx.app.settings)))
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setAccessibleName("Default output folder")
        self.folder_button = IconPushButton("Change…", "folder")
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.folder_button)
        output.body.addWidget(label("Default folder", "muted"))
        output.body.addLayout(folder_row)
        self.summary_label = label("", wrap=True)
        output.body.addWidget(self.summary_label)
        self.pdf_button = IconPushButton("Generate PDF…", "file", variant="primary")
        output.body.addWidget(self.pdf_button)
        csv_row = QHBoxLayout()
        self.csv_combo = QComboBox()
        self.csv_combo.setAccessibleName("CSV dataset")
        for dataset in CsvDataset:
            self.csv_combo.addItem(dataset.label, dataset)
        self.csv_button = IconPushButton("Export CSV…", "file")
        csv_row.addWidget(self.csv_combo, 1)
        csv_row.addWidget(self.csv_button)
        output.body.addLayout(csv_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setAccessibleName("Generation progress")
        output.body.addWidget(self.progress)
        self.result_pill = StatusIndicator("Nothing generated yet", StatusLevel.OFFLINE)
        output.body.addWidget(self.result_pill)
        self.result_text = label("", "muted", wrap=True)
        output.body.addWidget(self.result_text)
        open_row = QHBoxLayout()
        self.open_button = IconPushButton("Open file", "file")
        self.open_folder_button = IconPushButton("Open folder", "folder")
        open_row.addWidget(self.open_button)
        open_row.addWidget(self.open_folder_button)
        open_row.addStretch(1)
        output.body.addLayout(open_row)
        output.body.addStretch(1)
        top.addWidget(output, 2)
        self.content.addLayout(top)

        history_card = Card("Export history")
        self.history_table = make_table(HISTORY_COLUMNS, "Export history", stretch=3)
        self.history_table.setMinimumHeight(180)
        self.history_stack = StatefulStack(self.history_table)
        history_card.body.addWidget(self.history_stack)
        self.content.addWidget(history_card)

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.vehicle_combo.currentIndexChanged.connect(self._on_vehicle_selected)
        self.trip_combo.currentIndexChanged.connect(self._update_summary)
        self.date_check.toggled.connect(self._on_dates_toggled)
        for check in self.section_checks.values():
            check.toggled.connect(self._update_summary)
        self.folder_button.clicked.connect(self.choose_folder)
        self.pdf_button.clicked.connect(self.generate_pdf)
        self.csv_button.clicked.connect(self.export_csv)
        self.csv_combo.currentIndexChanged.connect(self._update_summary)
        self.open_button.clicked.connect(self.open_result)
        self.open_folder_button.clicked.connect(self.open_folder)
        self.history_table.doubleClicked.connect(self._open_history)
        ctx.state.vehicles_changed.connect(self._load_vehicles)
        ctx.trips.trips_changed.connect(self._load_trips)
        ctx.tasks.finished.connect(self._on_job_finished)
        ctx.tasks.failed.connect(self._on_job_failed)
        self._load_vehicles()
        self._on_type_changed()
        self._load_history()
        self._refresh_buttons()

    # -- options ------------------------------------------------------------------------------

    def on_shown(self) -> None:
        self._load_trips()
        self._load_history()

    @property
    def report_type(self) -> ReportType:
        return combo_enum(self.type_combo, ReportType) or ReportType.VEHICLE_OVERVIEW

    def _load_vehicles(self) -> None:
        current = self.vehicle_combo.currentData()
        active = self.ctx.state.active_vehicle
        self.vehicle_combo.blockSignals(True)
        self.vehicle_combo.clear()
        try:
            vehicles = self.ctx.vehicles.list_vehicles()
        except SmartDriveError:
            vehicles = []
        for vehicle in vehicles:
            self.vehicle_combo.addItem(vehicle.name, vehicle.id)
        wanted = current if current is not None else (active.id if active else None)
        index = self.vehicle_combo.findData(wanted)
        self.vehicle_combo.setCurrentIndex(max(0, index))
        self.vehicle_combo.blockSignals(False)
        self._load_trips()

    def _on_vehicle_selected(self, *_: object) -> None:
        self._load_trips()

    def _load_trips(self) -> None:
        vehicle_id = self.vehicle_combo.currentData()
        current = self.trip_combo.currentData()
        self.trip_combo.blockSignals(True)
        self.trip_combo.clear()
        choices: list[tuple[int, str]] = []
        if vehicle_id is not None:
            try:
                choices = self.ctx.reports.trip_choices(vehicle_id)
            except SmartDriveError:
                choices = []
        for session_id, text in choices:
            self.trip_combo.addItem(text, session_id)
        if not choices:
            self.trip_combo.addItem("No recorded trips", None)
        index = self.trip_combo.findData(current)
        self.trip_combo.setCurrentIndex(max(0, index))
        self.trip_combo.blockSignals(False)
        self._update_summary()

    def _on_type_changed(self, *_: object) -> None:
        defaults = set(DEFAULT_SECTIONS[self.report_type])
        for key, check in self.section_checks.items():
            check.blockSignals(True)
            check.setChecked(key in defaults)
            check.blockSignals(False)
        self._update_summary()

    def _on_dates_toggled(self, checked: bool) -> None:
        self.from_date.setEnabled(checked)
        self.to_date.setEnabled(checked)
        self._update_summary()

    def _period(self) -> tuple[datetime | None, datetime | None]:
        if not self.date_check.isChecked():
            return None, None
        start = datetime.combine(_qdate_to_date(self.from_date.date()), time.min).astimezone()
        end = datetime.combine(_qdate_to_date(self.to_date.date()), time.max).astimezone()
        return start.astimezone(UTC), end.astimezone(UTC)

    def build_request(self) -> ReportRequest:
        kind = self.report_type
        start, end = self._period()
        sections = frozenset(k for k, c in self.section_checks.items() if c.isChecked())
        return ReportRequest(
            kind,
            vehicle_id=self.vehicle_combo.currentData() if kind.needs_vehicle else None,
            start=start,
            end=end,
            session_id=self.trip_combo.currentData() if kind.needs_trip else None,
            sections=sections,
            include_identifiers=self.identifiers_check.isChecked(),
            include_notes=self.notes_check.isChecked(),
        )

    def _update_summary(self, *_: object) -> None:
        kind = self.report_type
        self.vehicle_combo.setEnabled(kind.needs_vehicle)
        self.trip_combo.setEnabled(kind.needs_trip)
        chosen = [SECTIONS[k] for k, c in self.section_checks.items() if c.isChecked()]
        problems = []
        if kind.needs_vehicle and self.vehicle_combo.currentData() is None:
            problems.append("add a vehicle first")
        if kind.needs_trip and self.trip_combo.currentData() is None:
            problems.append("choose a recorded trip")
        if not chosen:
            problems.append("choose at least one section")
        if problems:
            self.summary_label.setText("To generate this report: " + "; ".join(problems) + ".")
        else:
            period = "the selected dates" if self.date_check.isChecked() else "all recorded data"
            self.summary_label.setText(
                f"{kind.label} covering {period}. Sections: {', '.join(chosen)}. Every report "
                "states its data sources (simulated, live or recorded) and its limitations."
            )
        self._refresh_buttons()

    def _can_generate_pdf(self) -> bool:
        kind = self.report_type
        if kind.needs_vehicle and self.vehicle_combo.currentData() is None:
            return False
        if kind.needs_trip and self.trip_combo.currentData() is None:
            return False
        return any(c.isChecked() for c in self.section_checks.values())

    # -- generation ---------------------------------------------------------------------------

    def choose_folder(self) -> None:
        folder = choose_directory(self, "Default report folder", Path(self.folder_edit.text()))
        if folder is None:
            return
        self.folder_edit.setText(str(folder))
        self.ctx.app.settings.reports.output_directory = str(folder)
        self.ctx.state.save_settings()

    def _folder(self) -> Path:
        folder = Path(self.folder_edit.text())
        return folder if folder.is_dir() else default_directory(self.ctx.app.settings)

    def generate_pdf(self) -> None:
        if self._job is not None or not self._can_generate_pdf():
            return
        request = self.build_request()
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        name = f"smartdrive-{request.report_type.value.replace('_', '-')}-{stamp}.pdf"
        path = choose_save_path(self, "Save PDF report", self._folder(), name, PDF_FILTER)
        if path is None:
            return
        live = self.ctx.diagnostics.latest
        reports = self.ctx.reports
        self._start(
            request.report_type.label,
            lambda: reports.generate_pdf(request, path, overwrite=True, live=live),
        )

    def export_csv(self) -> None:
        if self._job is not None:
            return
        dataset = combo_enum(self.csv_combo, CsvDataset)
        if dataset is None:
            return
        vehicle_id = self.vehicle_combo.currentData()
        session_id = self.trip_combo.currentData()
        if dataset.needs_trip and session_id is None:
            self._show_failure("Choose a recorded trip to export its telemetry.")
            return
        start, end = self._period()
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        name = f"smartdrive-{dataset.value.replace('_', '-')}-{stamp}.csv"
        path = choose_save_path(self, "Save CSV export", self._folder(), name, CSV_FILTER)
        if path is None:
            return
        reports = self.ctx.reports
        self._start(
            f"CSV export: {dataset.label}",
            lambda: reports.export_csv(
                dataset,
                path,
                vehicle_id=vehicle_id,
                session_id=session_id,
                start=start,
                end=end,
                overwrite=True,
            ),
        )

    def _start(self, kind: str, job: Callable[[], ExportResult]) -> None:
        job_id = self.ctx.tasks.submit(kind, job)
        if job_id is None:
            self._show_failure("Another export is being prepared. Try again in a moment.")
            return
        self._job = job_id
        self._job_kind = kind
        self.progress.setVisible(True)
        self.result_pill.set_status(f"Generating {kind}…", StatusLevel.INFO)
        self.result_text.setText("")
        self._refresh_buttons()

    def _on_job_finished(self, job_id: int, result: object) -> None:
        if job_id != self._job:
            return
        self._job = None
        self.progress.setVisible(False)
        if not isinstance(result, ExportResult) or not result.path.exists():
            self._show_failure("The export did not produce a file.")
            return
        self.last_result = result
        rows = f", {result.rows} row(s)" if result.rows is not None else ""
        size_kb = max(1, round(result.size_bytes / 1024))
        self.result_pill.set_status(f"Saved {result.path.name}", StatusLevel.NORMAL)
        self.result_text.setText(f"{self._job_kind}: {size_kb} KB{rows}. ID {result.report_id}.")
        self.ctx.notifications.post(
            NotificationSeverity.SUCCESS,
            NotificationCategory.REPORT,
            "Report ready",
            f"{self._job_kind} was saved as {result.path.name}.",
            dedup_key=f"report:{result.report_id}",
        )
        self._load_history()
        self._refresh_buttons()

    def _on_job_failed(self, job_id: int, message: str) -> None:
        if job_id != self._job:
            return
        self._job = None
        self.progress.setVisible(False)
        self._show_failure(message)
        self.ctx.notifications.post(
            NotificationSeverity.WARNING,
            NotificationCategory.REPORT,
            "Report could not be generated",
            f"{self._job_kind}: {message}",
            dedup_key=f"report:failed:{self._job_kind}",
            cooldown_s=30.0,
        )
        self._load_history()

    def _show_failure(self, message: str) -> None:
        self.result_pill.set_status("Not generated", StatusLevel.CRITICAL)
        self.result_text.setText(message)
        self._refresh_buttons()

    # -- opening ------------------------------------------------------------------------------

    def open_result(self) -> None:
        if self.last_result is not None and not open_path(self.last_result.path):
            self._show_failure("The file could not be opened; it may have been moved.")

    def open_folder(self) -> None:
        target = self.last_result.path.parent if self.last_result else self._folder()
        if not open_path(target):
            self._show_failure("The folder could not be opened.")

    def _open_history(self, *_: object) -> None:
        item_id = row_data(self.history_table)
        item = next((h for h in self._history if h.id == item_id), None)
        if item is None or not item.file_path:
            return
        if not open_path(Path(item.file_path)):
            self._show_failure("That file no longer exists at its saved location.")

    def _load_history(self) -> None:
        try:
            self._history = self.ctx.reports.history()
        except SmartDriveError as exc:
            self.history_stack.show_error("Export history could not be loaded", exc.user_message)
            return
        if not self._history:
            self.history_stack.show_empty("No exports yet")
            return
        rows = [
            (
                local_time(h.created_at),
                report_label(h.report_type),
                h.export_format.upper(),
                h.file_name,
                "Saved" if h.status == "success" else f"Failed: {h.message}",
            )
            for h in self._history
        ]
        fill_table(self.history_table, rows, [h.id for h in self._history])
        self.history_stack.show_content()

    def _refresh_buttons(self, *_: object) -> None:
        idle = self._job is None
        self.pdf_button.setEnabled(idle and self._can_generate_pdf())
        self.csv_button.setEnabled(idle)
        has_result = self.last_result is not None
        self.open_button.setEnabled(has_result)

    def apply_palette(self, palette: ThemePalette) -> None:
        self.result_pill.apply_palette(palette)
