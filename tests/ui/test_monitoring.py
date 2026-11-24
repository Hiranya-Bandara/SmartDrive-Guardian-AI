"""Background monitoring workers, controller state, persistence and the monitoring pages."""

from __future__ import annotations

from datetime import timedelta

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from pytestqt.qtbot import QtBot
from sqlalchemy import func, select

from smartdrive.config.constants import DataSource
from smartdrive.config.settings import AppSettings
from smartdrive.core.units import MISSING_TEXT
from smartdrive.database.models import TelemetryReadingRecord
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.models.vehicle import Vehicle
from smartdrive.services.data_source import TelemetryFrame
from smartdrive.services.scenarios import ScenarioId
from smartdrive.services.simulator import SimulationConfig
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.monitoring_controller import (
    ConnectionState,
    MonitoringController,
    MonitoringState,
    buffer_capacity,
)
from smartdrive.ui.pages.dashboard import DashboardPage
from smartdrive.ui.pages.live_monitoring import LiveMonitoringPage
from smartdrive.ui.pages.simulation_lab import SimulationLabPage
from smartdrive.ui.workers.persistence_worker import PersistenceWorker
from tests.conftest import make_samples

pytestmark = pytest.mark.ui


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_frames(qtbot: QtBot, controller: MonitoringController, count: int = 3) -> None:
    qtbot.waitUntil(lambda: len(controller.buffer) >= count, timeout=10_000)


class TestController:
    def test_start_receives_frames_on_gui_thread(self, gui: GuiApplication, qtbot: QtBot) -> None:
        monitoring = gui.ui.monitoring
        received: list[object] = []
        monitoring.frame_received.connect(received.append)
        monitoring.start()
        assert monitoring.state is MonitoringState.RUNNING
        assert monitoring.data_source is DataSource.SIMULATION
        wait_frames(qtbot, monitoring)
        assert all(isinstance(f, TelemetryFrame) for f in received)
        assert monitoring.connection is ConnectionState.CONNECTED
        assert gui.window.top_bar.connection_indicator.text == "Receiving data"
        assert gui.window.top_bar.mode_indicator.text == "Mode: Simulation"
        monitoring.stop()
        assert not monitoring.threads_running()
        assert gui.window.top_bar.mode_indicator.text == "Mode: Stopped"

    def test_pause_and_resume(self, gui: GuiApplication, qtbot: QtBot) -> None:
        monitoring = gui.ui.monitoring
        monitoring.start()
        wait_frames(qtbot, monitoring)
        monitoring.pause()
        assert monitoring.state is MonitoringState.PAUSED
        pump(150)
        paused_at = len(monitoring.buffer)
        pump(400)
        assert len(monitoring.buffer) == paused_at
        monitoring.resume()
        qtbot.waitUntil(lambda: len(monitoring.buffer) > paused_at, timeout=5000)
        monitoring.stop()

    def test_cancellation_before_first_frame(self, gui: GuiApplication) -> None:
        monitoring = gui.ui.monitoring
        for _ in range(5):
            monitoring.start()
            monitoring.stop()
        assert not monitoring.threads_running()
        assert monitoring.state is MonitoringState.STOPPED

    def test_buffer_is_bounded_by_history_setting(self, gui: GuiApplication) -> None:
        monitoring = gui.ui.monitoring
        history = gui.app_context.settings.monitoring.chart_history_seconds
        assert monitoring.buffer.capacity == buffer_capacity(history)
        assert buffer_capacity(10**6) == 36_000

    def test_recording_requires_a_vehicle(self, gui: GuiApplication, qtbot: QtBot) -> None:
        with qtbot.waitSignal(gui.ui.monitoring.error_occurred, timeout=2000):
            gui.ui.monitoring.start(record=True, vehicle_id=None)
        assert not gui.ui.monitoring.is_active

    def test_recorded_session_is_persisted_in_background(
        self, gui: GuiApplication, qtbot: QtBot, active_vehicle: Vehicle
    ) -> None:
        monitoring = gui.ui.monitoring
        monitoring.set_speed_factor(5.0)
        monitoring.start(record=True, vehicle_id=active_vehicle.id)
        assert monitoring.session_id is not None
        wait_frames(qtbot, monitoring, 8)
        monitoring.stop()
        assert monitoring.persisted_count >= 8
        (summary,) = gui.ui.telemetry.session_summaries(active_vehicle.id)
        assert summary.sample_count == monitoring.persisted_count
        assert summary.session.ended_at is not None
        assert summary.session.scenario == ScenarioId.NORMAL.value
        assert summary.session.random_seed == monitoring.simulation_config.seed

    def test_overrides_and_speed_reach_the_worker(self, gui: GuiApplication, qtbot: QtBot) -> None:
        monitoring = gui.ui.monitoring
        monitoring.start()
        wait_frames(qtbot, monitoring)
        monitoring.set_output_override("coolant_temp_c", 123.0)
        monitoring.set_speed_factor(10.0)
        qtbot.waitUntil(
            lambda: (
                monitoring.buffer.latest is not None
                and monitoring.buffer.latest.coolant_temp_c == 123.0
            ),
            timeout=5000,
        )
        frame = monitoring.last_frame
        assert frame is not None and frame.labels is not None
        assert "coolant_temp_c" in frame.labels.overridden_sensors
        with pytest.raises(ValueError):
            monitoring.set_output_override("rpm", -10.0)
        monitoring.stop()

    def test_reconfigure_restarts_timeline(self, gui: GuiApplication, qtbot: QtBot) -> None:
        monitoring = gui.ui.monitoring
        monitoring.set_speed_factor(10.0)
        monitoring.start()
        qtbot.waitUntil(lambda: (monitoring.buffer.last_elapsed or 0) > 5, timeout=5000)
        monitoring.configure_simulation(SimulationConfig(scenario=ScenarioId.IDLE, seed=9))
        qtbot.waitUntil(
            lambda: (
                monitoring.last_frame is not None
                and monitoring.last_frame.labels is not None
                and monitoring.last_frame.labels.scenario is ScenarioId.IDLE
            ),
            timeout=5000,
        )
        assert (monitoring.buffer.last_elapsed or 0) < 5
        monitoring.stop()

    def test_connection_loss_is_reported(self, gui: GuiApplication, qtbot: QtBot) -> None:
        monitoring = gui.ui.monitoring
        monitoring.configure_simulation(
            SimulationConfig(scenario=ScenarioId.CONNECTION_LOSS, seed=7)
        )
        monitoring.set_speed_factor(20.0)
        monitoring.start()
        qtbot.waitUntil(lambda: monitoring.frames_without_response > 0, timeout=20_000)
        monitoring.stop()

    def test_worker_command_failure_is_reported_without_crashing(
        self, gui: GuiApplication, qtbot: QtBot
    ) -> None:
        monitoring = gui.ui.monitoring
        monitoring.start()
        wait_frames(qtbot, monitoring)

        def explode(_source: object) -> None:
            raise RuntimeError("boom")

        with qtbot.waitSignal(monitoring.error_occurred, timeout=3000):
            monitoring._run_on_source(explode)
        count = len(monitoring.buffer)
        qtbot.waitUntil(lambda: len(monitoring.buffer) > count, timeout=5000)
        monitoring.stop()


def test_staleness_detection_with_controlled_clock(gui: GuiApplication, qtbot: QtBot) -> None:
    now = [1000.0]
    settings = AppSettings()
    settings.monitoring.refresh_interval_ms = 100
    controller = MonitoringController(settings, gui.ui.telemetry, clock=lambda: now[0])
    controller.start()
    qtbot.waitUntil(lambda: controller.connection is ConnectionState.CONNECTED, timeout=5000)
    controller._check_staleness()
    assert controller.connection is ConnectionState.CONNECTED
    now[0] += controller.stale_threshold_s + 1
    controller._check_staleness()
    assert controller.connection is ConnectionState.STALE
    controller.stop()
    assert controller.connection is ConnectionState.IDLE


class TestPersistenceWorker:
    def _session(self, telemetry: TelemetryService, vehicle: Vehicle) -> int:
        return telemetry.start_session(vehicle.id, DataSource.SIMULATION).id

    def test_batches_and_flushes_on_stop(
        self, gui: GuiApplication, active_vehicle: Vehicle
    ) -> None:
        telemetry = gui.ui.telemetry
        session_id = self._session(telemetry, active_vehicle)
        worker = PersistenceWorker(telemetry, session_id, batch_size=10)
        persisted: list[int] = []
        worker.persisted.connect(persisted.append)
        start = telemetry.session_summaries(active_vehicle.id)[0].session.started_at
        for sample in make_samples(25, start=start):
            worker.enqueue(sample)
        assert persisted == [10, 20]
        worker.stop()
        assert worker.total_persisted == 25
        with gui.app_context.database.session() as session:
            count = session.scalar(select(func.count(TelemetryReadingRecord.id)))
        assert count == 25

    def test_bounded_queue_drops_oldest(self, gui: GuiApplication, active_vehicle: Vehicle) -> None:
        telemetry = gui.ui.telemetry
        worker = PersistenceWorker(
            telemetry, self._session(telemetry, active_vehicle), batch_size=1000, max_pending=5
        )
        for sample in make_samples(8):
            worker.enqueue(sample)
        assert worker.total_dropped == 3

    def test_write_failure_is_reported_once(
        self, gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot
    ) -> None:
        telemetry = gui.ui.telemetry
        session_id = self._session(telemetry, active_vehicle)
        telemetry.end_session(session_id)
        worker = PersistenceWorker(telemetry, session_id)
        worker.enqueue(make_samples(1)[0])
        with qtbot.waitSignal(worker.failed, timeout=1000):
            worker.flush()
        worker.enqueue(make_samples(1)[0])
        worker.flush()
        assert worker.total_persisted == 0


class TestMonitoringPages:
    def test_dashboard_shows_live_values_then_dashes(
        self, gui: GuiApplication, qtbot: QtBot
    ) -> None:
        page = gui.window.pages["dashboard"]
        assert isinstance(page, DashboardPage)
        assert page.speed_value.text() == MISSING_TEXT
        assert page.coolant_gauge.value is None
        gui.ui.monitoring.start()
        assert page.banner.isVisibleTo(page)
        qtbot.waitUntil(lambda: page.coolant_gauge.value is not None, timeout=5000)
        assert page.speed_value.text() != MISSING_TEXT
        gui.ui.monitoring.stop()
        assert page.coolant_gauge.value is None
        assert page.speed_value.text() == MISSING_TEXT
        assert not page.banner.isVisibleTo(page)

    def test_live_page_selection_statistics_and_missing_sensors(
        self, gui: GuiApplication, qtbot: QtBot
    ) -> None:
        gui.window.show_page("monitoring")
        page = gui.window.pages["monitoring"]
        assert isinstance(page, LiveMonitoringPage)
        page.set_selected(["rpm", "oil_pressure_kpa"])
        assert page.charts["rpm"].isVisibleTo(page)
        assert not page.charts["speed_kph"].isVisibleTo(page)
        page.set_selected([])
        assert page.empty_selection.isVisibleTo(page)
        page.set_selected(["rpm", "oil_pressure_kpa"])

        gui.ui.monitoring.configure_simulation(
            SimulationConfig(scenario=ScenarioId.MISSING_SENSORS, seed=1)
        )
        gui.ui.monitoring.start()
        wait_frames(qtbot, gui.ui.monitoring, 5)
        page.render_now()
        rows = {page.table.item(r, 0).text(): r for r in range(page.table.rowCount())}
        oil = rows["Engine oil pressure"]
        assert page.table.item(oil, 1).text() == MISSING_TEXT
        assert page.table.item(oil, 6).text() == "Not supported"
        assert page.table.item(rows["Engine speed"], 6).text() in {"OK", "Missing"}
        rpm_curve = page.charts["rpm"].curves["rpm"]
        assert len(rpm_curve.getData()[0]) > 0
        gui.ui.monitoring.stop()
        page.render_now()
        assert page.table.item(rows["Engine speed"], 6).text() == "Stopped"
        assert page.table.item(rows["Engine speed"], 1).text() == MISSING_TEXT

    def test_live_page_refresh_interval_is_applied_and_saved(self, gui: GuiApplication) -> None:
        page = gui.window.pages["monitoring"]
        assert isinstance(page, LiveMonitoringPage)
        page.refresh_combo.setCurrentIndex(page.refresh_combo.findData(500))
        assert gui.ui.monitoring.interval_ms == 500
        store = gui.app_context.settings_store
        assert store.load().monitoring.refresh_interval_ms == 500

    def test_time_range_options_respect_history(self, gui: GuiApplication) -> None:
        page = gui.window.pages["monitoring"]
        assert isinstance(page, LiveMonitoringPage)
        history = gui.app_context.settings.monitoring.chart_history_seconds
        options = [page.range_combo.itemData(i) for i in range(page.range_combo.count())]
        assert max(options) == history


class TestSimulationLab:
    def _page(self, gui: GuiApplication) -> SimulationLabPage:
        gui.window.show_page("simulation")
        page = gui.window.pages["simulation"]
        assert isinstance(page, SimulationLabPage)
        return page

    def test_apply_selected_scenario(self, gui: GuiApplication) -> None:
        page = self._page(gui)
        page.scenario_combo.setCurrentIndex(page.scenario_combo.findData(ScenarioId.LUBRICATION))
        page.seed_spin.setValue(1234)
        page.noise_slider.setValue(50)
        page.development_check.setChecked(True)
        page.development_spin.setValue(60)
        page.apply_scenario()
        config = gui.ui.monitoring.simulation_config
        assert config == SimulationConfig(
            scenario=ScenarioId.LUBRICATION,
            seed=1234,
            noise_scale=0.5,
            fault_development_s=60.0,
        )
        assert "Oil pressure" in page.description_label.text()

    def test_form_reflects_configuration_changed_elsewhere(self, gui: GuiApplication) -> None:
        page = self._page(gui)
        gui.ui.monitoring.configure_simulation(SimulationConfig(scenario=ScenarioId.IDLE, seed=5))
        gui.ui.monitoring.set_speed_factor(5.0)
        assert page.build_config().scenario is ScenarioId.IDLE
        assert page.seed_spin.value() == 5
        assert page.speed_combo.currentData() == 5.0

    def test_ground_truth_and_manual_override(self, gui: GuiApplication, qtbot: QtBot) -> None:
        page = self._page(gui)
        gui.ui.monitoring.configure_simulation(
            SimulationConfig(scenario=ScenarioId.OVERHEATING, seed=2, fault_development_s=0)
        )
        gui.ui.monitoring.set_speed_factor(20.0)
        row = page.override_rows[0]
        row.check.setChecked(True)
        assert "coolant_temp_c" in gui.ui.monitoring.output_overrides
        gui.ui.monitoring.start()
        qtbot.waitUntil(lambda: (gui.ui.monitoring.buffer.last_elapsed or 0) > 35, timeout=10_000)
        page._render()
        assert page.fault_rows
        assert "overridden" in page.overridden_label.text().lower()
        row.check.setChecked(False)
        assert "coolant_temp_c" not in gui.ui.monitoring.output_overrides
        page.driver_check.setChecked(True)
        assert gui.ui.monitoring.target_speed == float(page.target_slider.value())
        gui.ui.monitoring.stop()
        page._render()
        assert page.elapsed_label.text() == "Not running"


def test_missing_values_never_displayed_as_zero(gui: GuiApplication, qtbot: QtBot) -> None:
    sample = TelemetrySample(timestamp=make_samples(1)[0].timestamp + timedelta(seconds=1))
    assert sample.available_sensors() == []
    dashboard = gui.window.pages["dashboard"]
    assert isinstance(dashboard, DashboardPage)
    dashboard.voltage_card.set_value(None)
    assert dashboard.voltage_card.value_label.text() == MISSING_TEXT
