"""AI Diagnostics page, dashboard integration and the background inference controller."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from smartdrive.ai.model_registry import ANOMALY_NAME, CLASSIFIER_NAME, LoadStatus, ModelRegistry
from smartdrive.app import bootstrap, shutdown
from smartdrive.models.diagnostic import DiagnosticStatus, ModelRunStatus
from smartdrive.models.vehicle import Vehicle
from smartdrive.services.scenarios import ScenarioId
from smartdrive.services.simulator import SimulationConfig
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.main_window import PAGES, UPCOMING
from smartdrive.ui.pages.ai_diagnostics import AiDiagnosticsPage
from smartdrive.ui.pages.dashboard import DashboardPage
from smartdrive.ui.pages.settings_page import SettingsPage
from smartdrive.ui.widgets.diagnostic_card import FindingCard
from smartdrive.ui.widgets.states import ViewState

pytestmark = pytest.mark.ui


def page(gui: GuiApplication) -> AiDiagnosticsPage:
    gui.window.show_page("diagnostics")
    result = gui.window.pages["diagnostics"]
    assert isinstance(result, AiDiagnosticsPage)
    return result


def wait_models(gui: GuiApplication, qtbot: QtBot) -> None:
    qtbot.waitUntil(lambda: not gui.ui.diagnostics.models_loading, timeout=20_000)


def start_fast(
    gui: GuiApplication,
    *,
    record: bool = False,
    vehicle: Vehicle | None = None,
    scenario: ScenarioId = ScenarioId.NORMAL,
) -> None:
    settings = gui.app_context.settings
    settings.monitoring.refresh_interval_ms = 100
    settings.diagnostics.inference_interval_s = 1.0
    gui.ui.diagnostics.apply_settings()
    monitoring = gui.ui.monitoring
    monitoring.configure_simulation(SimulationConfig(scenario=scenario, seed=4))
    monitoring.set_speed_factor(10.0)
    monitoring.start(record=record, vehicle_id=vehicle.id if vehicle else None)


def wait_assessment(gui: GuiApplication, qtbot: QtBot, *, timeout: int = 30_000) -> None:
    qtbot.waitUntil(
        lambda: (
            gui.ui.diagnostics.latest is not None
            and gui.ui.diagnostics.latest.status is not DiagnosticStatus.INSUFFICIENT_DATA
        ),
        timeout=timeout,
    )


def test_ai_diagnostics_is_a_real_page_in_navigation(gui: GuiApplication) -> None:
    assert "diagnostics" in {item.key for item in PAGES}
    assert "diagnostics" not in {item.key for item in UPCOMING}
    assert gui.window.sidebar.buttons["diagnostics"].isEnabled()
    shortcuts = {s.key().toString(): s for s in gui.window.findChildren(QShortcut)}
    shortcuts["Ctrl+5"].activated.emit()
    assert gui.window.current_key == "diagnostics"
    shortcuts["Ctrl+3"].activated.emit()
    assert gui.window.current_key == "garage"


def test_models_load_in_background_and_are_reported(gui: GuiApplication, qtbot: QtBot) -> None:
    wait_models(gui, qtbot)
    assert gui.ui.diagnostics.model_status(CLASSIFIER_NAME) is LoadStatus.AVAILABLE
    assert gui.ui.diagnostics.model_status(ANOMALY_NAME) is LoadStatus.AVAILABLE
    view = page(gui)
    assert view.classifier_pill.text == "Classifier: available"
    assert view.importance_chart.labels, "global importance comes from the model manifest"


def test_stopped_state_is_explicit(gui: GuiApplication, qtbot: QtBot) -> None:
    wait_models(gui, qtbot)
    view = page(gui)
    assert view.findings_stack.state is ViewState.EMPTY
    assert view.findings_stack.panel.title_label.text() == "Monitoring stopped"
    assert view.health_widget.score_text() == "—"
    assert view.status_pill.text == "Status: Monitoring stopped"
    dashboard = gui.window.pages["dashboard"]
    assert isinstance(dashboard, DashboardPage)
    assert "Monitoring stopped" in dashboard.diagnostics_card.status_pill.text


def test_live_diagnostics_end_to_end(
    gui: GuiApplication, qtbot: QtBot, active_vehicle: Vehicle
) -> None:
    wait_models(gui, qtbot)
    view = page(gui)
    start_fast(gui, record=True, vehicle=active_vehicle)
    gui.ui.monitoring.set_output_override("coolant_temp_c", 124.0)
    qtbot.waitUntil(
        lambda: (
            gui.ui.diagnostics.latest is not None
            and any(f.key == "rule:coolant_temperature" for f in gui.ui.diagnostics.latest.findings)
        ),
        timeout=30_000,
    )
    latest = gui.ui.diagnostics.latest
    assert latest is not None
    assert latest.status is DiagnosticStatus.CRITICAL
    view.refresh_view()
    cards = view.findings_widget.findChildren(FindingCard)
    assert {c.finding.key for c in cards} == {f.key for f in latest.findings}
    assert view.findings_stack.state is ViewState.CONTENT
    expected_score = "—" if latest.health.score is None else str(latest.health.score)
    assert view.health_widget.score_text() == expected_score
    assert latest.classifier.status in (ModelRunStatus.OK, ModelRunStatus.ABSTAINED)
    if latest.classifier.status is ModelRunStatus.OK:
        row = view.probability_rows[latest.classifier.labels[0].category]
        assert row.bar.value() == round(latest.classifier.labels[0].probability * 100)
    category = view.explanation_combo.currentData()
    if category is not None:
        explanation = latest.explanations[category]
        expected = sorted(
            explanation.contributions, key=lambda c: abs(c.contribution), reverse=True
        )[:10]
        assert view.contribution_chart.values == pytest.approx([c.contribution for c in expected])
    dashboard = gui.window.pages["dashboard"]
    assert isinstance(dashboard, DashboardPage)
    assert "Critical" in dashboard.diagnostics_card.status_pill.text
    qtbot.waitUntil(
        lambda: bool(gui.ui.telemetry.recent_alerts(vehicle_id=active_vehicle.id)), timeout=10_000
    )
    view.reload_history()
    assert view.history_table.rowCount() >= 1
    view.history_table.selectRow(0)
    assert "Rule engine" in view.history_details.text() or "model" in view.history_details.text()
    gui.ui.monitoring.stop()
    assert gui.ui.diagnostics.latest is None
    view.refresh_view()
    assert view.findings_stack.panel.title_label.text() == "Monitoring stopped"


def test_inference_never_overlaps(gui: GuiApplication, qtbot: QtBot) -> None:
    wait_models(gui, qtbot)
    controller = gui.ui.diagnostics
    start_fast(gui)
    qtbot.waitUntil(lambda: len(gui.ui.monitoring.buffer) > 5, timeout=5000)
    controller._timer.stop()
    qtbot.waitUntil(lambda: not controller.busy, timeout=10_000)
    assert controller.tick()
    skipped = controller.skipped_ticks
    assert not controller.tick()
    assert controller.skipped_ticks == skipped + 1
    qtbot.waitUntil(lambda: not controller.busy, timeout=10_000)
    gui.ui.monitoring.stop()


def test_results_from_a_stopped_run_are_discarded(gui: GuiApplication, qtbot: QtBot) -> None:
    wait_models(gui, qtbot)
    controller = gui.ui.diagnostics
    start_fast(gui)
    qtbot.waitUntil(lambda: len(gui.ui.monitoring.buffer) > 5, timeout=5000)
    controller._timer.stop()
    qtbot.waitUntil(lambda: not controller.busy, timeout=10_000)
    assert controller.tick()
    gui.ui.monitoring.stop()
    qtbot.waitUntil(lambda: not controller.busy, timeout=10_000)
    assert controller.latest is None


def test_telemetry_keeps_flowing_while_inference_runs(gui: GuiApplication, qtbot: QtBot) -> None:
    wait_models(gui, qtbot)
    start_fast(gui)
    wait_assessment(gui, qtbot)
    runs_before = gui.ui.diagnostics.completed_runs
    frames_before = len(gui.ui.monitoring.buffer)
    qtbot.wait(3000)
    assert gui.ui.diagnostics.completed_runs > runs_before
    assert len(gui.ui.monitoring.buffer) - frames_before >= 15
    gui.ui.monitoring.stop()


def test_diagnostics_can_be_turned_off(gui: GuiApplication, qtbot: QtBot) -> None:
    wait_models(gui, qtbot)
    settings_page = gui.window.pages["settings"]
    assert isinstance(settings_page, SettingsPage)
    settings_page.diagnostics_check.setChecked(False)
    assert gui.app_context.settings_store.load().diagnostics.enabled is False
    start_fast(gui)
    qtbot.wait(1500)
    assert gui.ui.diagnostics.latest is None
    view = page(gui)
    assert view.findings_stack.panel.title_label.text() == "Diagnostics are turned off"
    gui.ui.monitoring.stop()


@pytest.fixture
def gui_without_models(qapp: QApplication, tmp_path: Path) -> Iterator[GuiApplication]:
    ctx = bootstrap(home=tmp_path / "home", console_logging=False)
    ctx.settings.appearance.animations_enabled = False
    app = GuiApplication(ctx, install_excepthook=False, registry=ModelRegistry(tmp_path / "none"))
    app.window.show()
    yield app
    app.shutdown()
    shutdown(ctx)


def test_rules_still_work_when_models_are_unavailable(
    gui_without_models: GuiApplication, qtbot: QtBot
) -> None:
    gui = gui_without_models
    wait_models(gui, qtbot)
    assert gui.ui.diagnostics.model_status(CLASSIFIER_NAME) is LoadStatus.MISSING
    view = page(gui)
    assert view.classifier_pill.text == "Classifier: unavailable"
    start_fast(gui)
    gui.ui.monitoring.set_output_override("coolant_temp_c", 124.0)
    qtbot.waitUntil(
        lambda: gui.ui.diagnostics.latest is not None and bool(gui.ui.diagnostics.latest.findings),
        timeout=30_000,
    )
    latest = gui.ui.diagnostics.latest
    assert latest is not None
    assert latest.classifier.status is ModelRunStatus.UNAVAILABLE
    view.refresh_view()
    assert "Model unavailable" in view.classifier_status.text()
    assert view.explanation_stack.state is ViewState.EMPTY
    gui.ui.monitoring.stop()


def test_shutdown_stops_inference_thread(gui: GuiApplication, qtbot: QtBot) -> None:
    wait_models(gui, qtbot)
    start_fast(gui)
    wait_assessment(gui, qtbot)
    gui.shutdown()
    assert not gui.ui.diagnostics.thread_running()
    assert not gui.ui.monitoring.threads_running()
