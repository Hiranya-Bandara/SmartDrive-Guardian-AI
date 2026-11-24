"""Reusable widgets, dialogs and the monitoring worker exercised directly on the GUI thread
(coverage.py cannot trace code running inside native QThreads)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget
from pytestqt.qtbot import QtBot

from smartdrive.services.data_source import TelemetryFrame, TelemetrySource
from smartdrive.services.simulator import SimulationConfig, SimulationSource
from smartdrive.ui.dialogs.confirm import ConfirmDialog, confirm
from smartdrive.ui.themes.palette import LIGHT
from smartdrive.ui.widgets.cards import MetricCard
from smartdrive.ui.widgets.gauges import CircularGauge, GaugeBand, LinearGauge
from smartdrive.ui.widgets.inputs import FormField
from smartdrive.ui.widgets.notifications import Banner, ToastHost
from smartdrive.ui.widgets.states import StatefulStack, ViewState
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel
from smartdrive.ui.workers.monitoring_worker import MonitoringWorker

pytestmark = pytest.mark.ui


class TestMonitoringWorker:
    def test_polls_pauses_reconfigures_and_stops(self, qapp: QApplication, qtbot: QtBot) -> None:
        source = SimulationSource(SimulationConfig(seed=1))
        worker = MonitoringWorker(source, 20)
        frames: list[object] = []
        worker.frame_ready.connect(frames.append)
        worker.start()
        qtbot.waitUntil(lambda: len(frames) >= 3, timeout=3000)
        assert all(isinstance(f, TelemetryFrame) for f in frames)
        worker.set_paused(True)
        count = len(frames)
        qtbot.wait(120)
        assert len(frames) == count
        worker.set_paused(False)
        worker.set_interval(10)
        assert worker.interval_ms == 10
        qtbot.waitUntil(lambda: len(frames) > count, timeout=3000)
        worker.execute(lambda s: s.simulator.set_output_override("rpm", 3000.0))  # type: ignore[attr-defined]
        worker.execute("not callable")
        with qtbot.waitSignal(worker.command_failed, timeout=1000):
            worker.execute(lambda s: s.simulator.set_output_override("rpm", -1.0))  # type: ignore[attr-defined]
        with qtbot.waitSignal(worker.stopped, timeout=1000):
            worker.stop()
        assert not source.is_open

    def test_read_failure_stops_worker(self, qapp: QApplication, qtbot: QtBot) -> None:
        class Broken(SimulationSource):
            def read(self, interval_s: float) -> TelemetryFrame:
                raise OSError("adapter unplugged")

        worker = MonitoringWorker(Broken(), 10)
        with qtbot.waitSignals([worker.failed, worker.stopped], timeout=2000):
            worker.start()

    def test_open_failure_is_reported(self, qapp: QApplication, qtbot: QtBot) -> None:
        class Unopenable(SimulationSource):
            def open(self) -> None:
                raise OSError("port busy")

        source: TelemetrySource = Unopenable()
        worker = MonitoringWorker(source, 10)
        with qtbot.waitSignals([worker.failed, worker.stopped], timeout=2000):
            worker.start()


class TestDialogs:
    def test_confirm_returns_true_when_accepted(self, qapp: QApplication) -> None:
        def accept_active() -> None:
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, ConfirmDialog)
            dialog.confirm_button.click()

        QTimer.singleShot(50, accept_active)
        assert confirm(None, "Delete?", "Really?", destructive=True)

    def test_confirm_defaults_to_cancel(self, qapp: QApplication) -> None:
        dialog = ConfirmDialog("Reset?", "Defaults return.", palette=LIGHT)
        assert dialog.cancel_button.isDefault()
        QTimer.singleShot(50, dialog.reject)
        assert dialog.exec() == QDialog.DialogCode.Rejected


class TestWidgets:
    def test_circular_gauge_values_and_missing(self, qtbot: QtBot) -> None:
        gauge = CircularGauge("Coolant", "°C", 0, 130, bands=(GaugeBand(105, 130, "critical"),))
        qtbot.addWidget(gauge)
        gauge.animations_enabled = False
        gauge.resize(200, 220)
        gauge.show()
        gauge.set_value(250.0)
        assert gauge.value == 250.0
        assert gauge.value_text() == "250"
        gauge.grab()
        gauge.set_value(None)
        assert gauge.value_text() == "—"
        assert "No data" not in gauge.toolTip()
        gauge.configure(unit="°F", minimum=32, maximum=266, bands=())
        gauge.apply_palette(LIGHT)
        gauge.grab()

    def test_linear_gauge_low_band_is_stated_in_text(self, qtbot: QtBot) -> None:
        gauge = LinearGauge("Fuel level", "%", low_band=15.0)
        qtbot.addWidget(gauge)
        gauge.animations_enabled = False
        gauge.set_value(10.0)
        assert gauge.is_low()
        assert "Low" in gauge.value_text()
        gauge.set_value(None)
        assert not gauge.is_low()
        gauge.grab()

    def test_status_indicator_always_has_text(self, qtbot: QtBot) -> None:
        indicator = StatusIndicator("Receiving data", StatusLevel.NORMAL, prefix="Link: ")
        qtbot.addWidget(indicator)
        assert indicator.text == "Link: Receiving data"
        indicator.set_status("No response", StatusLevel.CRITICAL)
        assert indicator.level is StatusLevel.CRITICAL
        assert indicator.accessibleName() == "Link: No response"
        indicator.apply_palette(LIGHT)

    def test_metric_card(self, qtbot: QtBot) -> None:
        card = MetricCard("Voltage", "V")
        qtbot.addWidget(card)
        card.set_value("14.10", "V", "Charging")
        assert "14.10" in card.accessibleName()
        card.set_value(None)
        assert card.value_label.text() == "—"

    def test_stateful_stack_states_and_retry(self, qtbot: QtBot) -> None:
        stack = StatefulStack(QWidget())
        qtbot.addWidget(stack)
        retried: list[bool] = []
        stack.show_loading("Loading vehicles")
        assert stack.state is ViewState.LOADING
        assert stack.panel.progress.isVisibleTo(stack.panel)
        stack.show_error("Failed", "Database locked", action=lambda: retried.append(True))
        assert stack.state is ViewState.ERROR
        stack.panel.action_button.click()
        assert retried == [True]
        stack.show_empty("Nothing here")
        assert not stack.panel.action_button.isVisibleTo(stack.panel)
        stack.apply_palette(LIGHT)
        stack.show_content()
        assert stack.currentWidget() is stack.content

    def test_form_field_errors(self, qtbot: QtBot) -> None:
        field = FormField("VIN", QLineEdit(), required=True, hint="17 characters")
        qtbot.addWidget(field)
        assert field.title_label.text() == "VIN *"
        field.set_error("Too short")
        assert field.has_error
        assert field.editor.property("invalid") == "true"
        field.set_error(None)
        assert not field.has_error

    def test_banner_and_toasts(self, qtbot: QtBot) -> None:
        host = QWidget()
        qtbot.addWidget(host)
        host.resize(800, 600)
        host.show()
        banner = Banner("Simulated", StatusLevel.SIMULATION, parent=host)
        banner.set_message("Stale data", StatusLevel.WARNING)
        assert banner.property("level") == "warning"
        banner.apply_palette(LIGHT)
        toasts = ToastHost(host)
        for index in range(ToastHost.MAX_VISIBLE + 2):
            toasts.notify(f"Message {index}", StatusLevel.INFO, timeout_ms=0)
        qtbot.wait(10)
        toast = toasts.toasts()[-1]
        toast.dismiss()
        qtbot.waitUntil(lambda: toast not in toasts.toasts(), timeout=2000)
