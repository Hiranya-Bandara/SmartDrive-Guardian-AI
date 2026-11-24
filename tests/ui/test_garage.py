"""Vehicle garage page and vehicle dialog."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from pytestqt.qtbot import QtBot

from smartdrive.config.constants import FuelType, TransmissionType
from smartdrive.models.vehicle import Vehicle
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.dialogs.vehicle_dialog import VehicleDialog
from smartdrive.ui.pages.garage import GaragePage, mask_identifier
from smartdrive.ui.widgets.states import ViewState

pytestmark = pytest.mark.ui


def garage(gui: GuiApplication) -> GaragePage:
    gui.window.show_page("garage")
    page = gui.window.pages["garage"]
    assert isinstance(page, GaragePage)
    return page


def fill(dialog: VehicleDialog, name: str = "Weekend Car", **extra: object) -> None:
    dialog.name_edit.setText(name)
    dialog.manufacturer_edit.setText("Mazda")
    dialog.model_edit.setText("MX-5")
    dialog.year_spin.setValue(2019)
    dialog.fuel_combo.setCurrentIndex(dialog.fuel_combo.findData(FuelType.PETROL))
    dialog.transmission_combo.setCurrentIndex(
        dialog.transmission_combo.findData(TransmissionType.MANUAL)
    )
    dialog.engine_spin.setValue(2000)
    dialog.mileage_spin.setValue(int(extra.get("mileage", 15000)))  # type: ignore[call-overload]


def accept_with(
    action: Callable[[VehicleDialog], None],
) -> Callable[[GaragePage, VehicleDialog], bool]:
    def run(_page: GaragePage, dialog: VehicleDialog) -> bool:
        action(dialog)
        return dialog.try_accept()

    return run


def test_empty_garage_offers_to_add(gui: GuiApplication) -> None:
    page = garage(gui)
    assert page.list_stack.state is ViewState.EMPTY
    assert page.list_stack.panel.action_button.isVisibleTo(page.list_stack.panel)
    assert not page.edit_button.isEnabled()


def test_add_vehicle_becomes_active_and_appears_everywhere(
    gui: GuiApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = garage(gui)
    monkeypatch.setattr(GaragePage, "_run_dialog", accept_with(fill))
    page.add_vehicle()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "Weekend Car"
    active = gui.ui.state.active_vehicle
    assert active is not None and active.name == "Weekend Car"
    assert gui.window.top_bar.vehicle_combo.currentText() == "Weekend Car"
    assert page.details_name.text().startswith("Weekend Car")
    assert any("added" in t.message_label.text() for t in gui.window.toasts.toasts())


def test_edit_vehicle(
    gui: GuiApplication, monkeypatch: pytest.MonkeyPatch, active_vehicle: Vehicle
) -> None:
    page = garage(gui)
    page.select_vehicle(active_vehicle.id)
    monkeypatch.setattr(
        GaragePage,
        "_run_dialog",
        accept_with(lambda d: d.mileage_spin.setValue(123_456)),
    )
    page.edit_selected()
    assert gui.ui.vehicles.get(active_vehicle.id).mileage_km == 123_456
    assert "123,456" in page.detail_values["odometer"].text()


def test_delete_requires_confirmation(
    gui: GuiApplication, monkeypatch: pytest.MonkeyPatch, active_vehicle: Vehicle
) -> None:
    page = garage(gui)
    page.select_vehicle(active_vehicle.id)
    monkeypatch.setattr("smartdrive.ui.dialogs.confirm.confirm", lambda *a, **k: False)
    page.delete_selected()
    assert len(gui.ui.vehicles.list_vehicles()) == 1
    monkeypatch.setattr("smartdrive.ui.dialogs.confirm.confirm", lambda *a, **k: True)
    page.delete_selected()
    assert gui.ui.vehicles.list_vehicles() == []
    assert gui.ui.state.active_vehicle is None
    assert page.list_stack.state is ViewState.EMPTY


def test_search_and_fuel_filter(gui: GuiApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    page = garage(gui)
    monkeypatch.setattr(GaragePage, "_run_dialog", accept_with(fill))
    page.add_vehicle()

    def diesel(dialog: VehicleDialog) -> None:
        fill(dialog, "Work Truck")
        dialog.fuel_combo.setCurrentIndex(dialog.fuel_combo.findData(FuelType.DIESEL))

    monkeypatch.setattr(GaragePage, "_run_dialog", accept_with(diesel))
    page.add_vehicle()
    assert page.table.rowCount() == 2
    page.fuel_filter.setCurrentIndex(page.fuel_filter.findData(FuelType.DIESEL))
    assert [page.table.item(r, 0).text() for r in range(page.table.rowCount())] == ["Work Truck"]
    page.fuel_filter.setCurrentIndex(0)
    page.search_edit.setText("weekend")
    assert page.table.rowCount() == 1
    page.search_edit.setText("no such car")
    assert page.list_stack.state is ViewState.EMPTY
    assert "No matching" in page.list_stack.panel.title_label.text()


def test_set_active_and_remove_identifiers(
    gui: GuiApplication, monkeypatch: pytest.MonkeyPatch, active_vehicle: Vehicle
) -> None:
    page = garage(gui)
    second = gui.ui.vehicles.add(
        active_vehicle.model_copy(update={"name": "Second", "vin": None})  # type: ignore[arg-type]
    )
    gui.ui.state.reload()
    page.select_vehicle(second.id)
    page.activate_selected()
    assert gui.ui.state.active_vehicle is not None
    assert gui.ui.state.active_vehicle.id == second.id
    page.select_vehicle(active_vehicle.id)
    assert page.detail_values["vin"].text().endswith(active_vehicle.vin[-4:])  # type: ignore[index]
    assert active_vehicle.vin not in page.detail_values["vin"].text()  # type: ignore[operator]
    monkeypatch.setattr("smartdrive.ui.dialogs.confirm.confirm", lambda *a, **k: True)
    page.remove_identifiers()
    assert gui.ui.vehicles.get(active_vehicle.id).vin is None
    assert page.detail_values["vin"].text() == "Not recorded"


def test_vehicle_history_lists_recorded_sessions(
    gui: GuiApplication, qtbot: QtBot, active_vehicle: Vehicle
) -> None:
    monitoring = gui.ui.monitoring
    monitoring.set_speed_factor(5.0)
    monitoring.start(record=True, vehicle_id=active_vehicle.id)
    qtbot.waitUntil(lambda: len(monitoring.buffer) >= 6, timeout=10_000)
    monitoring.stop()
    page = garage(gui)
    page.select_vehicle(active_vehicle.id)
    assert page.sessions_table.rowCount() == 1
    assert page.sessions_table.item(0, 1).text() == "Simulation"
    page.history_sensor.setCurrentIndex(page.history_sensor.findData("speed_kph"))
    x, _ = page.history_chart.curves["history"].getData()
    assert x is not None and len(x) >= 6


class TestVehicleDialog:
    def test_required_fields(self, gui: GuiApplication) -> None:
        dialog = VehicleDialog(gui.ui.vehicles)
        assert not dialog.try_accept()
        for key in ("name", "manufacturer", "model"):
            assert dialog.fields[key].has_error
        assert dialog.profile is None

    def test_invalid_vin_and_service_dates(self, gui: GuiApplication) -> None:
        dialog = VehicleDialog(gui.ui.vehicles)
        fill(dialog)
        dialog.vin_edit.setText("TOO-SHORT")
        assert not dialog.try_accept()
        assert dialog.fields["vin"].has_error
        dialog.vin_edit.setText("")
        dialog.last_service_date.set_value(date(2026, 5, 1))
        dialog.next_service_date.set_value(date(2026, 1, 1))
        assert not dialog.try_accept()
        assert "earlier" in dialog.general_error.text()
        dialog.next_service_date.set_value(None)
        assert dialog.try_accept()
        assert dialog.profile is not None
        assert dialog.profile.next_service_date is None

    def test_image_selection_and_cancel_cleanup(self, gui: GuiApplication, tmp_path: Path) -> None:
        image = QImage(64, 40, QImage.Format.Format_RGB32)
        image.fill(QColor("#06B6D4"))
        source = tmp_path / "car.png"
        assert image.save(str(source))
        dialog = VehicleDialog(gui.ui.vehicles)
        assert dialog.set_image_file(source)
        name = dialog.form_values()["image_path"]
        assert gui.ui.vehicles.resolve_image(name) is not None
        dialog.reject()
        assert gui.ui.vehicles.resolve_image(name) is None

    def test_invalid_image_is_reported(self, gui: GuiApplication, tmp_path: Path) -> None:
        bogus = tmp_path / "bogus.png"
        bogus.write_text("not an image")
        dialog = VehicleDialog(gui.ui.vehicles)
        assert not dialog.set_image_file(bogus)
        assert dialog.general_error.isVisibleTo(dialog)

    def test_editing_prefills_existing_values(
        self, gui: GuiApplication, active_vehicle: Vehicle
    ) -> None:
        dialog = VehicleDialog(gui.ui.vehicles, active_vehicle)
        assert dialog.name_edit.text() == active_vehicle.name
        assert dialog.vin_edit.text() == active_vehicle.vin
        assert dialog.try_accept()
        assert dialog.profile is not None
        assert dialog.profile.fuel_type is active_vehicle.fuel_type


def test_identifier_masking() -> None:
    assert mask_identifier(None) == "Not recorded"
    assert mask_identifier("JTDBR32E720123456") == "•" * 13 + "3456"
