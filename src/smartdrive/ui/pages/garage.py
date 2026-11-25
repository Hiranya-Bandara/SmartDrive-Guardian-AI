"""Digital vehicle garage: list, search/filter, CRUD, active selection, details and history."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from smartdrive.config.constants import FuelType, UnitSystem
from smartdrive.core.sensors import SENSOR_BY_KEY, SENSORS
from smartdrive.core.units import MISSING_TEXT, convert_distance, distance_label
from smartdrive.models.vehicle import Vehicle
from smartdrive.services.telemetry_service import SessionSummary
from smartdrive.ui.context import UiContext
from smartdrive.ui.dialogs import confirm as confirm_dialogs
from smartdrive.ui.dialogs.vehicle_dialog import VehicleDialog, enum_label
from smartdrive.ui.icons import pixmap
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.charts import ChartContainer
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusLevel
from smartdrive.utils.exceptions import SmartDriveError

VEHICLE_COLUMNS = ("Name", "Vehicle", "Year", "Fuel", "Odometer", "Active")
SESSION_COLUMNS = ("Started", "Source", "Scenario", "Duration", "Readings", "Distance")


def mask_identifier(value: str | None) -> str:
    if not value:
        return "Not recorded"
    visible = value[-4:]
    return f"{'•' * max(0, len(value) - 4)}{visible}"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "In progress"
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _table(columns: tuple[str, ...], name: str) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setAccessibleName(name)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    return table


class GaragePage(Page):
    key = "garage"
    title = "Vehicle Garage"
    subtitle = "Manage vehicles, select the active vehicle and review history"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._vehicles: list[Vehicle] = []
        self._sessions: list[SessionSummary] = []

        toolbar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by name, manufacturer or model")
        self.search_edit.setAccessibleName("Search vehicles")
        self.search_edit.setClearButtonEnabled(True)
        self.fuel_filter = QComboBox()
        self.fuel_filter.setAccessibleName("Filter by fuel type")
        self.fuel_filter.addItem("All fuel types", None)
        for fuel in FuelType:
            self.fuel_filter.addItem(enum_label(fuel.value), fuel)
        self.add_button = IconPushButton("Add vehicle", "plus", variant="primary")
        self.edit_button = IconPushButton("Edit", "edit")
        self.active_button = IconPushButton("Set active", "check")
        self.delete_button = IconPushButton("Delete", "trash", variant="danger")
        toolbar.addWidget(self.search_edit, 2)
        toolbar.addWidget(self.fuel_filter, 1)
        toolbar.addStretch(1)
        for button in (self.add_button, self.edit_button, self.active_button, self.delete_button):
            toolbar.addWidget(button)
        self.content.addLayout(toolbar)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        list_card = Card("Vehicles")
        self.table = _table(VEHICLE_COLUMNS, "Vehicle list")
        self.table.setMinimumHeight(300)
        self.list_stack = StatefulStack(self.table)
        list_card.body.addWidget(self.list_stack)
        columns.addWidget(list_card, 3)

        self.details_card = Card("Details")
        details_top = QHBoxLayout()
        self.details_image = QLabel()
        self.details_image.setFixedSize(180, 115)
        self.details_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_name = label("Select a vehicle", "section-title", wrap=True)
        details_top.addWidget(self.details_image)
        details_top.addWidget(self.details_name, 1)
        self.details_form = QFormLayout()
        self.details_form.setHorizontalSpacing(16)
        self.detail_values: dict[str, QLabel] = {}
        for key, title in (
            ("vehicle", "Vehicle"),
            ("fuel", "Fuel / transmission"),
            ("engine", "Engine"),
            ("odometer", "Odometer"),
            ("registration", "Registration"),
            ("vin", "VIN"),
            ("purchase", "Purchased"),
            ("service", "Last / next service"),
            ("notes", "Notes"),
        ):
            value = label(MISSING_TEXT, wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.detail_values[key] = value
            self.details_form.addRow(label(title, "muted"), value)
        self.remove_ids_button = IconPushButton(
            "Remove identifiers",
            "shield",
            variant="ghost",
            tooltip="Erase the VIN and registration number",
        )
        self.details_card.body.addLayout(details_top)
        self.details_card.body.addLayout(self.details_form)
        self.details_card.body.addWidget(self.remove_ids_button, 0, Qt.AlignmentFlag.AlignLeft)
        columns.addWidget(self.details_card, 2)
        self.content.addLayout(columns)

        history_card = Card("Telemetry history")
        history_row = QHBoxLayout()
        history_row.setSpacing(16)
        self.sessions_table = _table(SESSION_COLUMNS, "Recorded sessions")
        self.sessions_table.setMinimumHeight(220)
        self.sessions_stack = StatefulStack(self.sessions_table)
        history_row.addWidget(self.sessions_stack, 3)
        chart_column = QVBoxLayout()
        self.history_sensor = QComboBox()
        self.history_sensor.setAccessibleName("History chart sensor")
        for spec in SENSORS:
            self.history_sensor.addItem(spec.label, spec.key)
        self.history_chart = ChartContainer("Selected session", height=200)
        self.history_chart.add_curve("history", "Reading")
        chart_column.addWidget(self.history_sensor)
        chart_column.addWidget(self.history_chart, 1)
        history_row.addLayout(chart_column, 2)
        history_card.body.addLayout(history_row)
        self.content.addWidget(history_card)

        self.search_edit.textChanged.connect(lambda _t: self.reload())
        self.fuel_filter.currentIndexChanged.connect(lambda _i: self.reload())
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.doubleClicked.connect(lambda _i: self.edit_selected())
        self.add_button.clicked.connect(self.add_vehicle)
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.active_button.clicked.connect(self.activate_selected)
        self.remove_ids_button.clicked.connect(self.remove_identifiers)
        self.sessions_table.itemSelectionChanged.connect(self._show_session)
        self.history_sensor.currentIndexChanged.connect(lambda _i: self._show_session())
        ctx.state.vehicles_changed.connect(self.reload)
        ctx.monitoring.recording_changed.connect(self._load_history)
        self.reload()

    # -- data ---------------------------------------------------------------------------------

    def on_shown(self) -> None:
        self.reload()

    def selected_vehicle(self) -> Vehicle | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self._vehicles[row] if 0 <= row < len(self._vehicles) else None

    def select_vehicle(self, vehicle_id: int) -> None:
        for row, vehicle in enumerate(self._vehicles):
            if vehicle.id == vehicle_id:
                self.table.selectRow(row)
                return

    def reload(self) -> None:
        previous = self.selected_vehicle()
        try:
            self._vehicles = self.ctx.vehicles.list_vehicles(
                search=self.search_edit.text(),
                fuel_type=combo_enum(self.fuel_filter, FuelType),
            )
        except SmartDriveError as exc:
            self.list_stack.show_error(
                "Vehicles could not be loaded", exc.user_message, action=self.reload
            )
            return
        system = self.ctx.app.settings.units.system
        self.table.setRowCount(len(self._vehicles))
        for row, vehicle in enumerate(self._vehicles):
            odometer = convert_distance(vehicle.mileage_km, system)
            cells = (
                vehicle.name,
                f"{vehicle.manufacturer} {vehicle.model}",
                str(vehicle.year),
                enum_label(vehicle.fuel_type.value),
                f"{odometer:,.0f} {distance_label(system)}",
                "Active" if vehicle.is_active else "",
            )
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))
        if self._vehicles:
            self.list_stack.show_content()
        elif self.search_edit.text().strip() or self.fuel_filter.currentData() is not None:
            self.list_stack.show_empty(
                "No matching vehicles", "Try a different search or fuel filter."
            )
        else:
            self.list_stack.show_empty(
                "Your garage is empty",
                "Add a vehicle to record sessions and keep its history.",
                action_text="Add vehicle",
                action=self.add_vehicle,
            )
        if previous is not None:
            self.select_vehicle(previous.id)
        elif self._vehicles:
            active = next((v for v in self._vehicles if v.is_active), self._vehicles[0])
            self.select_vehicle(active.id)
        self._on_selection()

    # -- actions ------------------------------------------------------------------------------

    def _run_dialog(self, dialog: VehicleDialog) -> bool:
        return dialog.exec() == QDialog.DialogCode.Accepted and dialog.profile is not None

    def add_vehicle(self) -> None:
        dialog = VehicleDialog(self.ctx.vehicles, palette=self.ctx.theme.palette, parent=self)
        if not self._run_dialog(dialog) or dialog.profile is None:
            return
        try:
            vehicle = self.ctx.vehicles.add(dialog.profile)
            if self.ctx.state.active_vehicle is None:
                self.ctx.state.set_active_vehicle(vehicle.id)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self.ctx.state.reload()
        self.select_vehicle(vehicle.id)
        self.ctx.notifier.notify(f"{vehicle.name} added to the garage.", StatusLevel.NORMAL)

    def edit_selected(self) -> None:
        vehicle = self.selected_vehicle()
        if vehicle is None:
            return
        dialog = VehicleDialog(
            self.ctx.vehicles, vehicle, palette=self.ctx.theme.palette, parent=self
        )
        if not self._run_dialog(dialog) or dialog.profile is None:
            return
        try:
            self.ctx.vehicles.update(vehicle.id, dialog.profile)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self.ctx.state.reload()
        self.ctx.notifier.notify("Vehicle details saved.", StatusLevel.NORMAL)

    def delete_selected(self) -> None:
        vehicle = self.selected_vehicle()
        if vehicle is None:
            return
        active = self.ctx.state.active_vehicle
        if self.ctx.monitoring.session_id is not None and active and active.id == vehicle.id:
            self.ctx.notifier.notify(
                "Stop recording before deleting this vehicle.", StatusLevel.WARNING
            )
            return
        if not confirm_dialogs.confirm(
            self,
            f"Delete {vehicle.name}?",
            "This permanently removes the vehicle together with all of its recorded sessions "
            "and telemetry. This cannot be undone.",
            confirm_text="Delete vehicle",
            destructive=True,
            palette=self.ctx.theme.palette,
        ):
            return
        try:
            self.ctx.vehicles.delete(vehicle.id)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return
        self.ctx.state.reload()
        self.ctx.notifier.notify(f"{vehicle.name} deleted.", StatusLevel.INFO)

    def activate_selected(self) -> None:
        vehicle = self.selected_vehicle()
        if vehicle is None:
            return
        if self.ctx.monitoring.session_id is not None:
            self.ctx.notifier.notify(
                "Stop recording before changing the active vehicle.", StatusLevel.WARNING
            )
            return
        self.ctx.state.set_active_vehicle(vehicle.id)
        self.ctx.notifier.notify(f"{vehicle.name} is now the active vehicle.", StatusLevel.NORMAL)

    def remove_identifiers(self) -> None:
        vehicle = self.selected_vehicle()
        if vehicle is None or not (vehicle.vin or vehicle.registration_number):
            return
        if not confirm_dialogs.confirm(
            self,
            "Remove identifiers?",
            "The VIN and registration number will be erased from this vehicle's record.",
            confirm_text="Remove",
            destructive=True,
            palette=self.ctx.theme.palette,
        ):
            return
        self.ctx.vehicles.remove_identifiers(vehicle.id)
        self.ctx.state.reload()
        self.ctx.notifier.notify("Identifiers removed.", StatusLevel.NORMAL)

    # -- details and history ------------------------------------------------------------------

    def _on_selection(self) -> None:
        vehicle = self.selected_vehicle()
        has = vehicle is not None
        for button in (self.edit_button, self.delete_button, self.active_button):
            button.setEnabled(has)
        self.active_button.setEnabled(has and not (vehicle and vehicle.is_active))
        self.remove_ids_button.setEnabled(
            has and bool(vehicle and (vehicle.vin or vehicle.registration_number))
        )
        self._show_details(vehicle)
        self._load_history()

    def _show_details(self, vehicle: Vehicle | None) -> None:
        palette = self.ctx.theme.palette
        values = self.detail_values
        if vehicle is None:
            self.details_name.setText("Select a vehicle")
            for value in values.values():
                value.setText(MISSING_TEXT)
            self.details_image.setPixmap(pixmap("car", palette.offline, 64))
            return
        system = self.ctx.app.settings.units.system
        self.details_name.setText(vehicle.name + ("  ·  Active" if vehicle.is_active else ""))
        values["vehicle"].setText(f"{vehicle.year} {vehicle.manufacturer} {vehicle.model}")
        values["fuel"].setText(
            f"{enum_label(vehicle.fuel_type.value)} / {enum_label(vehicle.transmission.value)}"
        )
        values["engine"].setText(
            f"{vehicle.engine_capacity_cc} cc" if vehicle.engine_capacity_cc else "Not specified"
        )
        values["odometer"].setText(
            f"{convert_distance(vehicle.mileage_km, system):,.0f} {distance_label(system)}"
        )
        values["registration"].setText(mask_identifier(vehicle.registration_number))
        values["vin"].setText(mask_identifier(vehicle.vin))
        values["purchase"].setText(str(vehicle.purchase_date or "Not recorded"))
        last = vehicle.last_service_date or MISSING_TEXT
        upcoming = vehicle.next_service_date or MISSING_TEXT
        values["service"].setText(f"{last} / {upcoming}")
        values["notes"].setText(vehicle.notes or MISSING_TEXT)
        image_file = self.ctx.vehicles.image_file(vehicle)
        image = QPixmap(str(image_file)) if image_file else QPixmap()
        if image.isNull():
            self.details_image.setPixmap(pixmap("car", palette.accent, 64))
        else:
            self.details_image.setPixmap(
                image.scaled(
                    self.details_image.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _load_history(self, *_args: object) -> None:
        vehicle = self.selected_vehicle()
        self.history_chart.clear_data()
        if vehicle is None:
            self._sessions = []
            self.sessions_stack.show_empty("No vehicle selected")
            return
        self._sessions = self.ctx.telemetry.session_summaries(vehicle.id)
        if not self._sessions:
            self.sessions_stack.show_empty(
                "No recorded sessions",
                "Start monitoring with “Record session” enabled to build this vehicle's history.",
            )
            return
        system = self.ctx.app.settings.units.system
        self.sessions_table.setRowCount(len(self._sessions))
        for row, summary in enumerate(self._sessions):
            session = summary.session
            distance = session.distance_km
            cells = (
                session.started_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                session.data_source.value.title(),
                enum_label(session.scenario) if session.scenario else MISSING_TEXT,
                format_duration(summary.duration_s),
                f"{summary.sample_count:,}",
                MISSING_TEXT
                if distance is None
                else f"{convert_distance(distance, system):.2f} {distance_label(system)} (est.)",
            )
            for column, text in enumerate(cells):
                self.sessions_table.setItem(row, column, QTableWidgetItem(text))
        self.sessions_stack.show_content()
        self.sessions_table.selectRow(0)
        self._show_session()

    def _show_session(self) -> None:
        rows = self.sessions_table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._sessions):
            self.history_chart.clear_data()
            return
        summary = self._sessions[rows[0].row()]
        key = str(self.history_sensor.currentData())
        spec = SENSOR_BY_KEY[key]
        system: UnitSystem = self.ctx.app.settings.units.system
        samples = self.ctx.telemetry.load_samples(summary.session.id)
        start = summary.session.started_at
        times = [(s.timestamp - start).total_seconds() for s in samples]
        values = [
            float("nan") if getattr(s, key) is None else spec.to_display(getattr(s, key), system)
            for s in samples
        ]
        self.history_chart.set_title(
            f"{summary.session.data_source.value.title()} session · {spec.label}"
        )
        self.history_chart.set_y_label(spec.unit(system))
        self.history_chart.set_data("history", times, values)
        self.history_chart.plot.enableAutoRange()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._show_details(self.selected_vehicle())
