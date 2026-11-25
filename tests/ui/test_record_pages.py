"""Maintenance dialogs and page actions, trip exports and deletion, and the save-file helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from smartdrive.config.constants import MaintenanceCategory, MaintenanceStatus
from smartdrive.models.maintenance import MaintenanceRecordInput, ScheduleInput
from smartdrive.models.vehicle import Vehicle
from smartdrive.services.maintenance_service import EXAMPLE_INTERVALS, EXAMPLE_NOTE
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.dialogs import files
from smartdrive.ui.dialogs.maintenance_dialogs import RecordDialog, ScheduleDialog
from smartdrive.ui.pages.maintenance import MaintenancePage
from smartdrive.ui.pages.trip_history import TripHistoryPage, duration_text

pytestmark = pytest.mark.ui
TIMEOUT = 15_000


class TestDialogs:
    def test_record_dialog_validates_before_accepting(self, qtbot: QtBot) -> None:
        dialog = RecordDialog(currency="LKR", schedules=[])
        qtbot.addWidget(dialog)
        dialog.title_edit.setText("Engine oil and filter")
        dialog.cost.setText("eighteen thousand")
        dialog._try_accept()
        assert dialog.value is None and "number" in dialog.error_label.text()
        dialog.cost.setText("18,500.00")
        dialog.service_date.check.setChecked(False)
        dialog._try_accept()
        assert dialog.value is None and "service date" in dialog.error_label.text()
        dialog.service_date.check.setChecked(True)
        dialog._try_accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        value = dialog.value
        assert value is not None
        assert value.cost == Decimal("18500.00") and value.currency == "LKR"
        assert value.status is MaintenanceStatus.COMPLETED
        assert isinstance(value.category, MaintenanceCategory)

    def test_schedule_dialog_marks_example_intervals(self, qtbot: QtBot) -> None:
        dialog = ScheduleDialog()
        qtbot.addWidget(dialog)
        dialog._try_accept()
        assert dialog.value is None and dialog.error_label.text().startswith("Task:")
        dialog.task.setText("Inspection")
        dialog._try_accept()
        assert "time interval, a distance interval, or both" in dialog.error_label.text()
        dialog.task.clear()
        dialog.category.setCurrentIndex(dialog.category.findData(MaintenanceCategory.ENGINE_OIL))
        dialog.use_example()
        days, km = EXAMPLE_INTERVALS[MaintenanceCategory.ENGINE_OIL]
        assert dialog.days.value() == days and dialog.km.value() == km
        assert dialog.source_label.text() == EXAMPLE_NOTE
        assert dialog.task.text() == "Engine oil replacement"
        dialog._try_accept()
        assert dialog.value is not None and dialog.value.interval_source == "example"
        dialog.days.setValue(200)  # the user changed it: no longer the example
        dialog._try_accept()
        assert dialog.value.interval_source == "user"
        custom = ScheduleDialog()
        qtbot.addWidget(custom)
        custom.category.setCurrentIndex(custom.category.findData(MaintenanceCategory.CUSTOM))
        custom.use_example()
        assert "no example interval" in custom.error_label.text()


class FakeDialog:
    """Replaces a dialog class: returns a prepared value as if the user pressed Save."""

    value: Any = None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted


def test_maintenance_page_actions(
    gui: GuiApplication, active_vehicle: Vehicle, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = gui.window.pages["maintenance"]
    assert isinstance(page, MaintenancePage)
    module = "smartdrive.ui.pages.maintenance"
    FakeDialog.value = ScheduleInput(task_name="Battery", interval_days=365)
    monkeypatch.setattr(f"{module}.ScheduleDialog", FakeDialog)
    page.add_schedule()
    assert page.schedule_table.rowCount() == 1
    FakeDialog.value = MaintenanceRecordInput(
        title="Battery check",
        category=MaintenanceCategory.BATTERY,
        service_date=date(2026, 5, 1),
        cost=Decimal("2500"),
        currency="LKR",
    )
    monkeypatch.setattr(f"{module}.RecordDialog", FakeDialog)
    page.add_record()
    assert page.record_table.rowCount() == 1
    assert "LKR 2,500.00" in page.cost_totals.text()
    assert page.cost_chart.labels == ["2026"]
    page.cost_view.setCurrentIndex(page.cost_view.findData("by_category"))
    assert page.cost_chart.labels == ["Battery inspection"]
    page.record_table.selectRow(0)
    FakeDialog.value = FakeDialog.value.model_copy(update={"title": "Battery replaced"})
    page.edit_record()
    assert page.record_table.item(0, 1).text() == "Battery replaced"
    monkeypatch.setattr("smartdrive.ui.dialogs.confirm.confirm", lambda *a, **k: False)
    page.record_table.selectRow(0)
    page.delete_record()
    assert page.record_table.rowCount() == 1
    monkeypatch.setattr("smartdrive.ui.dialogs.confirm.confirm", lambda *a, **k: True)
    page.delete_record()
    assert page.record_stack.state.value == "empty"
    page.schedule_table.selectRow(0)
    FakeDialog.value = ScheduleInput(task_name="Battery check", interval_days=180)
    monkeypatch.setattr(f"{module}.ScheduleDialog", FakeDialog)
    page.edit_schedule()
    assert page.schedule_table.item(0, 0).text() == "Battery check"
    page.schedule_table.selectRow(0)
    page.delete_schedule()
    assert page.schedule_stack.state.value == "empty"


def test_trip_page_exports_and_deletes(
    gui: GuiApplication,
    active_vehicle: Vehicle,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitoring = gui.ui.monitoring
    monitoring.start(record=True, vehicle_id=active_vehicle.id)
    qtbot.waitUntil(lambda: monitoring.buffer.latest is not None, timeout=TIMEOUT)
    qtbot.wait(1200)
    with qtbot.waitSignal(gui.ui.trips.trip_finalized, timeout=TIMEOUT):
        monitoring.stop()
    page = gui.window.pages["trips"]
    assert isinstance(page, TripHistoryPage)
    page.reload()
    page.table.selectRow(0)
    page.chart_sensor.setCurrentIndex(1)
    assert page.facts["distance"].text() != "—"
    targets = iter([tmp_path / "trip.pdf", tmp_path / "trip.csv"])
    monkeypatch.setattr(
        "smartdrive.ui.pages.trip_history.choose_save_path", lambda *a, **k: next(targets)
    )
    page.export_pdf()
    qtbot.waitUntil(lambda: page._export_job is None, timeout=TIMEOUT)
    page.export_csv()
    qtbot.waitUntil(lambda: page._export_job is None, timeout=TIMEOUT)
    assert (tmp_path / "trip.pdf").read_bytes().startswith(b"%PDF-")
    assert (tmp_path / "trip.csv").read_text("utf-8-sig").startswith("timestamp_utc")
    monkeypatch.setattr("smartdrive.ui.dialogs.confirm.confirm", lambda *a, **k: True)
    page.delete_selected()
    assert page.list_stack.state.value == "empty"
    assert duration_text(3725) == "1:02:05" and duration_text(None) == "In progress"


def test_replay_controls_on_the_trip_page(
    gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot
) -> None:
    monitoring = gui.ui.monitoring
    monitoring.start(record=True, vehicle_id=active_vehicle.id)
    qtbot.waitUntil(lambda: monitoring.buffer.latest is not None, timeout=TIMEOUT)
    qtbot.wait(1500)
    with qtbot.waitSignal(gui.ui.trips.trip_finalized, timeout=TIMEOUT):
        monitoring.stop()
    page = gui.window.pages["trips"]
    assert isinstance(page, TripHistoryPage)
    page.reload()
    page.table.selectRow(0)
    page.speed_combo.setCurrentIndex(page.speed_combo.findData(0.5))
    page.replay_selected()
    qtbot.waitUntil(lambda: monitoring.replay_session_id is not None, timeout=TIMEOUT)
    assert monitoring.replay_speed == 0.5
    assert not page.replay_button.isEnabled()
    page.toggle_play()  # pause
    assert page.play_button.text() == "Play"
    page.toggle_play()  # resume
    page.speed_combo.setCurrentIndex(page.speed_combo.findData(4.0))
    assert monitoring.replay_speed == 4.0
    page.seek_slider.setValue(500)
    page._on_seek_released()
    qtbot.waitUntil(lambda: "/" in page.position_label.text(), timeout=TIMEOUT)
    page.stop_replay()
    assert page.replay_pill.text == "No replay"


class TestFileHelpers:
    def test_save_path_gets_the_right_suffix(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        chosen = str(tmp_path / "out" / "report")
        monkeypatch.setattr(files.QFileDialog, "getSaveFileName", lambda *a: (chosen, ""))
        result = files.choose_save_path(None, "t", tmp_path, "r.pdf", files.PDF_FILTER)
        assert result == tmp_path / "out" / "report.pdf"
        monkeypatch.setattr(files.QFileDialog, "getSaveFileName", lambda *a: ("", ""))
        assert files.choose_save_path(None, "t", tmp_path, "r.csv", files.CSV_FILTER) is None
        monkeypatch.setattr(files.QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))
        assert files.choose_directory(None, "t", tmp_path.parent) == tmp_path

    def test_default_directory_and_open(self, gui: GuiApplication, tmp_path: Path) -> None:
        settings = gui.ui.app.settings
        settings.reports.output_directory = str(tmp_path)
        assert files.default_directory(settings) == tmp_path
        settings.reports.output_directory = str(tmp_path / "gone")
        assert files.default_directory(settings) != tmp_path / "gone"
        assert files.open_path(tmp_path / "missing.pdf") is False
