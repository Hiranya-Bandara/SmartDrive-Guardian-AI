"""Maintenance centre: records, user-defined schedules, reminders, costs and AI observations.

Schedules use the intervals the user enters. Example intervals can be filled in but are labelled
as examples, never as manufacturer recommendations. Mileage reminders use the odometer reading
the user last recorded and say so when it is old. Costs are totalled per currency; different
currencies are never added together.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from smartdrive.config.constants import MaintenanceCategory, MaintenanceStatus
from smartdrive.models.maintenance import (
    MaintenanceRecordView,
    ScheduleState,
    ScheduleStatus,
    ScheduleView,
)
from smartdrive.services.maintenance_service import CostSummary
from smartdrive.ui.context import UiContext
from smartdrive.ui.dialogs import confirm as confirm_dialogs
from smartdrive.ui.dialogs.maintenance_dialogs import STATUS_LABELS, RecordDialog, ScheduleDialog
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.explanation_chart import BarChart
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel
from smartdrive.ui.widgets.tables import (
    MISSING,
    day,
    fill_table,
    local_time,
    make_table,
    number,
    row_data,
)
from smartdrive.utils.exceptions import SmartDriveError

SCHEDULE_COLUMNS = ("Task", "Interval", "Last done", "Next due", "Status", "Interval source")
RECORD_COLUMNS = ("Date", "Service", "Category", "Odometer", "Provider", "Cost", "Status")
STATE_SYMBOL = {
    ScheduleState.OVERDUE: "‼",
    ScheduleState.DUE: "!",
    ScheduleState.UPCOMING: "›",
    ScheduleState.UP_TO_DATE: "✓",
    ScheduleState.INSUFFICIENT_MILEAGE: "?",
    ScheduleState.NOT_SCHEDULED: "–",
}
COST_VIEWS = (("by_year", "Per year"), ("by_month", "Per month"), ("by_category", "Per category"))


def category_label(value: str) -> str:
    try:
        return MaintenanceCategory(value).label
    except ValueError:
        return value.replace("_", " ").title()


def interval_text(days: int | None, km: float | None) -> str:
    parts = []
    if days:
        parts.append(f"{days} days")
    if km:
        parts.append(f"{km:,.0f} km")
    return " or ".join(parts) if parts else MISSING


def due_text(status: ScheduleStatus) -> str:
    parts = []
    if status.due_date is not None:
        remaining = status.days_remaining
        suffix = "" if remaining is None else f" ({remaining:+d} days)"
        parts.append(f"{status.due_date.isoformat()}{suffix}")
    if status.due_km is not None:
        remaining_km = status.km_remaining
        suffix = "" if remaining_km is None else f" ({remaining_km:+,.0f} km)"
        parts.append(f"{status.due_km:,.0f} km{suffix}")
    return " / ".join(parts) if parts else MISSING


def money(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


class MaintenancePage(Page):
    key = "maintenance"
    title = "Maintenance"
    subtitle = "Service records, schedules, reminders and costs for the active vehicle"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self.service = ctx.maintenance
        self._schedules: list[ScheduleView] = []
        self._statuses: list[ScheduleStatus] = []
        self._records: list[MaintenanceRecordView] = []
        self._costs: list[CostSummary] = []

        header = Card("Vehicle and odometer")
        head_row = QHBoxLayout()
        self.vehicle_label = label("No active vehicle", "section-title")
        self.odometer_pill = StatusIndicator("Odometer: not recorded", StatusLevel.OFFLINE)
        self.odometer_spin = QDoubleSpinBox()
        self.odometer_spin.setRange(0, 5_000_000)
        self.odometer_spin.setDecimals(0)
        self.odometer_spin.setSingleStep(100)
        self.odometer_spin.setSuffix(" km")
        self.odometer_spin.setAccessibleName("Current odometer reading")
        self.odometer_button = IconPushButton("Record odometer", "check")
        head_row.addWidget(self.vehicle_label)
        head_row.addWidget(self.odometer_pill)
        head_row.addStretch(1)
        head_row.addWidget(self.odometer_spin)
        head_row.addWidget(self.odometer_button)
        header.body.addLayout(head_row)
        header.body.addWidget(
            label(
                "Mileage reminders use the reading you record here, with its date. SmartDrive "
                "does not read the odometer from the vehicle.",
                "muted",
                wrap=True,
            )
        )
        self.content.addWidget(header)

        status_row = QHBoxLayout()
        status_row.setSpacing(16)
        self.attention_card = Card("Overdue and due")
        self.attention_list = QListWidget()
        self.attention_list.setAccessibleName("Overdue and due maintenance")
        self.attention_list.setMaximumHeight(140)
        self.attention_card.body.addWidget(self.attention_list)
        self.upcoming_card = Card("Upcoming")
        self.upcoming_list = QListWidget()
        self.upcoming_list.setAccessibleName("Upcoming maintenance")
        self.upcoming_list.setMaximumHeight(140)
        self.upcoming_card.body.addWidget(self.upcoming_list)
        status_row.addWidget(self.attention_card, 1)
        status_row.addWidget(self.upcoming_card, 1)
        self.content.addLayout(status_row)

        schedules_card = Card("Service schedules")
        self.schedule_table = make_table(SCHEDULE_COLUMNS, "Service schedules")
        self.schedule_table.setMinimumHeight(170)
        self.schedule_stack = StatefulStack(self.schedule_table)
        schedules_card.body.addWidget(self.schedule_stack)
        schedule_actions = QHBoxLayout()
        self.add_schedule_button = IconPushButton("Add schedule", "plus", variant="primary")
        self.edit_schedule_button = IconPushButton("Edit", "edit")
        self.delete_schedule_button = IconPushButton("Delete", "trash", variant="danger")
        for button in (
            self.add_schedule_button,
            self.edit_schedule_button,
            self.delete_schedule_button,
        ):
            schedule_actions.addWidget(button)
        schedule_actions.addStretch(1)
        schedules_card.body.addLayout(schedule_actions)
        self.content.addWidget(schedules_card)

        records_card = Card("Maintenance history")
        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search service, provider or notes")
        self.search_edit.setAccessibleName("Search maintenance records")
        self.search_edit.setClearButtonEnabled(True)
        self.category_filter = QComboBox()
        self.category_filter.setAccessibleName("Filter by category")
        self.category_filter.addItem("All categories", None)
        for category in MaintenanceCategory:
            self.category_filter.addItem(category.label, category.value)
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("Filter by status")
        self.status_filter.addItem("All statuses", None)
        for status, text in STATUS_LABELS.items():
            self.status_filter.addItem(text, status)
        filters.addWidget(self.search_edit, 2)
        filters.addWidget(self.category_filter, 1)
        filters.addWidget(self.status_filter, 1)
        records_card.body.addLayout(filters)
        self.record_table = make_table(RECORD_COLUMNS, "Maintenance records", stretch=1)
        self.record_table.setMinimumHeight(200)
        self.record_stack = StatefulStack(self.record_table)
        records_card.body.addWidget(self.record_stack)
        record_actions = QHBoxLayout()
        self.add_record_button = IconPushButton("Add record", "plus", variant="primary")
        self.edit_record_button = IconPushButton("Edit", "edit")
        self.delete_record_button = IconPushButton("Delete", "trash", variant="danger")
        for button in (self.add_record_button, self.edit_record_button, self.delete_record_button):
            record_actions.addWidget(button)
        record_actions.addStretch(1)
        records_card.body.addLayout(record_actions)
        self.content.addWidget(records_card)

        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        cost_card = Card("Costs")
        cost_top = QHBoxLayout()
        self.currency_combo = QComboBox()
        self.currency_combo.setAccessibleName("Currency")
        self.cost_view = QComboBox()
        self.cost_view.setAccessibleName("Cost grouping")
        for key, text in COST_VIEWS:
            self.cost_view.addItem(text, key)
        cost_top.addWidget(self.currency_combo)
        cost_top.addWidget(self.cost_view)
        cost_top.addStretch(1)
        cost_card.body.addLayout(cost_top)
        self.cost_totals = label("", wrap=True)
        cost_card.body.addWidget(self.cost_totals)
        self.cost_chart = BarChart("Spending", "Amount", height=200)
        cost_card.body.addWidget(self.cost_chart)
        bottom.addWidget(cost_card, 3)

        observations_card = Card("AI-related observations (experimental)")
        observations = QVBoxLayout()
        self.observation_list = QListWidget()
        self.observation_list.setAccessibleName("AI-related maintenance observations")
        self.observation_list.setWordWrap(True)
        self.observation_list.setMinimumHeight(180)
        self.observation_basis = label("", "muted", wrap=True)
        observations.addWidget(self.observation_list)
        observations.addWidget(self.observation_basis)
        observations.addWidget(
            label(
                "These are prompts to plan an inspection, based on recent findings, trouble "
                "codes and maintenance history. They are separate from your schedules, do not "
                "predict when anything will fail, and come from models trained on simulated data.",
                "muted",
                wrap=True,
            )
        )
        observations_card.body.addLayout(observations)
        bottom.addWidget(observations_card, 2)
        self.content.addLayout(bottom)

        self.odometer_button.clicked.connect(self.record_odometer)
        self.add_schedule_button.clicked.connect(self.add_schedule)
        self.edit_schedule_button.clicked.connect(self.edit_schedule)
        self.delete_schedule_button.clicked.connect(self.delete_schedule)
        self.add_record_button.clicked.connect(self.add_record)
        self.edit_record_button.clicked.connect(self.edit_record)
        self.delete_record_button.clicked.connect(self.delete_record)
        self.record_table.doubleClicked.connect(self.edit_record)
        self.schedule_table.doubleClicked.connect(self.edit_schedule)
        self.search_edit.textChanged.connect(self._on_filters)
        self.category_filter.currentIndexChanged.connect(self._on_filters)
        self.status_filter.currentIndexChanged.connect(self._on_filters)
        self.currency_combo.currentIndexChanged.connect(self._draw_costs)
        self.cost_view.currentIndexChanged.connect(self._draw_costs)
        self.schedule_table.itemSelectionChanged.connect(self._refresh_buttons)
        self.record_table.itemSelectionChanged.connect(self._refresh_buttons)
        ctx.state.active_vehicle_changed.connect(self._on_vehicle_changed)
        self.reload()

    @property
    def vehicle_id(self) -> int | None:
        vehicle = self.ctx.state.active_vehicle
        return vehicle.id if vehicle else None

    # -- loading ------------------------------------------------------------------------------

    def on_shown(self) -> None:
        self.reload()

    def _on_vehicle_changed(self, _vehicle: object) -> None:
        self.reload()

    def _on_filters(self, *_: object) -> None:
        self.load_records()

    def reload(self) -> None:
        vehicle = self.ctx.state.active_vehicle
        self.vehicle_label.setText(vehicle.name if vehicle else "No active vehicle")
        if vehicle is None:
            self._schedules, self._statuses, self._records, self._costs = [], [], [], []
            for stack in (self.schedule_stack, self.record_stack):
                stack.show_empty("No active vehicle", "Select a vehicle in the garage.")
            self.attention_list.clear()
            self.upcoming_list.clear()
            self.observation_list.clear()
            self.cost_chart.clear_bars()
            self.cost_totals.setText("")
            self.odometer_pill.set_status("Odometer: no vehicle", StatusLevel.OFFLINE)
            self._refresh_buttons()
            return
        settings = self.ctx.app.settings.maintenance
        try:
            odometer = self.service.odometer(vehicle.id)
            self._schedules = self.service.schedules(vehicle.id)
            self._statuses = self.service.statuses(
                vehicle.id, today=date.today(), odometer_stale_days=settings.odometer_stale_days
            )
            self._costs = self.service.cost_summary(vehicle.id)
            observations, basis = self.service.observations(vehicle.id)
        except SmartDriveError as exc:
            self.schedule_stack.show_error("Maintenance data could not be loaded", exc.user_message)
            return
        if odometer.km is None:
            self.odometer_pill.set_status("Odometer: not recorded", StatusLevel.WARNING)
        else:
            current = odometer.is_current(date.today(), settings.odometer_stale_days)
            self.odometer_pill.set_status(
                f"Odometer {odometer.km:,.0f} km on {local_time(odometer.recorded_at)}"
                + ("" if current else " — out of date"),
                StatusLevel.NORMAL if current else StatusLevel.WARNING,
            )
            self.odometer_spin.setValue(odometer.km)
        self._render_statuses()
        self._render_costs()
        self.observation_list.clear()
        if not observations:
            self.observation_list.addItem(
                "No observation: there is not enough evidence to suggest an inspection."
            )
        for item in observations:
            entry = QListWidgetItem(f"{item.title}\n{item.detail}\nEvidence: {item.evidence}")
            self.observation_list.addItem(entry)
        self.observation_basis.setText(basis)
        self.load_records()

    def _render_statuses(self) -> None:
        self.attention_list.clear()
        self.upcoming_list.clear()
        if not self._statuses:
            self.schedule_stack.show_empty(
                "No schedules",
                "Add a schedule with the intervals from your vehicle's service documentation.",
                action_text="Add schedule",
                action=self.add_schedule,
            )
            self.attention_list.addItem("No schedules configured.")
            self.upcoming_list.addItem("No schedules configured.")
            return
        rows = []
        for status in self._statuses:
            schedule = status.schedule
            symbol = STATE_SYMBOL[status.state]
            note = f" — {status.notes[0]}" if status.notes else ""
            rows.append(
                (
                    schedule.task_name + ("" if schedule.is_active else " (inactive)"),
                    interval_text(schedule.interval_days, schedule.interval_km),
                    " / ".join(
                        p
                        for p in (
                            day(status.baseline_date) if status.baseline_date else "",
                            f"{status.baseline_km:,.0f} km" if status.baseline_km else "",
                        )
                        if p
                    )
                    or "Not recorded",
                    due_text(status),
                    f"{symbol} {status.state.label}",
                    "Example — verify" if schedule.interval_source == "example" else "Entered",
                )
            )
            line = f"{symbol} {schedule.task_name}: {status.state.label} — {due_text(status)}{note}"
            if status.state in (ScheduleState.OVERDUE, ScheduleState.DUE):
                self.attention_list.addItem(line)
            elif status.state is ScheduleState.UPCOMING:
                self.upcoming_list.addItem(line)
            elif status.state is ScheduleState.INSUFFICIENT_MILEAGE:
                self.attention_list.addItem(line)
        if self.attention_list.count() == 0:
            self.attention_list.addItem("Nothing overdue or due.")
        if self.upcoming_list.count() == 0:
            self.upcoming_list.addItem("Nothing upcoming in the reminder window.")
        fill_table(self.schedule_table, rows, [s.schedule.id for s in self._statuses])
        self.schedule_stack.show_content()
        self._refresh_buttons()

    def load_records(self) -> None:
        vehicle_id = self.vehicle_id
        if vehicle_id is None:
            return
        try:
            self._records = self.service.records(
                vehicle_id,
                category=self.category_filter.currentData(),
                status=combo_enum(self.status_filter, MaintenanceStatus),
                search=self.search_edit.text(),
            )
        except SmartDriveError as exc:
            self.record_stack.show_error("Records could not be loaded", exc.user_message)
            return
        if not self._records:
            self.record_stack.show_empty(
                "No maintenance records",
                "Add the services you have had done to build the history.",
                action_text="Add record",
                action=self.add_record,
            )
            self._refresh_buttons()
            return
        rows = [
            (
                day(r.service_date),
                r.title,
                category_label(r.category),
                number(r.mileage_km, 0, "km"),
                r.provider or MISSING,
                MISSING if r.cost is None or r.currency is None else money(r.cost, r.currency),
                STATUS_LABELS.get(r.status, r.status.value),
            )
            for r in self._records
        ]
        fill_table(self.record_table, rows, [r.id for r in self._records])
        self.record_stack.show_content()
        self._refresh_buttons()

    def _render_costs(self) -> None:
        current = self.currency_combo.currentText()
        default = self.ctx.app.settings.maintenance.currency
        self.currency_combo.blockSignals(True)
        self.currency_combo.clear()
        for summary in self._costs:
            self.currency_combo.addItem(summary.currency)
        index = self.currency_combo.findText(current or default)
        self.currency_combo.setCurrentIndex(index if index >= 0 else 0)
        self.currency_combo.blockSignals(False)
        if not self._costs:
            self.cost_totals.setText("No completed services with a cost have been recorded.")
        else:
            totals = "; ".join(
                f"{money(s.total, s.currency)} over {s.record_count} service(s)"
                for s in self._costs
            )
            separate = (
                " Each currency is totalled separately; amounts are not converted."
                if len(self._costs) > 1
                else ""
            )
            self.cost_totals.setText(f"Total spent: {totals}.{separate}")
        self._draw_costs()

    def _draw_costs(self, *_: object) -> None:
        summary = next(
            (s for s in self._costs if s.currency == self.currency_combo.currentText()), None
        )
        if summary is None:
            self.cost_chart.clear_bars()
            return
        view = self.cost_view.currentData()
        groups: dict[str, Decimal] = getattr(summary, view)
        labels = [category_label(k) if view == "by_category" else k for k in groups]
        self.cost_chart.set_title(f"Spending in {summary.currency}")
        self.cost_chart.set_bars(labels, [float(v) for v in groups.values()])

    # -- actions ------------------------------------------------------------------------------

    def record_odometer(self) -> None:
        vehicle_id = self.vehicle_id
        if vehicle_id is None:
            return
        try:
            self.service.record_odometer(vehicle_id, self.odometer_spin.value())
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self.ctx.state.reload()
        self.ctx.notifications.check_maintenance()
        self.reload()

    def _selected_schedule(self) -> ScheduleView | None:
        schedule_id = row_data(self.schedule_table) if self._statuses else None
        return next((s for s in self._schedules if s.id == schedule_id), None)

    def _selected_record(self) -> MaintenanceRecordView | None:
        record_id = row_data(self.record_table) if self._records else None
        return next((r for r in self._records if r.id == record_id), None)

    def add_schedule(self) -> None:
        self._edit_schedule(None)

    def edit_schedule(self, *_: object) -> None:
        schedule = self._selected_schedule()
        if schedule is not None:
            self._edit_schedule(schedule)

    def _edit_schedule(self, schedule: ScheduleView | None) -> None:
        vehicle_id = self.vehicle_id
        if vehicle_id is None:
            return
        dialog = ScheduleDialog(schedule=schedule, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.value is None:
            return
        try:
            if schedule is None:
                self.service.add_schedule(vehicle_id, dialog.value)
            else:
                self.service.update_schedule(vehicle_id, schedule.id, dialog.value)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self.ctx.notifications.check_maintenance()
        self.reload()

    def delete_schedule(self) -> None:
        schedule = self._selected_schedule()
        vehicle_id = self.vehicle_id
        if schedule is None or vehicle_id is None:
            return
        if not confirm_dialogs.confirm(
            self,
            "Delete schedule?",
            f"Delete the schedule “{schedule.task_name}”? Maintenance records linked to it are "
            "kept.",
            confirm_text="Delete schedule",
            destructive=True,
            palette=self.ctx.theme.palette,
        ):
            return
        try:
            self.service.delete_schedule(vehicle_id, schedule.id)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self.reload()

    def add_record(self) -> None:
        self._edit_record(None)

    def edit_record(self, *_: object) -> None:
        record = self._selected_record()
        if record is not None:
            self._edit_record(record)

    def _edit_record(self, record: MaintenanceRecordView | None) -> None:
        vehicle_id = self.vehicle_id
        if vehicle_id is None:
            return
        dialog = RecordDialog(
            currency=self.ctx.app.settings.maintenance.currency,
            schedules=self._schedules,
            record=record,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.value is None:
            return
        try:
            if record is None:
                self.service.add_record(vehicle_id, dialog.value)
            else:
                self.service.update_record(vehicle_id, record.id, dialog.value)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self.ctx.state.reload()
        self.ctx.notifications.check_maintenance()
        self.reload()

    def delete_record(self) -> None:
        record = self._selected_record()
        vehicle_id = self.vehicle_id
        if record is None or vehicle_id is None:
            return
        if not confirm_dialogs.confirm(
            self,
            "Delete maintenance record?",
            f"Delete “{record.title}” ({day(record.service_date)})? This cannot be undone.",
            confirm_text="Delete record",
            destructive=True,
            palette=self.ctx.theme.palette,
        ):
            return
        try:
            self.service.delete_record(vehicle_id, record.id)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self.reload()

    def _refresh_buttons(self, *_: object) -> None:
        has_vehicle = self.vehicle_id is not None
        for button in (self.add_schedule_button, self.add_record_button, self.odometer_button):
            button.setEnabled(has_vehicle)
        has_schedule = self._selected_schedule() is not None
        has_record = self._selected_record() is not None
        self.edit_schedule_button.setEnabled(has_schedule)
        self.delete_schedule_button.setEnabled(has_schedule)
        self.edit_record_button.setEnabled(has_record)
        self.delete_record_button.setEnabled(has_record)

    def apply_palette(self, palette: ThemePalette) -> None:
        self.odometer_pill.apply_palette(palette)
        self.cost_chart.apply_palette(palette)
