"""Add/edit dialogs for maintenance records and user-defined service schedules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from smartdrive.config.constants import MaintenanceCategory, MaintenanceStatus
from smartdrive.models.maintenance import (
    MaintenanceRecordInput,
    MaintenanceRecordView,
    ScheduleInput,
    ScheduleView,
)
from smartdrive.services.maintenance_service import EXAMPLE_INTERVALS, EXAMPLE_NOTE
from smartdrive.ui.widgets.base import combo_enum, label

COMMON_CURRENCIES = ("LKR", "USD", "EUR", "GBP", "INR", "AUD", "JPY")
STATUS_LABELS = {
    MaintenanceStatus.COMPLETED: "Completed",
    MaintenanceStatus.PLANNED: "Planned",
    MaintenanceStatus.CANCELLED: "Cancelled",
}


def _qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def _pydate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


class OptionalDate(QWidget):
    """A date that may be left empty (unchecked)."""

    def __init__(self, text: str, value: date | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox(text)
        self.edit = QDateEdit(_qdate(value or date.today()))
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("yyyy-MM-dd")
        self.edit.setAccessibleName(text)
        self.check.setChecked(value is not None)
        self.edit.setEnabled(value is not None)
        self.check.toggled.connect(self.edit.setEnabled)
        layout.addWidget(self.check)
        layout.addWidget(self.edit, 1)

    def value(self) -> date | None:
        return _pydate(self.edit.date()) if self.check.isChecked() else None

    def set_value(self, value: date | None) -> None:
        self.check.setChecked(value is not None)
        if value is not None:
            self.edit.setDate(_qdate(value))


def _km_spin(name: str) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0, 5_000_000)
    spin.setDecimals(0)
    spin.setSingleStep(500)
    spin.setSuffix(" km")
    spin.setSpecialValueText("Not recorded")
    spin.setAccessibleName(name)
    return spin


def _category_combo(current: str | None) -> QComboBox:
    combo = QComboBox()
    combo.setAccessibleName("Maintenance category")
    for category in MaintenanceCategory:
        combo.addItem(category.label, category)
    index = combo.findData(MaintenanceCategory(current) if current else None)
    combo.setCurrentIndex(max(0, index))
    return combo


FIELD_LABELS = {
    "title": "Description",
    "task_name": "Task",
    "service_date": "Service date",
    "mileage_km": "Odometer",
    "provider": "Provider",
    "cost": "Cost",
    "currency": "Currency",
    "notes": "Notes",
    "next_due_date": "Next service date",
    "next_due_km": "Next service odometer",
    "interval_days": "Time interval",
    "interval_km": "Distance interval",
    "last_done_mileage_km": "Last done at",
}


def validation_message(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        text = str(error.get("msg", "")).removeprefix("Value error, ")
        field = ".".join(str(p) for p in error.get("loc", ()))
        label_text = FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
        messages.append(f"{label_text}: {text}" if field else text)
    return "; ".join(messages)


class _Base(QDialog):
    def __init__(self, title: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self.layout_ = QVBoxLayout(self)
        self.form = QFormLayout()
        self.layout_.addLayout(self.form)
        self.error_label = label("", "field-error", wrap=True)
        self.error_label.setVisible(False)
        self.layout_.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._try_accept)
        self.buttons.rejected.connect(self.reject)

    def finish_layout(self) -> None:
        self.layout_.addWidget(self.buttons)

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _try_accept(self) -> None:  # pragma: no cover - overridden
        self.accept()


class RecordDialog(_Base):
    def __init__(
        self,
        *,
        currency: str,
        schedules: list[ScheduleView],
        record: MaintenanceRecordView | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Edit maintenance record" if record else "Add maintenance record", parent)
        self.value: MaintenanceRecordInput | None = None
        self.category = _category_combo(record.category if record else None)
        self.title_edit = QLineEdit(record.title if record else "")
        self.title_edit.setPlaceholderText("What was done, e.g. Engine oil and filter")
        self.title_edit.setAccessibleName("Service description")
        self.status = QComboBox()
        self.status.setAccessibleName("Status")
        for status, text in STATUS_LABELS.items():
            self.status.addItem(text, status)
        if record:
            self.status.setCurrentIndex(self.status.findData(record.status))
        self.service_date = OptionalDate(
            "Service date", record.service_date if record else date.today()
        )
        self.odometer = _km_spin("Odometer at service")
        self.odometer.setValue((record.mileage_km or 0) if record else 0)
        self.provider = QLineEdit((record.provider or "") if record else "")
        self.provider.setAccessibleName("Service provider")
        self.cost = QLineEdit("" if record is None or record.cost is None else str(record.cost))
        self.cost.setPlaceholderText("Optional, e.g. 18500.00")
        self.cost.setAccessibleName("Service cost")
        self.currency = QComboBox()
        self.currency.setEditable(True)
        self.currency.setAccessibleName("Currency")
        for code in dict.fromkeys((currency, *COMMON_CURRENCIES)):
            self.currency.addItem(code)
        if record and record.currency:
            self.currency.setCurrentText(record.currency)
        self.schedule = QComboBox()
        self.schedule.setAccessibleName("Schedule")
        self.schedule.addItem("Not linked to a schedule", None)
        for schedule in schedules:
            self.schedule.addItem(schedule.task_name, schedule.id)
        if record and record.schedule_id:
            self.schedule.setCurrentIndex(max(0, self.schedule.findData(record.schedule_id)))
        self.next_date = OptionalDate("Next service date", record.next_due_date if record else None)
        self.next_km = _km_spin("Next service odometer")
        self.next_km.setValue((record.next_due_km or 0) if record else 0)
        self.notes = QPlainTextEdit(record.notes if record else "")
        self.notes.setAccessibleName("Notes")
        self.notes.setMaximumHeight(80)
        cost_row = QHBoxLayout()
        cost_row.addWidget(self.cost, 2)
        cost_row.addWidget(self.currency, 1)
        for title, widget in (
            ("Category", self.category),
            ("Description", self.title_edit),
            ("Status", self.status),
            ("", self.service_date),
            ("Odometer", self.odometer),
            ("Provider", self.provider),
            ("Cost", self._cost_widget(cost_row)),
            ("Schedule", self.schedule),
            ("", self.next_date),
            ("Next service at", self.next_km),
            ("Notes", self.notes),
        ):
            self.form.addRow(title, widget)
        self.form.addRow(
            "",
            label(
                "Notes stay on this computer; they are not included in reports or exports.",
                "muted",
                wrap=True,
            ),
        )
        self.finish_layout()

    @staticmethod
    def _cost_widget(row: QHBoxLayout) -> QWidget:
        holder = QWidget()
        row.setContentsMargins(0, 0, 0, 0)
        holder.setLayout(row)
        return holder

    def _try_accept(self) -> None:
        cost_text = self.cost.text().strip().replace(",", "")
        try:
            cost = Decimal(cost_text) if cost_text else None
        except InvalidOperation:
            self.show_error("Enter the cost as a number, for example 18500.00.")
            return
        currency = self.currency.currentText().strip().upper() if cost is not None else None
        try:
            self.value = MaintenanceRecordInput(
                category=combo_enum(self.category, MaintenanceCategory),
                title=self.title_edit.text(),
                status=combo_enum(self.status, MaintenanceStatus),
                service_date=self.service_date.value(),
                mileage_km=self.odometer.value() or None,
                provider=self.provider.text(),
                cost=cost,
                currency=currency,
                notes=self.notes.toPlainText(),
                next_due_date=self.next_date.value(),
                next_due_km=self.next_km.value() or None,
                schedule_id=self.schedule.currentData(),
            )
        except ValidationError as exc:
            self.show_error(validation_message(exc))
            return
        self.accept()


class ScheduleDialog(_Base):
    def __init__(
        self, *, schedule: ScheduleView | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__("Edit service schedule" if schedule else "Add service schedule", parent)
        self.value: ScheduleInput | None = None
        self._source = schedule.interval_source if schedule else "user"
        self.category = _category_combo(schedule.category if schedule else "custom")
        self.task = QLineEdit(schedule.task_name if schedule else "")
        self.task.setPlaceholderText("e.g. Engine oil replacement")
        self.task.setAccessibleName("Task name")
        self.days = QSpinBox()
        self.days.setRange(0, 3650)
        self.days.setSuffix(" days")
        self.days.setSpecialValueText("No time interval")
        self.days.setAccessibleName("Interval in days")
        self.days.setValue((schedule.interval_days or 0) if schedule else 0)
        self.km = QDoubleSpinBox()
        self.km.setRange(0, 500_000)
        self.km.setDecimals(0)
        self.km.setSingleStep(1000)
        self.km.setSuffix(" km")
        self.km.setSpecialValueText("No distance interval")
        self.km.setAccessibleName("Interval in kilometres")
        self.km.setValue((schedule.interval_km or 0) if schedule else 0)
        self.example_button = QPushButton("Fill in example interval")
        self.example_button.setToolTip(EXAMPLE_NOTE)
        self.source_label = label("", "muted", wrap=True)
        self.last_date = OptionalDate("Last done on", schedule.last_done_date if schedule else None)
        self.last_km = _km_spin("Last done at")
        self.last_km.setValue((schedule.last_done_mileage_km or 0) if schedule else 0)
        self.remind_days = QSpinBox()
        self.remind_days.setRange(0, 365)
        self.remind_days.setSuffix(" days before")
        self.remind_days.setValue(schedule.reminder_days_before if schedule else 14)
        self.remind_km = QDoubleSpinBox()
        self.remind_km.setRange(0, 50_000)
        self.remind_km.setDecimals(0)
        self.remind_km.setSuffix(" km before")
        self.remind_km.setValue(schedule.reminder_km_before if schedule else 500)
        self.active = QCheckBox("Active")
        self.active.setChecked(schedule.is_active if schedule else True)
        self.notes = QPlainTextEdit(schedule.notes if schedule else "")
        self.notes.setMaximumHeight(70)
        for title, widget in (
            ("Category", self.category),
            ("Task", self.task),
            ("Every", self.days),
            ("or every", self.km),
            ("", self.example_button),
            ("", self.source_label),
            ("", self.last_date),
            ("Last done at", self.last_km),
            ("Remind", self.remind_days),
            ("", self.remind_km),
            ("", self.active),
            ("Notes", self.notes),
        ):
            self.form.addRow(title, widget)
        self.example_button.clicked.connect(self.use_example)
        self.days.valueChanged.connect(self._mark_user)
        self.km.valueChanged.connect(self._mark_user)
        self._refresh_source()
        self.finish_layout()

    def use_example(self) -> None:
        category = combo_enum(self.category, MaintenanceCategory) or MaintenanceCategory.CUSTOM
        days, km = EXAMPLE_INTERVALS.get(category, (None, None))
        if days is None and km is None:
            self.show_error("There is no example interval for this category; enter your own.")
            return
        self.days.blockSignals(True)
        self.km.blockSignals(True)
        self.days.setValue(days or 0)
        self.km.setValue(km or 0)
        self.days.blockSignals(False)
        self.km.blockSignals(False)
        if not self.task.text().strip():
            self.task.setText(category.label)
        self._source = "example"
        self._refresh_source()

    def _mark_user(self, *_: object) -> None:
        self._source = "user"
        self._refresh_source()

    def _refresh_source(self) -> None:
        self.source_label.setText(
            EXAMPLE_NOTE
            if self._source == "example"
            else "Enter the interval from the vehicle's service documentation."
        )

    def _try_accept(self) -> None:
        try:
            self.value = ScheduleInput(
                category=combo_enum(self.category, MaintenanceCategory),
                task_name=self.task.text(),
                interval_days=self.days.value() or None,
                interval_km=self.km.value() or None,
                last_done_date=self.last_date.value(),
                last_done_mileage_km=self.last_km.value() or None,
                reminder_days_before=self.remind_days.value(),
                reminder_km_before=self.remind_km.value(),
                interval_source=self._source,
                notes=self.notes.toPlainText(),
                is_active=self.active.isChecked(),
            )
        except ValidationError as exc:
            self.show_error(validation_message(exc))
            return
        self.accept()
