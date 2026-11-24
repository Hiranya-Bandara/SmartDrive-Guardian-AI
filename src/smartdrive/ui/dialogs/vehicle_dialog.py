"""Add/edit vehicle form with inline validation backed by the VehicleProfile model."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from smartdrive.config.constants import FuelType, TransmissionType
from smartdrive.models.vehicle import Vehicle, VehicleProfile
from smartdrive.services.vehicle_service import IMAGE_SUFFIXES, VehicleService
from smartdrive.ui.icons import pixmap
from smartdrive.ui.themes.palette import DARK, ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label
from smartdrive.ui.widgets.inputs import FormField
from smartdrive.utils.exceptions import DataValidationError

_ACRONYMS = {"cvt": "CVT", "lpg": "LPG", "cng": "CNG"}


def enum_label(value: str) -> str:
    return _ACRONYMS.get(value, value.replace("_", " ").title())


class OptionalDateEdit(QWidget):
    """A date that may be left unset (``None``)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled_check = QCheckBox("Set")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setEnabled(False)
        self.enabled_check.toggled.connect(self.date_edit.setEnabled)
        layout.addWidget(self.enabled_check)
        layout.addWidget(self.date_edit, 1)

    def value(self) -> date | None:
        if not self.enabled_check.isChecked():
            return None
        qdate = self.date_edit.date()
        return date(qdate.year(), qdate.month(), qdate.day())

    def set_value(self, value: date | None) -> None:
        self.enabled_check.setChecked(value is not None)
        if value is not None:
            self.date_edit.setDate(QDate(value.year, value.month, value.day))


class VehicleDialog(QDialog):
    def __init__(
        self,
        service: VehicleService,
        vehicle: Vehicle | None = None,
        *,
        palette: ThemePalette = DARK,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._vehicle = vehicle
        self._palette = palette
        self.profile: VehicleProfile | None = None
        self._image_name: str | None = vehicle.image_path if vehicle else None
        self._imported: list[str] = []
        self.setWindowTitle("Edit vehicle" if vehicle else "Add vehicle")
        self.setModal(True)
        self.resize(720, 680)

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(80)
        self.name_edit.setPlaceholderText("e.g. Daily driver")
        self.manufacturer_edit = QLineEdit()
        self.manufacturer_edit.setMaxLength(60)
        self.model_edit = QLineEdit()
        self.model_edit.setMaxLength(60)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(1886, date.today().year + 1)
        self.year_spin.setValue(date.today().year)
        self.fuel_combo = QComboBox()
        for fuel in FuelType:
            self.fuel_combo.addItem(enum_label(fuel.value), fuel)
        self.transmission_combo = QComboBox()
        for transmission in TransmissionType:
            self.transmission_combo.addItem(enum_label(transmission.value), transmission)
        self.engine_spin = QSpinBox()
        self.engine_spin.setRange(0, 20_000)
        self.engine_spin.setSpecialValueText("Not specified")
        self.engine_spin.setSuffix(" cc")
        self.mileage_spin = QDoubleSpinBox()
        self.mileage_spin.setRange(0, 5_000_000)
        self.mileage_spin.setDecimals(0)
        self.mileage_spin.setSuffix(" km")
        self.mileage_spin.setGroupSeparatorShown(True)
        self.registration_edit = QLineEdit()
        self.registration_edit.setMaxLength(16)
        self.registration_edit.setPlaceholderText("Optional")
        self.vin_edit = QLineEdit()
        self.vin_edit.setMaxLength(17)
        self.vin_edit.setPlaceholderText("Optional — 17 characters")
        self.purchase_date = OptionalDateEdit()
        self.last_service_date = OptionalDateEdit()
        self.next_service_date = OptionalDateEdit()
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Optional notes")
        self.notes_edit.setFixedHeight(80)

        self.fields: dict[str, FormField] = {
            "name": FormField("Vehicle name", self.name_edit, required=True),
            "manufacturer": FormField("Manufacturer", self.manufacturer_edit, required=True),
            "model": FormField("Model", self.model_edit, required=True),
            "year": FormField("Manufacturing year", self.year_spin, required=True),
            "fuel_type": FormField("Fuel type", self.fuel_combo, required=True),
            "transmission": FormField("Transmission", self.transmission_combo, required=True),
            "engine_capacity_cc": FormField("Engine capacity", self.engine_spin),
            "mileage_km": FormField("Current odometer", self.mileage_spin),
            "registration_number": FormField(
                "Registration number",
                self.registration_edit,
                hint="Optional. Stored locally only and masked in log files.",
            ),
            "vin": FormField(
                "VIN",
                self.vin_edit,
                hint="Optional. Stored locally only and masked in log files.",
            ),
            "purchase_date": FormField("Purchase date", self.purchase_date),
            "last_service_date": FormField("Last service date", self.last_service_date),
            "next_service_date": FormField("Next service date", self.next_service_date),
            "notes": FormField("Notes", self.notes_edit),
        }

        form = QWidget()
        grid = QGridLayout(form)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        order = list(self.fields)
        for index, key in enumerate(order[:-1]):
            grid.addWidget(self.fields[key], index // 2, index % 2)
        grid.addWidget(self.fields["notes"], len(order) // 2 + 1, 0, 1, 2)

        image_row = QHBoxLayout()
        self.image_preview = QLabel()
        self.image_preview.setFixedSize(160, 100)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setAccessibleName("Vehicle image preview")
        self.choose_image_button = IconPushButton("Choose image…", "image")
        self.remove_image_button = IconPushButton("Remove image", "x", variant="ghost")
        self.choose_image_button.clicked.connect(self._choose_image)
        self.remove_image_button.clicked.connect(self._remove_image)
        image_buttons = QVBoxLayout()
        image_buttons.addWidget(label("Vehicle image (optional)"))
        image_buttons.addWidget(self.choose_image_button)
        image_buttons.addWidget(self.remove_image_button)
        image_buttons.addStretch(1)
        image_row.addWidget(self.image_preview)
        image_row.addLayout(image_buttons, 1)
        grid.addLayout(image_row, len(order) // 2 + 2, 0, 1, 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form)

        self.general_error = label("", "field-error", wrap=True)
        self.general_error.hide()
        buttons = QDialogButtonBox()
        self.save_button = IconPushButton("Save vehicle", "check", variant="primary")
        cancel = IconPushButton("Cancel")
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.try_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.addWidget(label(self.windowTitle(), "section-title"))
        layout.addWidget(label("Fields marked * are required.", "muted"))
        layout.addWidget(scroll, 1)
        layout.addWidget(self.general_error)
        layout.addWidget(buttons)
        for button in (
            self.save_button,
            cancel,
            self.choose_image_button,
            self.remove_image_button,
        ):
            button.apply_palette(palette)

        if vehicle is not None:
            self._populate(vehicle)
        self._refresh_image()

    def _populate(self, vehicle: Vehicle) -> None:
        self.name_edit.setText(vehicle.name)
        self.manufacturer_edit.setText(vehicle.manufacturer)
        self.model_edit.setText(vehicle.model)
        self.year_spin.setValue(vehicle.year)
        self.fuel_combo.setCurrentIndex(self.fuel_combo.findData(vehicle.fuel_type))
        self.transmission_combo.setCurrentIndex(
            self.transmission_combo.findData(vehicle.transmission)
        )
        self.engine_spin.setValue(vehicle.engine_capacity_cc or 0)
        self.mileage_spin.setValue(vehicle.mileage_km)
        self.registration_edit.setText(vehicle.registration_number or "")
        self.vin_edit.setText(vehicle.vin or "")
        self.purchase_date.set_value(vehicle.purchase_date)
        self.last_service_date.set_value(vehicle.last_service_date)
        self.next_service_date.set_value(vehicle.next_service_date)
        self.notes_edit.setPlainText(vehicle.notes)

    def form_values(self) -> dict[str, Any]:
        return {
            "name": self.name_edit.text(),
            "manufacturer": self.manufacturer_edit.text(),
            "model": self.model_edit.text(),
            "year": self.year_spin.value(),
            "fuel_type": combo_enum(self.fuel_combo, FuelType),
            "transmission": combo_enum(self.transmission_combo, TransmissionType),
            "engine_capacity_cc": self.engine_spin.value() or None,
            "mileage_km": self.mileage_spin.value(),
            "registration_number": self.registration_edit.text() or None,
            "vin": self.vin_edit.text() or None,
            "purchase_date": self.purchase_date.value(),
            "last_service_date": self.last_service_date.value(),
            "next_service_date": self.next_service_date.value(),
            "image_path": self._image_name,
            "notes": self.notes_edit.toPlainText(),
        }

    def try_accept(self) -> bool:
        for field in self.fields.values():
            field.set_error(None)
        self.general_error.hide()
        try:
            self.profile = VehicleProfile.model_validate(self.form_values())
        except ValidationError as exc:
            general: list[str] = []
            for error in exc.errors():
                location = error["loc"][0] if error["loc"] else None
                message = str(error["msg"]).removeprefix("Value error, ")
                if isinstance(location, str) and location in self.fields:
                    self.fields[location].set_error(message)
                else:
                    general.append(message)
            if general:
                self.general_error.setText(" ".join(general))
                self.general_error.show()
            first = next((f for f in self.fields.values() if f.has_error), None)
            if first is not None:
                first.editor.setFocus()
            return False
        self._discard_unused(keep=self._image_name)
        self.accept()
        return True

    def reject(self) -> None:
        self._discard_unused(keep=self._vehicle.image_path if self._vehicle else None)
        super().reject()

    def set_image_file(self, path: Path) -> bool:
        try:
            name = self._service.import_image(path)
        except DataValidationError as exc:
            self.general_error.setText(exc.user_message)
            self.general_error.show()
            return False
        self._imported.append(name)
        self._image_name = name
        self._refresh_image()
        return True

    def _choose_image(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(IMAGE_SUFFIXES))
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose vehicle image", "", f"Images ({patterns})"
        )
        if path:
            self.set_image_file(Path(path))

    def _remove_image(self) -> None:
        self._image_name = None
        self._refresh_image()

    def _refresh_image(self) -> None:
        image = QPixmap()
        if self._image_name:
            stored = self._service.resolve_image(self._image_name)
            if stored is not None:
                image = QPixmap(str(stored))
        if image.isNull():
            self.image_preview.setPixmap(pixmap("car", self._palette.offline, 64))
        else:
            self.image_preview.setPixmap(
                image.scaled(
                    self.image_preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.remove_image_button.setEnabled(self._image_name is not None)

    def _discard_unused(self, keep: str | None) -> None:
        for name in self._imported:
            if name != keep:
                self._service.discard_unused_image(name)
        self._imported.clear()
