"""Phase 4 pages end to end, through the *mock* OBD-II adapter (no hardware is involved).

Mock telemetry is recorded and labelled as simulated data. These tests verify the application
logic around a connection; they are not evidence of compatibility with any physical adapter.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QAbstractButton
from pytestqt.qtbot import QtBot
from sqlalchemy import func, select

from smartdrive.config.constants import (
    DataSource,
    NotificationCategory,
    NotificationSeverity,
    SessionStatus,
    Severity,
)
from smartdrive.config.settings import SettingsStore
from smartdrive.database.models import AlertRecord, DiagnosticAssessmentRecord
from smartdrive.models.maintenance import ScheduleInput
from smartdrive.models.vehicle import Vehicle
from smartdrive.obd.mock import MOCK_PORT
from smartdrive.obd.session import ConnectionStatus
from smartdrive.reporting.report_templates import ReportType
from smartdrive.services.report_service import CsvDataset
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.monitoring_controller import MonitoringState
from smartdrive.ui.pages.alerts import AlertsPage
from smartdrive.ui.pages.dashboard import DashboardPage
from smartdrive.ui.pages.diagnostic_codes import DiagnosticCodesPage
from smartdrive.ui.pages.maintenance import MaintenancePage
from smartdrive.ui.pages.reports import ReportsPage
from smartdrive.ui.pages.settings_page import SettingsPage
from smartdrive.ui.pages.trip_history import TripHistoryPage
from smartdrive.ui.pages.vehicle_connection import VehicleConnectionPage
from smartdrive.ui.widgets.status import StatusLevel
from tests.ui.conftest import FakeSpeech

pytestmark = pytest.mark.ui

TIMEOUT = 15_000


def connect_mock(gui: GuiApplication, qtbot: QtBot, profile: str = "healthy") -> None:
    settings = gui.ui.app.settings
    settings.obd.show_mock_adapter = True
    settings.obd.mock_profile = profile  # type: ignore[assignment]
    settings.obd.poll_interval_ms = 250
    page = gui.window.pages["connection"]
    assert isinstance(page, VehicleConnectionPage)
    page.refresh_ports()
    qtbot.waitUntil(lambda: page.selected_port() is not None, timeout=TIMEOUT)
    index = next(
        i for i in range(page.port_combo.count()) if page.port_combo.itemData(i).port == MOCK_PORT
    )
    page.port_combo.setCurrentIndex(index)
    page.connect_selected()
    qtbot.waitUntil(lambda: gui.ui.connection.ecu_connected, timeout=TIMEOUT)


def record_live_trip(gui: GuiApplication, qtbot: QtBot, seconds: float = 2.5) -> int:
    monitoring = gui.ui.monitoring
    monitoring.set_preferred_mode("live")
    monitoring.set_record_requested(True)
    page = gui.window.pages["connection"]
    assert isinstance(page, VehicleConnectionPage)
    qtbot.waitUntil(page.controls.start_button.isEnabled, timeout=TIMEOUT)
    page.controls.start_button.click()
    qtbot.waitUntil(lambda: monitoring.session_id is not None, timeout=TIMEOUT)
    session_id = monitoring.session_id
    assert session_id is not None
    qtbot.waitUntil(lambda: monitoring.buffer.latest is not None, timeout=TIMEOUT)
    qtbot.wait(round(seconds * 1000))
    with qtbot.waitSignal(gui.ui.trips.trip_finalized, timeout=TIMEOUT):
        page.controls.start_button.click()  # stop
    return session_id


def test_no_adapter_state_shows_guidance_not_readings(gui: GuiApplication) -> None:
    page = gui.window.pages["connection"]
    assert isinstance(page, VehicleConnectionPage)
    gui.window.show_page("connection")
    assert gui.ui.connection.status is ConnectionStatus.DISCONNECTED
    assert page.sensor_stack.currentWidget() is page.sensor_stack.panel
    assert page.facts["adapter"].text() == "—"
    assert not page.disconnect_button.isEnabled()
    # Live monitoring cannot start without an ECU connection.
    gui.ui.monitoring.set_preferred_mode("live")
    assert not page.controls.start_button.isEnabled()


def test_mock_connection_capabilities_and_labels(
    gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot
) -> None:
    connect_mock(gui, qtbot, "partial_sensors")
    page = gui.window.pages["connection"]
    assert isinstance(page, VehicleConnectionPage)
    connection = gui.ui.connection
    assert connection.is_mock
    assert connection.data_source is DataSource.SIMULATION  # never labelled as live
    assert "Mock" in page.facts["source"].text()
    assert page.ecu_pill.text.endswith("connected")
    report = connection.report
    assert report is not None and report.capabilities is not None
    assert "oil_pressure_kpa" in connection.unavailable_sensors
    rows = {
        page.sensor_table.item(r, 0).text(): page.sensor_table.item(r, 3).text()
        for r in range(page.sensor_table.rowCount())
    }
    assert "Not supported" in rows.values()
    assert any("Not defined in generic OBD-II" in v for v in rows.values())
    # Disconnect returns to a clean state.
    connection.disconnect_adapter()
    qtbot.waitUntil(lambda: connection.report is None, timeout=TIMEOUT)
    qtbot.waitUntil(lambda: connection.status is ConnectionStatus.DISCONNECTED, timeout=TIMEOUT)


def test_live_trip_recording_summary_history_and_replay(
    gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot
) -> None:
    connect_mock(gui, qtbot)
    session_id = record_live_trip(gui, qtbot)
    trip = gui.ui.trips.trips.get_trip(session_id)
    assert trip.session.data_source is DataSource.SIMULATION  # mock data, labelled simulated
    assert trip.session.scenario == "mock-obd-adapter"
    assert trip.session.name and trip.session.name.startswith("Trip ")
    assert trip.summary is not None and trip.sample_count > 0

    trips_page = gui.window.pages["trips"]
    assert isinstance(trips_page, TripHistoryPage)
    gui.window.show_page("trips")
    assert trips_page.select_trip(session_id)
    assert trips_page.facts["samples"].text().startswith(str(trip.sample_count))
    assert "mock OBD-II adapter" in trips_page.facts["source"].text()

    with gui.ui.app.database.session() as s:
        assessments_before = s.scalar(select(func.count()).select_from(DiagnosticAssessmentRecord))
    monitoring = gui.ui.monitoring
    gui.ui.app.settings.diagnostics.inference_interval_s = 1.0
    gui.ui.diagnostics.apply_settings()
    trips_page.replay_selected()
    qtbot.waitUntil(lambda: monitoring.data_source is DataSource.REPLAY, timeout=TIMEOUT)
    assert monitoring.replay_session_id == session_id
    assert "Replaying trip" in trips_page.replay_pill.text
    assert gui.ui.connection.streaming is False  # replay never polls the adapter
    monitoring.set_replay_speed(4.0)
    qtbot.waitUntil(lambda: monitoring.buffer.latest is not None, timeout=TIMEOUT)
    first = monitoring.buffer.latest
    assert first is not None and first.timestamp >= trip.session.started_at
    monitoring.seek_replay(0.0)
    assert monitoring.buffer.latest is None  # the window restarts after a seek
    qtbot.waitUntil(lambda: monitoring.replay_finished, timeout=TIMEOUT)
    assert monitoring.state is MonitoringState.PAUSED
    trips_page.stop_replay()
    assert monitoring.state is MonitoringState.STOPPED
    with gui.ui.app.database.session() as s:
        after = s.scalar(select(func.count()).select_from(DiagnosticAssessmentRecord))
    assert after == assessments_before  # replays write no diagnostic history
    assert len(gui.ui.trips.trips.list_trips()) == 1  # and no new trip


def test_connection_failure_interrupts_the_recording(
    gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot
) -> None:
    connect_mock(gui, qtbot)
    monitoring = gui.ui.monitoring
    monitoring.set_preferred_mode("live")
    monitoring.set_record_requested(True)
    page = gui.window.pages["connection"]
    assert isinstance(page, VehicleConnectionPage)
    page.controls.start_button.click()
    qtbot.waitUntil(lambda: monitoring.buffer.latest is not None, timeout=TIMEOUT)
    session_id = monitoring.session_id
    assert session_id is not None
    with qtbot.waitSignal(gui.ui.trips.trip_finalized, timeout=TIMEOUT):
        gui.ui.connection.link_failed.emit("The adapter stopped responding.")
    assert not monitoring.is_active
    trip = gui.ui.trips.trips.get_trip(session_id)
    assert trip.session.status is SessionStatus.INTERRUPTED
    titles = [n.title for n in gui.ui.notifications.service.list_notifications()]
    assert "Vehicle connection closed" in titles


def test_trouble_code_scan_is_read_only_and_persisted(
    gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot
) -> None:
    connect_mock(gui, qtbot, "stored_codes")
    page = gui.window.pages["codes"]
    assert isinstance(page, DiagnosticCodesPage)
    gui.window.show_page("codes")
    assert page.scan_button.isEnabled()
    with qtbot.waitSignal(gui.ui.connection.scan_completed, timeout=TIMEOUT):
        page.scan()
    codes = {page.code_table.item(r, 0).text() for r in range(page.code_table.rowCount())}
    assert {"P0301", "P0171", "P0420"} <= codes
    assert "stored" in page.scan_summary.text() and "Mock adapter" in page.scan_summary.text()
    page.code_table.selectRow(0)
    assert page.details["steps"].text() != "—"
    assert "Mock adapter" in page.details["provenance"].text()
    page.search_edit.setText("P0420")
    assert page.code_table.rowCount() == 1
    # Nothing on the page offers to clear codes.
    labels = [b.text().lower() for b in page.findChildren(QAbstractButton)]
    assert not any("clear" in text and "code" in text for text in labels)
    dashboard = gui.window.pages["dashboard"]
    assert isinstance(dashboard, DashboardPage)
    assert "2 stored · 1 pending" in dashboard.records_card.values["codes"].text()


def test_maintenance_page_schedules_odometer_and_costs(
    gui: GuiApplication, active_vehicle: Vehicle
) -> None:
    page = gui.window.pages["maintenance"]
    assert isinstance(page, MaintenancePage)
    gui.ui.maintenance.add_schedule(
        active_vehicle.id,
        ScheduleInput(task_name="Engine oil", interval_km=10_000, last_done_mileage_km=40_000),
    )
    page.reload()
    texts = [page.attention_list.item(i).text() for i in range(page.attention_list.count())]
    assert any("Insufficient mileage" in t for t in texts)  # no dated odometer reading yet
    page.odometer_spin.setValue(49_900)
    page.record_odometer()
    assert "49,900 km" in page.odometer_pill.text
    upcoming = [page.upcoming_list.item(i).text() for i in range(page.upcoming_list.count())]
    attention = [page.attention_list.item(i).text() for i in range(page.attention_list.count())]
    assert any("Engine oil" in t for t in upcoming + attention)
    assert page.schedule_table.rowCount() == 1
    assert "No completed services with a cost" in page.cost_totals.text()


def test_reports_centre_generates_real_files_and_reports_failures(
    gui: GuiApplication,
    active_vehicle: Vehicle,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = gui.window.pages["reports"]
    assert isinstance(page, ReportsPage)
    gui.window.show_page("reports")
    target = tmp_path / "overview.pdf"
    monkeypatch.setattr("smartdrive.ui.pages.reports.choose_save_path", lambda *a, **k: target)
    page.type_combo.setCurrentIndex(page.type_combo.findData(ReportType.VEHICLE_OVERVIEW))
    assert page.pdf_button.isEnabled()
    page.generate_pdf()
    assert page.progress.isVisible()
    qtbot.waitUntil(lambda: page.last_result is not None, timeout=TIMEOUT)
    assert target.read_bytes().startswith(b"%PDF-")
    assert page.result_pill.text.startswith("Saved overview.pdf")
    assert page.history_table.rowCount() == 1
    assert any(n.title == "Report ready" for n in gui.ui.notifications.service.list_notifications())

    csv_target = tmp_path / "trips.csv"
    monkeypatch.setattr("smartdrive.ui.pages.reports.choose_save_path", lambda *a, **k: csv_target)
    page.csv_combo.setCurrentIndex(page.csv_combo.findData(CsvDataset.TRIPS))
    page.export_csv()
    qtbot.waitUntil(lambda: csv_target.exists() and page._job is None, timeout=TIMEOUT)

    missing = tmp_path / "no-such-folder" / "x.pdf"
    monkeypatch.setattr("smartdrive.ui.pages.reports.choose_save_path", lambda *a, **k: missing)
    page.generate_pdf()
    qtbot.waitUntil(lambda: page.result_pill.text == "Not generated", timeout=TIMEOUT)
    assert "folder does not exist" in page.result_text.text()
    assert not missing.exists()


def test_alert_centre_acknowledgement_does_not_resolve_conditions(
    gui: GuiApplication, active_vehicle: Vehicle
) -> None:
    with gui.ui.app.database.session() as s:
        alert = AlertRecord(
            vehicle_id=active_vehicle.id,
            severity=Severity.CRITICAL,
            category="cooling",
            title="Coolant temperature critically high",
            message="",
            dedup_key=f"v{active_vehicle.id}:rule:coolant_high",
            occurrence_count=3,
        )
        s.add(alert)
        s.flush()
        alert_id = alert.id
    gui.ui.notifications.post(
        NotificationSeverity.CRITICAL,
        NotificationCategory.DIAGNOSTIC,
        "Coolant temperature critically high",
        alert_id=alert_id,
    )
    page = gui.window.pages["alerts"]
    assert isinstance(page, AlertsPage)
    gui.window.show_page("alerts")
    assert "1 unread" in page.unread_pill.text
    assert "(1)" in gui.window.sidebar.buttons["alerts"].text()
    page.n_table.selectRow(0)
    page.acknowledge()
    assert page.unread_pill.level is StatusLevel.NORMAL
    page.tabs.setCurrentIndex(1)
    page.a_table.selectRow(0)
    (stored,) = gui.ui.notifications.service.alerts()
    assert stored.acknowledged_at is not None and stored.resolved_at is None
    assert "still active" in page.a_table.item(0, 6).text()
    assert "still active" in page.a_detail.text()


def test_voice_announcements_use_the_queue_and_respect_settings(
    gui: GuiApplication, qtbot: QtBot, fake_speech: FakeSpeech
) -> None:
    notifications = gui.ui.notifications
    qtbot.waitUntil(lambda: notifications.voice_available is True, timeout=TIMEOUT)
    notifications.post(
        NotificationSeverity.CRITICAL,
        NotificationCategory.DIAGNOSTIC,
        "Coolant critical",
        speak="Critical: coolant.",
    )
    qtbot.wait(100)
    assert fake_speech.spoken == []  # voice is off by default
    settings = gui.window.pages["settings"]
    assert isinstance(settings, SettingsPage)
    settings.voice_check.setChecked(True)
    assert gui.ui.app.settings.alerts.voice_notifications
    notifications.post(
        NotificationSeverity.CRITICAL,
        NotificationCategory.DIAGNOSTIC,
        "Battery critical",
        speak="Critical: battery.",
    )
    qtbot.waitUntil(lambda: fake_speech.spoken == ["Critical: battery."], timeout=TIMEOUT)
    # The same notification again within the cooldown is neither stored anew nor spoken.
    notifications.post(
        NotificationSeverity.CRITICAL,
        NotificationCategory.DIAGNOSTIC,
        "Battery critical",
        speak="Critical: battery.",
    )
    qtbot.wait(100)
    assert fake_speech.spoken == ["Critical: battery."]
    settings.test_voice_button.click()
    qtbot.waitUntil(lambda: len(fake_speech.spoken) == 2, timeout=TIMEOUT)


def test_phase_4_settings_validate_and_persist(gui: GuiApplication) -> None:
    page = gui.window.pages["settings"]
    assert isinstance(page, SettingsPage)
    page.poll_spin.setValue(500)
    page.reconnect_spin.setValue(2)
    page.live_ml_check.setChecked(True)
    page.desktop_check.setChecked(False)
    page.voice_rate_spin.setValue(150)
    page.trip_prefix_edit.setText("Drive")
    page.trip_prefix_edit.editingFinished.emit()
    page.currency_edit.setCurrentText("USD")
    page.currency_edit.activated.emit(0)
    stored = SettingsStore(gui.ui.app.paths.settings_file).load()
    assert stored.obd.poll_interval_ms == 500
    assert stored.obd.max_reconnect_attempts == 2
    assert stored.diagnostics.live_ml_enabled
    assert not stored.alerts.desktop_notifications
    assert stored.alerts.voice_rate == 150
    assert stored.trips.name_prefix == "Drive"
    assert stored.maintenance.currency in ("USD", "LKR")
    assert stored.obd.port is None  # never chosen automatically


def test_theme_switch_covers_the_new_pages(gui: GuiApplication) -> None:
    for theme in ("light", "dark"):
        gui.ui.theme.set_preference(theme)  # type: ignore[arg-type]
        for key in ("connection", "codes", "trips", "maintenance", "reports", "alerts"):
            gui.window.show_page(key)
    assert gui.window.current_key == "alerts"


def test_shutdown_while_everything_is_running(
    gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot, fake_speech: FakeSpeech
) -> None:
    connect_mock(gui, qtbot)
    gui.ui.app.settings.alerts.voice_notifications = True
    gui.ui.notifications.apply_settings()
    monitoring = gui.ui.monitoring
    monitoring.set_preferred_mode("live")
    monitoring.set_record_requested(True)
    monitoring.start_live(gui.ui.connection, record=True, vehicle_id=active_vehicle.id)
    qtbot.waitUntil(lambda: monitoring.buffer.latest is not None, timeout=TIMEOUT)
    session_id = monitoring.session_id
    gui.ui.tasks.submit("slow job", lambda: time.sleep(0.3))
    gui.ui.notifications.post(
        NotificationSeverity.WARNING,
        NotificationCategory.DIAGNOSTIC,
        "Something to say",
        speak="Warning: something.",
    )
    gui.shutdown()
    assert not monitoring.threads_running()
    assert not gui.ui.connection.thread_running()
    assert not gui.ui.notifications.voice_thread_running()
    assert not gui.ui.tasks.thread_running()
    assert fake_speech.closed
    assert session_id is not None
    trip = gui.ui.trips.trips.get_trip(session_id)
    assert trip.session.ended_at is not None  # the recording was closed, not left open


def test_selectors_return_real_values_through_qt(
    gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot
) -> None:
    """Qt hands StrEnum item data back as plain str; every selector must convert it back."""
    page = gui.window.pages["connection"]
    assert isinstance(page, VehicleConnectionPage)
    combo = page.controls.source_combo
    combo.setCurrentIndex(combo.findData(DataSource.LIVE))
    assert gui.ui.monitoring.preferred_mode == "live"
    combo.setCurrentIndex(combo.findData(DataSource.SIMULATION))
    assert gui.ui.monitoring.preferred_mode == "simulation"

    reports = gui.window.pages["reports"]
    assert isinstance(reports, ReportsPage)
    reports.type_combo.setCurrentIndex(reports.type_combo.findData(ReportType.TRIP))
    assert reports.report_type is ReportType.TRIP
    assert reports.trip_combo.isEnabled()
    assert not reports.pdf_button.isEnabled()  # no recorded trip to report on yet

    gui.ui.monitoring.start(record=True, vehicle_id=active_vehicle.id)
    qtbot.waitUntil(lambda: gui.ui.monitoring.buffer.latest is not None, timeout=TIMEOUT)
    with qtbot.waitSignal(gui.ui.trips.trip_finalized, timeout=TIMEOUT):
        gui.ui.monitoring.stop()
    trips = gui.window.pages["trips"]
    assert isinstance(trips, TripHistoryPage)
    trips.reload()
    assert trips.table.rowCount() == 1
    trips.severity_filter.setCurrentIndex(trips.severity_filter.findData(Severity.CRITICAL))
    assert trips.list_stack.state.value == "empty"
    trips.severity_filter.setCurrentIndex(0)
    trips.source_filter.setCurrentIndex(trips.source_filter.findData(DataSource.LIVE))
    assert trips.list_stack.state.value == "empty"
    trips.source_filter.setCurrentIndex(trips.source_filter.findData(DataSource.SIMULATION))
    assert trips.list_stack.state.value == "content"
