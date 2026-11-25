"""Alert Centre: application notifications and diagnostic condition alerts.

Reading or acknowledging something here changes only its notification state. A diagnostic
condition is resolved only when a later analysis with sufficient data no longer finds it; the
page shows "acknowledged", "condition resolved" and "condition still active" separately.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from smartdrive.config.constants import (
    DiagnosticSource,
    NotificationCategory,
    NotificationSeverity,
    Severity,
)
from smartdrive.models.notification import DiagnosticAlert, Notification
from smartdrive.ui.context import UiContext
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel
from smartdrive.ui.widgets.tables import (
    MISSING,
    SEVERITY_TEXT,
    fill_table,
    local_time,
    make_table,
    row_data,
)
from smartdrive.utils.exceptions import SmartDriveError

NOTIFICATION_COLUMNS = ("Last occurred", "Level", "Category", "Title", "Times", "State")
ALERT_COLUMNS = ("Last occurred", "Severity", "Condition", "Source", "Data", "Times", "State")
LEVEL_TEXT = {
    NotificationSeverity.CRITICAL: "‼ Critical",
    NotificationSeverity.WARNING: "! Warning",
    NotificationSeverity.SUCCESS: "✓ Success",
    NotificationSeverity.INFORMATION: "i Information",
}
SOURCE_TEXT = {
    DiagnosticSource.RULE: "Rule",
    DiagnosticSource.CLASSIFIER: "Classifier",
    DiagnosticSource.ANOMALY_DETECTOR: "Anomaly detector",
}


def _qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def notification_state(n: Notification) -> str:
    if n.acknowledged_at is not None:
        return "Acknowledged"
    return "Read" if n.read_at is not None else "Unread"


class _DateRange(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox("Dates")
        self.start = QDateEdit(QDate.currentDate().addDays(-30))
        self.end = QDateEdit(QDate.currentDate())
        for edit, name in ((self.start, "From date"), (self.end, "To date")):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setAccessibleName(name)
            edit.setEnabled(False)
        layout.addWidget(self.check)
        layout.addWidget(self.start)
        layout.addWidget(self.end)
        self.check.toggled.connect(self.start.setEnabled)
        self.check.toggled.connect(self.end.setEnabled)

    def bounds(self) -> tuple[datetime | None, datetime | None]:
        if not self.check.isChecked():
            return None, None
        start = datetime.combine(_qdate(self.start.date()), time.min).astimezone()
        end = datetime.combine(_qdate(self.end.date()), time.max).astimezone()
        return start.astimezone(UTC), end.astimezone(UTC)


class AlertsPage(Page):
    key = "alerts"
    title = "Alert Centre"
    subtitle = "Notifications and diagnostic alerts"
    navigate = Signal(str)

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._notifications: list[Notification] = []
        self._alerts: list[DiagnosticAlert] = []

        header = QHBoxLayout()
        self.unread_pill = StatusIndicator("No unread notifications", StatusLevel.NORMAL)
        self.preferences_button = IconPushButton(
            "Notification preferences", "settings", tooltip="Desktop, sound and voice options"
        )
        header.addWidget(self.unread_pill)
        header.addStretch(1)
        header.addWidget(self.preferences_button)
        self.content.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_notifications(), "Notifications")
        self.tabs.addTab(self._build_alerts(), "Diagnostic alerts")
        self.content.addWidget(self.tabs, 1)

        self.preferences_button.clicked.connect(self._open_preferences)
        ctx.notifications.changed.connect(self._on_changed)
        ctx.state.vehicles_changed.connect(self._load_vehicles)
        self._load_vehicles()

    # -- construction -------------------------------------------------------------------------

    def _vehicle_combo(self, name: str) -> QComboBox:
        combo = QComboBox()
        combo.setAccessibleName(name)
        return combo

    def _build_notifications(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        filters = QHBoxLayout()
        self.n_search = QLineEdit()
        self.n_search.setPlaceholderText("Search notifications")
        self.n_search.setAccessibleName("Search notifications")
        self.n_search.setClearButtonEnabled(True)
        self.n_severity = QComboBox()
        self.n_severity.setAccessibleName("Filter by level")
        self.n_severity.addItem("All levels", None)
        for level, text in LEVEL_TEXT.items():
            self.n_severity.addItem(text, level)
        self.n_category = QComboBox()
        self.n_category.setAccessibleName("Filter by category")
        self.n_category.addItem("All categories", None)
        for category in NotificationCategory:
            self.n_category.addItem(category.value.title(), category.value)
        self.n_vehicle = self._vehicle_combo("Filter notifications by vehicle")
        self.n_dates = _DateRange()
        self.n_unread = QCheckBox("Unread only")
        filters.addWidget(self.n_search, 2)
        for widget in (
            self.n_severity,
            self.n_category,
            self.n_vehicle,
            self.n_dates,
            self.n_unread,
        ):
            filters.addWidget(widget)
        layout.addLayout(filters)
        row = QHBoxLayout()
        row.setSpacing(16)
        table_card = Card("Notifications")
        self.n_table = make_table(NOTIFICATION_COLUMNS, "Notifications", stretch=3)
        self.n_table.setMinimumHeight(300)
        self.n_stack = StatefulStack(self.n_table)
        table_card.body.addWidget(self.n_stack)
        actions = QHBoxLayout()
        self.mark_read_button = IconPushButton("Mark as read", "check")
        self.mark_all_button = IconPushButton("Mark all as read", "check")
        self.ack_button = IconPushButton("Acknowledge", "check", variant="primary")
        for button in (self.mark_read_button, self.mark_all_button, self.ack_button):
            actions.addWidget(button)
        actions.addStretch(1)
        table_card.body.addLayout(actions)
        row.addWidget(table_card, 3)
        detail_card = Card("Details")
        self.n_detail = label("Select a notification.", wrap=True)
        self.n_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_card.body.addWidget(self.n_detail)
        detail_card.body.addStretch(1)
        row.addWidget(detail_card, 2)
        layout.addLayout(row, 1)

        self.n_search.textChanged.connect(self._on_n_filters)
        for combo in (self.n_severity, self.n_category, self.n_vehicle):
            combo.currentIndexChanged.connect(self._on_n_filters)
        self.n_unread.toggled.connect(self._on_n_filters)
        self.n_dates.check.toggled.connect(self._on_n_filters)
        self.n_dates.start.dateChanged.connect(self._on_n_filters)
        self.n_dates.end.dateChanged.connect(self._on_n_filters)
        self.n_table.itemSelectionChanged.connect(self._show_notification)
        self.mark_read_button.clicked.connect(self.mark_read)
        self.mark_all_button.clicked.connect(self.mark_all_read)
        self.ack_button.clicked.connect(self.acknowledge)
        return page

    def _build_alerts(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.addWidget(
            label(
                "Acknowledging an alert records that you have seen it. It does not clear the "
                "vehicle condition: an alert is resolved only when a later analysis with enough "
                "data no longer finds the condition.",
                "muted",
                wrap=True,
            )
        )
        filters = QHBoxLayout()
        self.a_search = QLineEdit()
        self.a_search.setPlaceholderText("Search alerts")
        self.a_search.setAccessibleName("Search alerts")
        self.a_search.setClearButtonEnabled(True)
        self.a_active = QCheckBox("Active conditions only")
        self.a_severity = QComboBox()
        self.a_severity.setAccessibleName("Filter by severity")
        self.a_severity.addItem("All severities", None)
        for severity in (Severity.CRITICAL, Severity.WARNING):
            self.a_severity.addItem(SEVERITY_TEXT[severity], severity)
        self.a_source = QComboBox()
        self.a_source.setAccessibleName("Filter by diagnostic source")
        self.a_source.addItem("All sources", None)
        for source, text in SOURCE_TEXT.items():
            self.a_source.addItem(text, source.value)
        self.a_vehicle = self._vehicle_combo("Filter alerts by vehicle")
        self.a_dates = _DateRange()
        filters.addWidget(self.a_search, 2)
        for widget in (self.a_active, self.a_severity, self.a_source, self.a_vehicle, self.a_dates):
            filters.addWidget(widget)
        layout.addLayout(filters)
        row = QHBoxLayout()
        row.setSpacing(16)
        table_card = Card("Diagnostic alerts")
        self.a_table = make_table(ALERT_COLUMNS, "Diagnostic alerts", stretch=2)
        self.a_table.setMinimumHeight(300)
        self.a_stack = StatefulStack(self.a_table)
        table_card.body.addWidget(self.a_stack)
        actions = QHBoxLayout()
        self.ack_alert_button = IconPushButton("Acknowledge alert", "check", variant="primary")
        actions.addWidget(self.ack_alert_button)
        actions.addStretch(1)
        table_card.body.addLayout(actions)
        row.addWidget(table_card, 3)
        detail_card = Card("Alert details and evidence")
        self.a_detail = label("Select an alert.", wrap=True)
        self.a_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_card.body.addWidget(self.a_detail)
        detail_card.body.addStretch(1)
        row.addWidget(detail_card, 2)
        layout.addLayout(row, 1)

        self.a_search.textChanged.connect(self._on_a_filters)
        self.a_active.toggled.connect(self._on_a_filters)
        for combo in (self.a_severity, self.a_source, self.a_vehicle):
            combo.currentIndexChanged.connect(self._on_a_filters)
        self.a_dates.check.toggled.connect(self._on_a_filters)
        self.a_dates.start.dateChanged.connect(self._on_a_filters)
        self.a_dates.end.dateChanged.connect(self._on_a_filters)
        self.a_table.itemSelectionChanged.connect(self._show_alert)
        self.ack_alert_button.clicked.connect(self.acknowledge_alert)
        return page

    # -- loading ------------------------------------------------------------------------------

    def on_shown(self) -> None:
        self.reload()

    def _load_vehicles(self) -> None:
        try:
            vehicles = self.ctx.vehicles.list_vehicles()
        except SmartDriveError:
            vehicles = []
        for combo in (self.n_vehicle, self.a_vehicle):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All vehicles", None)
            for vehicle in vehicles:
                combo.addItem(vehicle.name, vehicle.id)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)
        self.reload()

    def _on_changed(self) -> None:
        if self.isVisible():
            self.reload()
        else:
            self._update_unread()

    def _on_n_filters(self, *_: object) -> None:
        self.load_notifications()

    def _on_a_filters(self, *_: object) -> None:
        self.load_alerts()

    def reload(self) -> None:
        self.load_notifications()
        self.load_alerts()

    def _update_unread(self) -> None:
        count = self.ctx.notifications.unread_count()
        self.unread_pill.set_status(
            f"{count} unread notification{'s' if count != 1 else ''}"
            if count
            else "No unread notifications",
            StatusLevel.WARNING if count else StatusLevel.NORMAL,
        )

    def load_notifications(self) -> None:
        self._update_unread()
        start, end = self.n_dates.bounds()
        try:
            self._notifications = self.ctx.notifications.service.list_notifications(
                unread_only=self.n_unread.isChecked(),
                severity=combo_enum(self.n_severity, NotificationSeverity),
                category=self.n_category.currentData(),
                vehicle_id=self.n_vehicle.currentData(),
                start=start,
                end=end,
                search=self.n_search.text(),
            )
        except SmartDriveError as exc:
            self.n_stack.show_error("Notifications could not be loaded", exc.user_message)
            return
        if not self._notifications:
            self.n_stack.show_empty("No notifications", "Nothing matches the current filters.")
            self._show_notification()
            return
        rows = [
            (
                local_time(n.last_occurrence_at),
                LEVEL_TEXT[n.severity],
                n.category.title(),
                n.title,
                str(n.occurrence_count),
                notification_state(n),
            )
            for n in self._notifications
        ]
        fill_table(self.n_table, rows, [n.id for n in self._notifications])
        self.n_stack.show_content()
        self._show_notification()

    def load_alerts(self) -> None:
        start, end = self.a_dates.bounds()
        try:
            self._alerts = self.ctx.notifications.service.alerts(
                active_only=self.a_active.isChecked(),
                vehicle_id=self.a_vehicle.currentData(),
                severity=combo_enum(self.a_severity, Severity),
                source=self.a_source.currentData(),
                start=start,
                end=end,
                search=self.a_search.text(),
            )
        except SmartDriveError as exc:
            self.a_stack.show_error("Alerts could not be loaded", exc.user_message)
            return
        if not self._alerts:
            self.a_stack.show_empty(
                "No diagnostic alerts",
                "Warnings and critical findings from monitoring appear here.",
            )
            self._show_alert()
            return
        rows = [
            (
                local_time(a.last_occurrence_at),
                SEVERITY_TEXT.get(a.severity, a.severity.value),
                a.title,
                SOURCE_TEXT.get(a.source, MISSING) if a.source else MISSING,
                a.data_source.value.title() if a.data_source else MISSING,
                str(a.occurrence_count),
                a.state_text,
            )
            for a in self._alerts
        ]
        fill_table(self.a_table, rows, [a.id for a in self._alerts])
        self.a_stack.show_content()
        self._show_alert()

    # -- details and actions ------------------------------------------------------------------

    def selected_notification(self) -> Notification | None:
        selected = row_data(self.n_table) if self._notifications else None
        return next((n for n in self._notifications if n.id == selected), None)

    def selected_alert(self) -> DiagnosticAlert | None:
        selected = row_data(self.a_table) if self._alerts else None
        return next((a for a in self._alerts if a.id == selected), None)

    def _show_notification(self) -> None:
        n = self.selected_notification()
        self.mark_read_button.setEnabled(n is not None and n.read_at is None)
        self.ack_button.setEnabled(n is not None and n.acknowledged_at is None)
        if n is None:
            self.n_detail.setText("Select a notification.")
            return
        lines = [
            n.message or "",
            f"Level: {LEVEL_TEXT[n.severity]} · Category: {n.category.title()}",
            f"First: {local_time(n.created_at, seconds=True)} · "
            f"Last: {local_time(n.last_occurrence_at, seconds=True)} · "
            f"{n.occurrence_count} occurrence(s)",
            f"Notification: {notification_state(n).lower()}",
        ]
        if n.alert_id is not None:
            try:
                alert = self.ctx.notifications.service.alert(n.alert_id)
            except SmartDriveError:
                alert = None
            if alert is not None:
                lines.append(f"Linked diagnostic alert: {alert.state_text}")
        body = "<br>".join(_escape(line) for line in lines if line)
        self.n_detail.setText(f"<b>{_escape(n.title)}</b><br>{body}")

    def _show_alert(self) -> None:
        a = self.selected_alert()
        self.ack_alert_button.setEnabled(a is not None and a.acknowledged_at is None)
        if a is None:
            self.a_detail.setText("Select an alert.")
            return
        evidence = (
            json.dumps(a.evidence, indent=1, ensure_ascii=False, default=str)
            if a.evidence
            else "No evidence values were stored with this alert."
        )
        resolved = (
            f"resolved {local_time(a.resolved_at, seconds=True)}"
            if a.resolved_at
            else "still active (not seen resolved by a later analysis)"
        )
        acknowledged = (
            f"acknowledged {local_time(a.acknowledged_at, seconds=True)}"
            if a.acknowledged_at
            else "not acknowledged"
        )
        self.a_detail.setText(
            "<br>".join(
                [
                    f"<b>{_escape(a.title)}</b>",
                    _escape(a.message),
                    _escape(
                        f"Severity: {SEVERITY_TEXT.get(a.severity, a.severity.value)} · "
                        f"Source: {SOURCE_TEXT.get(a.source, MISSING) if a.source else MISSING}"
                    ),
                    _escape(f"Condition: {resolved}"),
                    _escape(f"Alert: {acknowledged}"),
                    _escape(
                        f"First: {local_time(a.created_at, seconds=True)} · "
                        f"Last: {local_time(a.last_occurrence_at, seconds=True)} · "
                        f"{a.occurrence_count} occurrence(s)"
                    ),
                    "<b>Evidence</b>",
                    f"<pre>{_escape(evidence)}</pre>",
                ]
            )
        )

    def mark_read(self) -> None:
        n = self.selected_notification()
        if n is not None:
            self._act(lambda: self.ctx.notifications.mark_read(n.id))

    def mark_all_read(self) -> None:
        self._act(self.ctx.notifications.mark_all_read)

    def acknowledge(self) -> None:
        n = self.selected_notification()
        if n is not None:
            self._act(lambda: self.ctx.notifications.acknowledge(n.id))

    def acknowledge_alert(self) -> None:
        a = self.selected_alert()
        if a is not None:
            self._act(lambda: self.ctx.notifications.acknowledge_alert(a.id))

    def _act(self, action: Callable[[], object]) -> None:
        try:
            action()
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
        self.reload()

    def _open_preferences(self) -> None:
        self.navigate.emit("settings")

    def apply_palette(self, palette: ThemePalette) -> None:
        self.unread_pill.apply_palette(palette)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
