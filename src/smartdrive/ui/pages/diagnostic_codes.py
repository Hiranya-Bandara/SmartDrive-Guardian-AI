"""Diagnostic Codes: read-only trouble-code scans, history, details and export.

There is deliberately no way to clear codes: the OBD-II command allowlist does not contain
mode 04, and this page offers no such action.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
)

from smartdrive.config.constants import DtcStatus
from smartdrive.models.trouble_code import DtcScan, TroubleCode
from smartdrive.obd.dtc import CodeCategory
from smartdrive.obd.session import DtcScanResult
from smartdrive.services.dtc_reference import lookup
from smartdrive.services.report_service import CsvDataset
from smartdrive.ui.context import UiContext
from smartdrive.ui.dialogs.files import CSV_FILTER, choose_save_path, default_directory
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel
from smartdrive.ui.widgets.tables import MISSING, fill_table, local_time, make_table, row_data
from smartdrive.utils.exceptions import SmartDriveError

CODE_COLUMNS = ("Code", "Status", "Category", "Description", "First detected", "Last detected")
SCAN_COLUMNS = ("Scanned", "Data", "MIL", "Stored", "Pending", "Permanent", "Protocol")
STATUS_TEXT = {
    DtcStatus.STORED: "Stored (confirmed)",
    DtcStatus.PENDING: "Pending",
    DtcStatus.PERMANENT: "Permanent",
}
LIMITATION_TEXT = (
    "Generic OBD-II gives access to emissions-related powertrain codes reported by the engine "
    "and transmission control units. Body (B), chassis (C) and network (U) modules, and "
    "manufacturer-specific codes, are often not reachable this way and may need dealer-level "
    "equipment. A code means a control unit detected a condition; it does not confirm that a "
    "particular component has failed. SmartDrive never clears codes."
)


def _bool_text(value: bool | None, true: str, false: str) -> str:
    return MISSING if value is None else (true if value else false)


class DiagnosticCodesPage(Page):
    key = "codes"
    title = "Diagnostic Codes"
    subtitle = "Read-only trouble codes from the vehicle's OBD-II interface"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._codes: list[TroubleCode] = []
        self._scans: list[DtcScan] = []
        self._export_job: int | None = None

        scan_card = Card("Scan")
        scan_row = QHBoxLayout()
        self.scan_button = IconPushButton("Scan for codes", "search", variant="primary")
        self.scan_button.setToolTip("Read stored, pending and permanent codes (read-only)")
        self.export_button = IconPushButton("Export CSV", "file")
        self.scan_status = StatusIndicator("Not scanned", StatusLevel.OFFLINE)
        scan_row.addWidget(self.scan_button)
        scan_row.addWidget(self.export_button)
        scan_row.addWidget(self.scan_status)
        scan_row.addStretch(1)
        scan_card.body.addLayout(scan_row)
        self.scan_summary = label("", wrap=True)
        scan_card.body.addWidget(self.scan_summary)
        scan_card.body.addWidget(label(LIMITATION_TEXT, "muted", wrap=True))
        self.content.addWidget(scan_card)

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search code or description")
        self.search_edit.setAccessibleName("Search trouble codes")
        self.search_edit.setClearButtonEnabled(True)
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("Filter by status")
        self.status_filter.addItem("All statuses", None)
        for status, text in STATUS_TEXT.items():
            self.status_filter.addItem(text, status)
        self.category_filter = QComboBox()
        self.category_filter.setAccessibleName("Filter by category")
        self.category_filter.addItem("All categories", None)
        for category in CodeCategory:
            self.category_filter.addItem(f"{category.value} — {category.label}", category.value)
        self.active_check = QCheckBox("Present in latest scan only")
        filters.addWidget(self.search_edit, 2)
        filters.addWidget(self.status_filter, 1)
        filters.addWidget(self.category_filter, 1)
        filters.addWidget(self.active_check)
        self.content.addLayout(filters)

        middle = QHBoxLayout()
        middle.setSpacing(16)
        codes_card = Card("Trouble codes")
        self.code_table = make_table(CODE_COLUMNS, "Trouble codes", stretch=3)
        self.code_table.setMinimumHeight(260)
        self.code_stack = StatefulStack(self.code_table)
        codes_card.body.addWidget(self.code_stack)
        middle.addWidget(codes_card, 3)

        details_card = Card("Code details")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.details: dict[str, QLabel] = {}
        for key, title in (
            ("code", "Code"),
            ("category", "Category / system"),
            ("description", "Description"),
            ("source", "Description source"),
            ("status", "Status"),
            ("first", "First detected"),
            ("last", "Most recent detection"),
            ("count", "Times detected"),
            ("vehicle", "Vehicle"),
            ("provenance", "Diagnostic source"),
            ("freeze", "Freeze frame"),
            ("steps", "Recommended next steps"),
        ):
            value = label(MISSING, wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.details[key] = value
            form.addRow(label(title, "muted"), value)
        details_card.body.addLayout(form)
        details_card.body.addWidget(label("AI findings around this scan", "section-title"))
        self.findings_list = QListWidget()
        self.findings_list.setAccessibleName("Related AI diagnostic findings")
        self.findings_list.setMaximumHeight(130)
        details_card.body.addWidget(self.findings_list)
        middle.addWidget(details_card, 2)
        self.content.addLayout(middle)

        history_card = Card("Scan history")
        self.scan_table = make_table(SCAN_COLUMNS, "Scan history")
        self.scan_table.setMinimumHeight(160)
        self.scan_stack = StatefulStack(self.scan_table)
        history_card.body.addWidget(self.scan_stack)
        self.content.addWidget(history_card)

        self.scan_button.clicked.connect(self.scan)
        self.export_button.clicked.connect(self.export_csv)
        self.search_edit.textChanged.connect(self._on_filter_changed)
        self.status_filter.currentIndexChanged.connect(self._on_filter_changed)
        self.category_filter.currentIndexChanged.connect(self._on_filter_changed)
        self.active_check.toggled.connect(self._on_filter_changed)
        self.code_table.itemSelectionChanged.connect(self._show_details)
        ctx.connection.scan_completed.connect(self._on_scan_completed)
        ctx.connection.scan_failed.connect(self._on_scan_failed)
        ctx.connection.status_changed.connect(self._refresh_buttons)
        ctx.state.active_vehicle_changed.connect(self._on_vehicle_changed)
        ctx.tasks.finished.connect(self._on_job_finished)
        ctx.tasks.failed.connect(self._on_job_failed)
        self.reload()

    # -- actions ------------------------------------------------------------------------------

    def on_shown(self) -> None:
        self.reload()

    def scan(self) -> None:
        if self.ctx.state.active_vehicle is None:
            self.scan_status.set_status("Select an active vehicle first", StatusLevel.WARNING)
            return
        self.scan_status.set_status("Scanning…", StatusLevel.INFO)
        self.ctx.connection.scan_codes()
        self._refresh_buttons()

    def export_csv(self) -> None:
        vehicle = self.ctx.state.active_vehicle
        if vehicle is None or self._export_job is not None:
            return
        settings = self.ctx.app.settings
        path = choose_save_path(
            self,
            "Export trouble codes",
            default_directory(settings),
            "smartdrive-trouble-codes.csv",
            CSV_FILTER,
        )
        if path is None:
            return
        reports = self.ctx.reports
        vehicle_id = vehicle.id
        self._export_job = self.ctx.tasks.submit(
            "Export trouble codes",
            lambda: reports.export_csv(
                CsvDataset.TROUBLE_CODES, path, vehicle_id=vehicle_id, overwrite=True
            ),
        )
        self.export_button.setEnabled(self._export_job is None)

    # -- data ---------------------------------------------------------------------------------

    def _on_vehicle_changed(self, _vehicle: object) -> None:
        self.reload()

    def _on_filter_changed(self, *_: object) -> None:
        self.reload_codes()

    def reload(self) -> None:
        vehicle = self.ctx.state.active_vehicle
        if vehicle is None:
            self._codes, self._scans = [], []
            self.code_stack.show_empty(
                "No active vehicle", "Select a vehicle in the garage to see its trouble codes."
            )
            self.scan_stack.show_empty("No scans")
            self.scan_summary.setText("")
            self._show_details()
            self._refresh_buttons()
            return
        try:
            self._scans = self.ctx.obd_history.scans(vehicle.id)
        except SmartDriveError as exc:
            self.scan_stack.show_error("Scan history could not be loaded", exc.user_message)
            self._scans = []
        else:
            self._render_scans()
        self.reload_codes()
        self._refresh_buttons()

    def reload_codes(self) -> None:
        vehicle = self.ctx.state.active_vehicle
        if vehicle is None:
            return
        try:
            self._codes = self.ctx.obd_history.trouble_codes(
                vehicle.id,
                active_only=self.active_check.isChecked(),
                status=combo_enum(self.status_filter, DtcStatus),
                category=self.category_filter.currentData(),
                search=self.search_edit.text(),
            )
        except SmartDriveError as exc:
            self.code_stack.show_error("Trouble codes could not be loaded", exc.user_message)
            return
        if not self._codes:
            if self._scans:
                self.code_stack.show_empty(
                    "No codes match",
                    "No trouble codes were reported, or none match the filters. An empty "
                    "result does not mean the vehicle is free of faults.",
                )
            else:
                self.code_stack.show_empty(
                    "Not scanned yet",
                    "Connect to the vehicle on the Vehicle Connection page, then press Scan.",
                )
            self._show_details()
            return
        rows = []
        for code in self._codes:
            info = lookup(code.code)
            rows.append(
                (
                    code.code,
                    STATUS_TEXT[code.status] + ("" if code.is_active else " · not in latest scan"),
                    info.category.label,
                    code.description or info.display_description,
                    local_time(code.first_seen_at),
                    local_time(code.last_seen_at),
                )
            )
        fill_table(self.code_table, rows, [c.id for c in self._codes])
        self.code_stack.show_content()
        if self.code_table.currentRow() < 0:
            self.code_table.selectRow(0)
        self._show_details()

    def _render_scans(self) -> None:
        if not self._scans:
            self.scan_stack.show_empty("No scans yet")
            self.scan_summary.setText("No trouble-code scan has been made for this vehicle.")
            return
        rows = [
            (
                local_time(s.scanned_at),
                ("Mock adapter (simulated)" if s.is_mock else s.data_source.value.title()),
                _bool_text(s.mil_on, "On", "Off"),
                str(s.stored_count),
                str(s.pending_count),
                "Not supported" if s.permanent_count is None else str(s.permanent_count),
                s.protocol or MISSING,
            )
            for s in self._scans
        ]
        fill_table(self.scan_table, rows, [s.id for s in self._scans])
        self.scan_stack.show_content()
        latest = self._scans[0]
        permanent = (
            "permanent codes not supported by this vehicle"
            if latest.permanent_count is None
            else f"{latest.permanent_count} permanent"
        )
        mock = " Mock adapter: these codes are simulated." if latest.is_mock else ""
        notes = (" " + " ".join(latest.notes)) if latest.notes else ""
        self.scan_summary.setText(
            f"Latest scan {local_time(latest.scanned_at)}: check-engine lamp "
            f"{_bool_text(latest.mil_on, 'on', 'off')}; {latest.stored_count} stored, "
            f"{latest.pending_count} pending, {permanent}.{mock}{notes}"
        )

    def _show_details(self) -> None:
        code_id = row_data(self.code_table) if self._codes else None
        code = next((c for c in self._codes if c.id == code_id), None)
        self.findings_list.clear()
        if code is None:
            for value in self.details.values():
                value.setText(MISSING)
            return
        info = lookup(code.code)
        vehicle = self.ctx.state.active_vehicle
        scan = next((s for s in self._scans if s.id == code.last_scan_id), None)
        self.details["code"].setText(code.code)
        generic = "generic (SAE-defined)" if info.generic else "manufacturer-specific"
        self.details["category"].setText(f"{info.category.label} · {info.system} · {generic}")
        self.details["description"].setText(code.description or info.display_description)
        self.details["source"].setText(code.description_source or info.source)
        self.details["status"].setText(
            STATUS_TEXT[code.status]
            + ("" if code.is_active else " — not reported in the latest scan")
        )
        self.details["first"].setText(local_time(code.first_seen_at, seconds=True))
        self.details["last"].setText(local_time(code.last_seen_at, seconds=True))
        self.details["count"].setText(str(code.detection_count))
        self.details["vehicle"].setText(vehicle.name if vehicle else MISSING)
        if scan is None:
            self.details["provenance"].setText(MISSING)
            self.details["freeze"].setText(MISSING)
        else:
            source = "Mock adapter (simulated data)" if scan.is_mock else "Live vehicle scan"
            self.details["provenance"].setText(
                f"{source} · {scan.protocol or 'protocol unknown'} · scan #{scan.id}"
            )
            frame = scan.freeze_frame
            if frame and frame.get("trigger_code") == code.code and frame.get("values"):
                values = ", ".join(f"{k}: {v}" for k, v in frame["values"].items())
                self.details["freeze"].setText(values)
            else:
                self.details["freeze"].setText("Not captured for this code")
            self._load_findings(scan.scanned_at)
        self.details["steps"].setText(info.next_steps)

    def _load_findings(self, around: datetime) -> None:
        vehicle = self.ctx.state.active_vehicle
        if vehicle is None:
            return
        try:
            findings = self.ctx.obd_history.related_findings(vehicle.id, around)
        except SmartDriveError:
            findings = []
        if not findings:
            self.findings_list.addItem("No AI or rule findings recorded around this scan.")
            return
        for f in findings:
            self.findings_list.addItem(
                f"{local_time(f['created_at'])} · {f['severity']} · {f['summary']} ({f['source']})"
            )

    # -- results ------------------------------------------------------------------------------

    def _on_scan_completed(self, result: object) -> None:
        if isinstance(result, DtcScanResult):
            self.scan_status.set_status("Scan finished (not saved: no vehicle)", StatusLevel.INFO)
        elif isinstance(result, DtcScan):
            total = result.stored_count + result.pending_count + (result.permanent_count or 0)
            level = StatusLevel.WARNING if total else StatusLevel.NORMAL
            self.scan_status.set_status(f"Scan finished: {total} code(s)", level)
        self.reload()

    def _on_scan_failed(self, message: str) -> None:
        self.scan_status.set_status("Scan failed", StatusLevel.CRITICAL)
        self.scan_summary.setText(message)
        self._refresh_buttons()

    def _on_job_finished(self, job_id: int, result: object) -> None:
        if job_id != self._export_job:
            return
        self._export_job = None
        self._refresh_buttons()
        path = getattr(result, "path", None)
        rows = getattr(result, "rows", None)
        self.ctx.notifier.notify(f"Exported {rows} code record(s) to {getattr(path, 'name', '')}.")

    def _on_job_failed(self, job_id: int, message: str) -> None:
        if job_id != self._export_job:
            return
        self._export_job = None
        self._refresh_buttons()
        self.ctx.notifier.notify(f"Export failed: {message}", StatusLevel.CRITICAL)

    def _refresh_buttons(self, *_: object) -> None:
        connection = self.ctx.connection
        has_vehicle = self.ctx.state.active_vehicle is not None
        self.scan_button.setEnabled(
            has_vehicle and connection.ecu_connected and not connection.scanning
        )
        self.scan_button.setToolTip(
            "Read stored, pending and permanent codes (read-only)"
            if connection.ecu_connected
            else "Connect to the vehicle on the Vehicle Connection page first"
        )
        self.export_button.setEnabled(has_vehicle and self._export_job is None)

    def apply_palette(self, palette: ThemePalette) -> None:
        self.scan_status.apply_palette(palette)
