"""Release scenarios A-H: the whole application, as a user would drive it, across restarts.

All telemetry is simulated or comes from the mock OBD-II adapter and is labelled as such. These
tests show that the features work together; they say nothing about real vehicles or adapters.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtWidgets import QAbstractButton, QApplication
from pytestqt.qtbot import QtBot

from smartdrive.app import bootstrap, shutdown
from smartdrive.config.constants import (
    DataSource,
    MaintenanceCategory,
    MaintenanceStatus,
    NotificationCategory,
    NotificationSeverity,
    SessionStatus,
    ThemePreference,
)
from smartdrive.database.connection import Database
from smartdrive.models.diagnostic import DiagnosticStatus
from smartdrive.models.maintenance import MaintenanceRecordInput, ScheduleInput, ScheduleState
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.obd.errors import CommunicationTimeoutError, OperationCancelledError
from smartdrive.obd.mock import PROFILES, MockElm327Transport
from smartdrive.obd.session import ConnectionParameters, ConnectionStatus, ObdSession
from smartdrive.reporting.report_templates import ReportRequest, ReportType
from smartdrive.services.report_service import CsvDataset
from smartdrive.services.scenarios import ScenarioId
from smartdrive.services.simulator import SimulationConfig
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.monitoring_controller import MonitoringState
from smartdrive.ui.pages.ai_diagnostics import AiDiagnosticsPage
from smartdrive.ui.pages.dashboard import DashboardPage
from smartdrive.ui.pages.maintenance import MaintenancePage
from smartdrive.ui.pages.reports import ReportsPage
from smartdrive.ui.pages.trip_history import TripHistoryPage
from smartdrive.ui.pages.vehicle_connection import VehicleConnectionPage
from tests.e2e.conftest import AppRunner
from tests.ui.conftest import FakeSpeech
from tests.ui.test_vehicle_integration_ui import connect_mock

pytestmark = pytest.mark.ui

TIMEOUT = 20_000


def add_vehicle(gui: GuiApplication, profile: VehicleProfile) -> int:
    vehicle = gui.ui.vehicles.add(profile)
    gui.ui.state.set_active_vehicle(vehicle.id)
    gui.ui.state.reload()
    return vehicle.id


def start_simulation(
    gui: GuiApplication,
    *,
    vehicle_id: int | None,
    record: bool = True,
    scenario: ScenarioId = ScenarioId.NORMAL,
    speed: float = 10.0,
) -> None:
    settings = gui.app_context.settings
    settings.diagnostics.inference_interval_s = 1.0
    gui.ui.diagnostics.apply_settings()
    monitoring = gui.ui.monitoring
    monitoring.configure_simulation(SimulationConfig(scenario=scenario, seed=11))
    monitoring.set_speed_factor(speed)
    monitoring.start(record=record, vehicle_id=vehicle_id)


def record_trip(gui: GuiApplication, qtbot: QtBot, vehicle_id: int, frames: int = 20) -> int:
    start_simulation(gui, vehicle_id=vehicle_id)
    monitoring = gui.ui.monitoring
    qtbot.waitUntil(lambda: len(monitoring.buffer) >= frames, timeout=TIMEOUT)
    session_id = monitoring.session_id
    assert session_id is not None
    with qtbot.waitSignal(gui.ui.trips.trip_finalized, timeout=TIMEOUT):
        monitoring.stop()
    return session_id


# --- Scenario A -------------------------------------------------------------------------------


def test_a_first_installation_and_restart(
    run_app: AppRunner, tmp_path: Path, qtbot: QtBot, vehicle_profile: VehicleProfile
) -> None:
    home = tmp_path / "fresh install folder"
    assert not home.exists()
    with run_app(home) as gui:
        paths = gui.app_context.paths
        assert paths.database_file.is_file() and paths.settings_file.is_file()
        database = gui.app_context.database
        assert database.current_revision() == database.head_revision()
        assert gui.window.current_key == "dashboard"
        assert gui.app_context.settings.general.welcome_seen is False  # guide offered once
        assert gui.app_context.settings.diagnostics.live_ml_enabled is False
        assert gui.ui.connection.status is ConnectionStatus.DISCONNECTED  # never auto-connects
        vehicle_id = add_vehicle(gui, vehicle_profile)
        gui.app_context.settings.appearance.theme = ThemePreference.LIGHT
        gui.ui.state.save_settings()
        dashboard = gui.window.pages["dashboard"]
        assert isinstance(dashboard, DashboardPage)
        session_id = record_trip(gui, qtbot, vehicle_id)
        assert gui.ui.monitoring.state is MonitoringState.STOPPED

    with run_app(home) as gui:  # restart on the same data
        active = gui.ui.state.active_vehicle
        assert active is not None and active.id == vehicle_id
        assert active.name == vehicle_profile.name
        assert gui.app_context.settings.appearance.theme is ThemePreference.LIGHT
        trip = gui.ui.trips.trips.get_trip(session_id)
        assert trip.session.data_source is DataSource.SIMULATION
        assert trip.session.status is SessionStatus.COMPLETED
        assert trip.sample_count >= 20 and trip.summary is not None


# --- Scenario B -------------------------------------------------------------------------------


def test_b_ai_diagnostic_workflow_to_report(
    run_app: AppRunner, tmp_path: Path, qtbot: QtBot, vehicle_profile: VehicleProfile
) -> None:
    with run_app(tmp_path / "home") as gui:
        vehicle_id = add_vehicle(gui, vehicle_profile)
        qtbot.waitUntil(lambda: not gui.ui.diagnostics.models_loading, timeout=TIMEOUT)
        start_simulation(gui, vehicle_id=vehicle_id, scenario=ScenarioId.OVERHEATING)
        gui.ui.monitoring.set_output_override("coolant_temp_c", 124.0)
        qtbot.waitUntil(
            lambda: (
                gui.ui.diagnostics.latest is not None
                and gui.ui.diagnostics.latest.status is DiagnosticStatus.CRITICAL
            ),
            timeout=30_000,
        )
        latest = gui.ui.diagnostics.latest
        assert latest is not None
        assert any(f.key == "rule:coolant_temperature" for f in latest.findings)
        assert latest.data_source is DataSource.SIMULATION
        view = gui.window.pages["diagnostics"]
        assert isinstance(view, AiDiagnosticsPage)
        gui.window.show_page("diagnostics")
        view.refresh_view()
        expected = "—" if latest.health.score is None else str(latest.health.score)
        assert view.health_widget.score_text() == expected
        assert latest.explanations or latest.classifier.status.value in {"abstained", "disabled"}
        with qtbot.waitSignal(gui.ui.trips.trip_finalized, timeout=TIMEOUT):
            gui.ui.monitoring.stop()

        history = gui.ui.diagnostic_history.history(vehicle_id=vehicle_id)
        assert any(entry.finding_key == "rule:coolant_temperature" for entry in history)
        target = tmp_path / "exports" / "diagnostic report.pdf"
        target.parent.mkdir()
        result = gui.ui.reports.generate_pdf(
            ReportRequest(ReportType.VEHICLE_DIAGNOSTIC, vehicle_id=vehicle_id), target
        )
        assert result.path == target and target.read_bytes().startswith(b"%PDF-")


# --- Scenario C -------------------------------------------------------------------------------


def test_c_trip_recording_history_replay_and_export(
    run_app: AppRunner,
    tmp_path: Path,
    qtbot: QtBot,
    vehicle_profile: VehicleProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with run_app(tmp_path / "home") as gui:
        vehicle_id = add_vehicle(gui, vehicle_profile)
        session_id = record_trip(gui, qtbot, vehicle_id, frames=30)
        trip = gui.ui.trips.trips.get_trip(session_id)
        assert trip.summary is not None and trip.sample_count >= 30

        page = gui.window.pages["trips"]
        assert isinstance(page, TripHistoryPage)
        gui.window.show_page("trips")
        assert page.select_trip(session_id)
        monitoring = gui.ui.monitoring
        page.replay_selected()
        qtbot.waitUntil(lambda: monitoring.data_source is DataSource.REPLAY, timeout=TIMEOUT)
        monitoring.set_replay_speed(4.0)
        qtbot.waitUntil(lambda: monitoring.buffer.latest is not None, timeout=TIMEOUT)
        monitoring.seek_replay(0.5)
        qtbot.waitUntil(lambda: monitoring.buffer.latest is not None, timeout=TIMEOUT)
        page.stop_replay()
        assert monitoring.state is MonitoringState.STOPPED
        assert len(gui.ui.trips.trips.list_trips()) == 1  # replays are never stored

        target = tmp_path / "trip export.csv"
        result = gui.ui.reports.export_csv(
            CsvDataset.TELEMETRY, target, vehicle_id=vehicle_id, session_id=session_id
        )
        rows = result.path.read_text("utf-8-sig").splitlines()
        assert len(rows) - 1 == trip.sample_count


# --- Scenario D -------------------------------------------------------------------------------


def test_d_maintenance_workflow(
    run_app: AppRunner, tmp_path: Path, qtbot: QtBot, vehicle_profile: VehicleProfile
) -> None:
    with run_app(tmp_path / "home") as gui:
        vehicle_id = add_vehicle(gui, vehicle_profile)
        maintenance = gui.ui.maintenance
        schedule = maintenance.add_schedule(
            vehicle_id,
            ScheduleInput(
                category=MaintenanceCategory.BRAKE_INSPECTION,
                task_name="Brake inspection",
                interval_days=365,
                last_done_date=date.today() - timedelta(days=400),
            ),
        )
        (status,) = maintenance.statuses(vehicle_id)
        assert status.state is ScheduleState.OVERDUE
        record = maintenance.add_record(
            vehicle_id,
            MaintenanceRecordInput(
                category=MaintenanceCategory.BRAKE_INSPECTION,
                title="Brake inspection",
                status=MaintenanceStatus.COMPLETED,
                service_date=date.today(),
                cost=Decimal("6500.00"),
                currency="LKR",
                schedule_id=schedule.id,
            ),
        )
        (status,) = maintenance.statuses(vehicle_id)
        assert status.state is ScheduleState.UP_TO_DATE
        maintenance.update_record(
            vehicle_id,
            record.id,
            MaintenanceRecordInput(
                category=MaintenanceCategory.BRAKE_INSPECTION,
                title="Brake inspection and pads",
                status=MaintenanceStatus.COMPLETED,
                service_date=date.today(),
                cost=Decimal("9500.00"),
                currency="LKR",
                schedule_id=schedule.id,
            ),
        )
        maintenance.add_record(
            vehicle_id,
            MaintenanceRecordInput(
                category=MaintenanceCategory.ENGINE_OIL,
                title="Oil change",
                status=MaintenanceStatus.COMPLETED,
                service_date=date.today(),
                cost=Decimal("40.00"),
                currency="USD",
            ),
        )
        summaries = {s.currency: s for s in maintenance.cost_summary(vehicle_id)}
        assert summaries["LKR"].total == Decimal("9500.00")  # updated, not added twice
        assert summaries["USD"].total == Decimal("40.00")  # currencies are never summed

        page = gui.window.pages["maintenance"]
        assert isinstance(page, MaintenancePage)
        gui.window.show_page("maintenance")
        target = tmp_path / "maintenance report.pdf"
        result = gui.ui.reports.generate_pdf(
            ReportRequest(ReportType.MAINTENANCE, vehicle_id=vehicle_id), target
        )
        assert result.path.read_bytes().startswith(b"%PDF-")


# --- Scenario E -------------------------------------------------------------------------------


class TimeoutAdapter(MockElm327Transport):
    """Opens like a Bluetooth serial port but never answers (the COM9 case seen on Windows)."""

    def read_until_prompt(self, timeout_s: float, cancel: threading.Event | None = None) -> str:
        if cancel is not None and cancel.wait(min(timeout_s, 0.2)):
            raise OperationCancelledError("Read cancelled")
        raise CommunicationTimeoutError("No reply from the adapter")


def test_e_without_hardware_and_after_a_failed_connection(
    run_app: AppRunner,
    tmp_path: Path,
    qtbot: QtBot,
    vehicle_profile: VehicleProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smartdrive.ui.workers.obd_worker.list_serial_ports", lambda **_: [])
    attempts: list[str] = []

    def factory(params: ConnectionParameters, **kwargs: object) -> ObdSession:
        attempts.append(params.port)
        return ObdSession(
            params,
            transport_factory=lambda _p, _b: TimeoutAdapter(PROFILES["healthy"]()),
            **kwargs,  # type: ignore[arg-type]
        )

    with run_app(tmp_path / "home", obd_session_factory=factory) as gui:
        vehicle_id = add_vehicle(gui, vehicle_profile)
        page = gui.window.pages["connection"]
        assert isinstance(page, VehicleConnectionPage)
        gui.window.show_page("connection")
        with qtbot.waitSignal(gui.ui.connection.ports_changed, timeout=TIMEOUT):
            page.refresh_ports()
        assert page.selected_port() is None
        assert attempts == []  # discovery lists ports; it never connects
        assert gui.ui.connection.status is ConnectionStatus.DISCONNECTED

        with qtbot.waitSignal(gui.ui.connection.connect_failed, timeout=TIMEOUT):
            gui.ui.connection.connect_adapter("COM9", vehicle_id=vehicle_id)
        assert attempts == ["COM9"]
        assert gui.ui.connection.last_error
        assert gui.ui.connection.status in {ConnectionStatus.FAILED, ConnectionStatus.DISCONNECTED}

        start_simulation(gui, vehicle_id=vehicle_id, record=False)  # back to simulation
        qtbot.waitUntil(lambda: len(gui.ui.monitoring.buffer) >= 5, timeout=TIMEOUT)
        assert gui.ui.monitoring.data_source is DataSource.SIMULATION
        started = time.monotonic()
        qtbot.wait(50)  # the event loop is not blocked by the failed adapter
        assert time.monotonic() - started < 1.0
        gui.ui.monitoring.stop()


# --- Scenario F -------------------------------------------------------------------------------


def test_f_notifications_deduplicate_acknowledge_and_speak(
    run_app: AppRunner,
    tmp_path: Path,
    qtbot: QtBot,
    vehicle_profile: VehicleProfile,
    fake_speech: FakeSpeech,
) -> None:
    with run_app(tmp_path / "home") as gui:
        add_vehicle(gui, vehicle_profile)
        notifications = gui.ui.notifications
        gui.app_context.settings.alerts.voice_notifications = True
        notifications.apply_settings()
        qtbot.waitUntil(lambda: notifications.voice_available is True, timeout=TIMEOUT)
        delivered: list[object] = []
        notifications.delivered.connect(delivered.append)
        for _ in range(3):
            notifications.post(
                NotificationSeverity.WARNING,
                NotificationCategory.DIAGNOSTIC,
                "Battery voltage low",
                "Simulated scenario.",
                dedup_key="e2e:battery",
                speak="Warning: battery voltage low.",
            )
        stored = [
            n for n in notifications.service.list_notifications() if n.dedup_key == "e2e:battery"
        ]
        assert len(stored) == 1 and len(delivered) == 1  # duplicates suppressed
        qtbot.waitUntil(
            lambda: fake_speech.spoken == ["Warning: battery voltage low."], timeout=TIMEOUT
        )
        notifications.acknowledge(stored[0].id)
        (after,) = [
            n for n in notifications.service.list_notifications() if n.dedup_key == "e2e:battery"
        ]
        assert after.acknowledged_at is not None and after.read_at is not None
        # Desktop notifications: enabled but no system tray offscreen, so delivery is skipped
        # without error and the in-app notification still exists.
        gui.app_context.settings.alerts.desktop_notifications = True
        notifications.apply_settings()
        notifications.post(
            NotificationSeverity.INFORMATION, NotificationCategory.APPLICATION, "Desktop path check"
        )
        assert any(
            n.title == "Desktop path check" for n in notifications.service.list_notifications()
        )


# --- Scenario G -------------------------------------------------------------------------------


def test_g_upgrading_an_older_database(
    tmp_path: Path, vehicle_profile: VehicleProfile, qapp: QApplication
) -> None:
    home = tmp_path / "older install"
    db_file = home / "data" / "smartdrive.db"
    db_file.parent.mkdir(parents=True)
    old = Database(db_file)
    old.upgrade("0002")  # the schema shipped with Phase 3
    with sqlite3.connect(db_file) as raw:
        raw.execute(
            "INSERT INTO vehicles (name, manufacturer, model, year, fuel_type, transmission,"
            " mileage_km, notes, is_active, created_at, updated_at) VALUES"
            " ('Old car','Example','Test',2015,'petrol','manual',120000,'',1,"
            "'2026-01-01 00:00:00','2026-01-01 00:00:00')"
        )
        raw.execute(
            "INSERT INTO driving_sessions (vehicle_id, data_source, started_at, ended_at,"
            " distance_estimated, notes) VALUES"
            " (1,'simulation','2026-01-02 08:00:00','2026-01-02 08:05:00',1,'')"
        )
        raw.executemany(
            "INSERT INTO telemetry_readings (session_id, timestamp, rpm, fuel_rate_estimated,"
            " extra) VALUES (1, ?, 900, 0, '{}')",
            [(f"2026-01-02 08:00:0{second}",) for second in range(2)],
        )
    old.dispose()

    ctx = bootstrap(home=home, console_logging=False)
    try:
        database = ctx.database
        assert database.current_revision() == database.head_revision() == "0003"
        backups = sorted(ctx.paths.backup_dir.glob("smartdrive-pre-upgrade-0002-*.db"))
        assert len(backups) == 1
        with sqlite3.connect(db_file) as raw:
            assert raw.execute("SELECT COUNT(*) FROM telemetry_readings").fetchone()[0] == 2
            assert raw.execute("SELECT name FROM vehicles").fetchone()[0] == "Old car"
            assert raw.execute("PRAGMA foreign_key_check").fetchall() == []
            assert raw.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert database.integrity_check()
        # The pre-upgrade copy is a valid 0002 database and can be restored.
        with sqlite3.connect(backups[0]) as raw:
            assert raw.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002"
            assert raw.execute("SELECT COUNT(*) FROM telemetry_readings").fetchone()[0] == 2
        # Restoring it brings the old data back and migrates it forward to the current schema.
        safety = database.restore(backups[0], safety_backup_dir=ctx.paths.backup_dir, keep=5)
        assert safety.is_file()
        assert database.current_revision() == "0003"
        with sqlite3.connect(db_file) as raw:
            assert raw.execute("SELECT COUNT(*) FROM telemetry_readings").fetchone()[0] == 2
            assert raw.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        shutdown(ctx)


# --- Scenario H -------------------------------------------------------------------------------


class SlowSpeech(FakeSpeech):
    def speak(self, text: str, *, voice_id: str | None, rate: int, volume: float) -> None:
        time.sleep(0.8)
        super().speak(text, voice_id=voice_id, rate=rate, volume=volume)


def test_h_shutdown_during_every_kind_of_background_work(
    qapp: QApplication,
    tmp_path: Path,
    qtbot: QtBot,
    vehicle_profile: VehicleProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from smartdrive.ui.workers.voice_worker import VoiceWorker

    speech = SlowSpeech()
    ctx = bootstrap(home=tmp_path / "home", console_logging=False)
    ctx.settings.monitoring.refresh_interval_ms = 100
    ctx.settings.alerts.desktop_notifications = False
    ctx.settings.alerts.voice_notifications = True
    gui = GuiApplication(ctx, install_excepthook=False, voice_worker=VoiceWorker(lambda: speech))
    try:
        vehicle_id = add_vehicle(gui, vehicle_profile)
        recorded = record_trip(gui, qtbot, vehicle_id, frames=10)
        qtbot.waitUntil(lambda: not gui.ui.diagnostics.models_loading, timeout=TIMEOUT)
        # Replay, inference, a running report job and speech, all at once.
        page = gui.window.pages["trips"]
        assert isinstance(page, TripHistoryPage)
        assert page.select_trip(recorded)
        page.replay_selected()
        qtbot.waitUntil(lambda: gui.ui.monitoring.data_source is DataSource.REPLAY, timeout=TIMEOUT)
        reports = gui.window.pages["reports"]
        assert isinstance(reports, ReportsPage)
        target = tmp_path / "in-flight.pdf"
        monkeypatch.setattr("smartdrive.ui.pages.reports.choose_save_path", lambda *a, **k: target)
        reports.type_combo.setCurrentIndex(reports.type_combo.findData(ReportType.VEHICLE_OVERVIEW))
        reports.generate_pdf()
        gui.ui.tasks.submit("slow job", lambda: time.sleep(0.5))
        qtbot.waitUntil(lambda: gui.ui.notifications.voice_available is True, timeout=TIMEOUT)
        gui.ui.notifications.post(
            NotificationSeverity.CRITICAL,
            NotificationCategory.DIAGNOSTIC,
            "Shutdown check",
            speak="Critical: shutdown check.",
        )
        started = time.monotonic()
        gui.shutdown()
        elapsed = time.monotonic() - started
        assert elapsed < 6.0, f"shutdown took {elapsed:.1f} s"
        assert not gui.ui.monitoring.threads_running()
        assert not gui.ui.diagnostics.thread_running()
        assert not gui.ui.connection.thread_running()
        assert not gui.ui.notifications.voice_thread_running()
        assert not gui.ui.tasks.thread_running()
        assert speech.closed
        # A report is either complete or absent: never a partial file.
        assert not target.exists() or target.read_bytes().startswith(b"%PDF-")
        assert not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob(".*.pdf*"))
        assert len(gui.ui.trips.trips.list_trips()) == 1  # the replay added nothing
    finally:
        gui.shutdown()
        shutdown(ctx)
        qapp.processEvents()


def test_h_shutdown_while_recording_closes_the_trip(
    run_app: AppRunner, tmp_path: Path, qtbot: QtBot, vehicle_profile: VehicleProfile
) -> None:
    home = tmp_path / "home"
    with run_app(home) as gui:
        vehicle_id = add_vehicle(gui, vehicle_profile)
        start_simulation(gui, vehicle_id=vehicle_id)
        qtbot.waitUntil(lambda: len(gui.ui.monitoring.buffer) >= 5, timeout=TIMEOUT)
        session_id = gui.ui.monitoring.session_id
        assert session_id is not None
    with run_app(home) as gui:
        trip = gui.ui.trips.trips.get_trip(session_id)
        assert trip.session.ended_at is not None
        assert trip.sample_count >= 5


# --- Application-wide safety checks --------------------------------------------------------


def test_no_page_offers_to_clear_codes_or_send_commands(run_app: AppRunner, tmp_path: Path) -> None:
    forbidden = ("clear code", "clear trouble", "clear dtc", "erase", "reset ecu", "send command")
    with run_app(tmp_path / "home") as gui:
        texts = []
        for page in gui.window.pages.values():
            texts += [b.text().lower() for b in page.findChildren(QAbstractButton)]
            texts += [a.text().lower() for a in page.actions()]
        assert texts
        for text in texts:
            assert not any(word in text for word in forbidden), text


def test_startup_never_touches_serial_ports(
    run_app: AppRunner, tmp_path: Path, qtbot: QtBot
) -> None:
    opened: list[str] = []

    def factory(params: ConnectionParameters, **kwargs: object) -> ObdSession:
        opened.append(params.port)
        raise AssertionError("must not connect")

    home = tmp_path / "home"
    settings_ready = bootstrap(home=home, console_logging=False)
    settings_ready.settings.obd.port = "COM9"  # a remembered port is only preselected
    settings_ready.save_settings()
    shutdown(settings_ready)
    with run_app(home, obd_session_factory=factory) as gui:
        qtbot.wait(1500)
        assert opened == []
        assert gui.ui.connection.status is ConnectionStatus.DISCONNECTED


def test_mock_adapter_is_labelled_simulated_end_to_end(
    run_app: AppRunner, tmp_path: Path, qtbot: QtBot, vehicle_profile: VehicleProfile
) -> None:
    with run_app(tmp_path / "home") as gui:
        add_vehicle(gui, vehicle_profile)
        connect_mock(gui, qtbot)
        assert gui.ui.connection.report is not None
        page = gui.window.pages["connection"]
        assert isinstance(page, VehicleConnectionPage)
        assert "data is labelled simulated" in page.method_label.text()
        assert gui.ui.connection.report.is_mock
