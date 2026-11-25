"""Background job runner, notification delivery and reminders. No real OS notification is shown."""

from __future__ import annotations

import gc
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from smartdrive.ai.model_registry import LoadedModels, LoadStatus
from smartdrive.app import bootstrap, shutdown
from smartdrive.config.constants import NotificationCategory, NotificationSeverity
from smartdrive.models.maintenance import ScheduleInput
from smartdrive.models.notification import Notification
from smartdrive.models.vehicle import Vehicle
from smartdrive.obd.errors import OperationCancelledError
from smartdrive.obd.mock import MOCK_PORT, PROFILES, MockElm327Transport
from smartdrive.obd.session import ConnectionParameters, ConnectionStatus, ObdSession
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.gc_guard import MainThreadGarbageCollector
from smartdrive.ui.workers.task_runner import MAX_PENDING, TaskRunner
from smartdrive.ui.workers.voice_worker import VoiceWorker
from smartdrive.utils.exceptions import ExportError
from tests.ui.conftest import FakeSpeech

pytestmark = pytest.mark.ui


class TestTaskRunner:
    def test_results_failures_and_order(self, qtbot: QtBot) -> None:
        runner = TaskRunner()
        finished: list[tuple[int, object]] = []
        failed: list[tuple[int, str]] = []
        runner.finished.connect(lambda i, r: finished.append((i, r)))
        runner.failed.connect(lambda i, m: failed.append((i, m)))
        a = runner.submit("a", lambda: 1)
        b = runner.submit("b", lambda: (_ for _ in ()).throw(ExportError("x", user_message="No.")))
        c = runner.submit("c", lambda: 1 / 0)
        qtbot.waitUntil(lambda: len(finished) + len(failed) == 3)
        assert finished == [(a, 1)]
        assert failed[0] == (b, "No.")
        assert failed[1][0] == c and "failed unexpectedly" in failed[1][1]
        assert not runner.busy
        runner.shutdown()
        assert not runner.thread_running()
        assert runner.submit("late", lambda: 1) is None

    def test_queue_is_bounded_and_shutdown_drops_waiting_jobs(self, qtbot: QtBot) -> None:
        runner = TaskRunner()
        release = threading.Event()
        ran: list[int] = []
        runner.submit("blocker", release.wait)
        qtbot.wait(50)
        accepted = [
            runner.submit(f"job {i}", lambda i=i: ran.append(i)) for i in range(MAX_PENDING + 3)
        ]
        assert accepted.count(None) >= 2  # rejected, not silently queued without limit
        release.set()
        runner.shutdown()
        assert not runner.thread_running()
        assert len(ran) < MAX_PENDING  # queued jobs were dropped at shutdown


class FakeTray:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def showMessage(self, title: str, message: str, *_args: object) -> None:  # noqa: N802
        self.messages.append((title, message))

    def hide(self) -> None:
        pass

    def deleteLater(self) -> None:  # noqa: N802
        pass


def test_new_notifications_are_delivered_once(gui: GuiApplication) -> None:
    controller = gui.ui.notifications
    tray = FakeTray()
    controller._tray = tray  # type: ignore[assignment]  # stands in for the system tray
    delivered: list[Notification] = []
    controller.delivered.connect(delivered.append)
    for _ in range(3):
        controller.post(
            NotificationSeverity.WARNING,
            NotificationCategory.CONNECTION,
            "Connection lost",
            "Reconnecting.",
            dedup_key="conn:lost",
        )
    assert len(delivered) == 1
    assert tray.messages == [("Connection lost", "Reconnecting.")]
    assert delivered[0].occurrence_count == 1
    (stored,) = controller.service.list_notifications()
    assert stored.occurrence_count == 3
    toast_texts = [t.message_label.text() for t in gui.window.toasts.toasts()]
    assert any("Connection lost" in text for text in toast_texts)


def test_maintenance_reminders_are_generated_and_not_repeated(
    gui: GuiApplication, active_vehicle: Vehicle, qtbot: QtBot
) -> None:
    maintenance = gui.ui.maintenance
    maintenance.add_schedule(
        active_vehicle.id,
        ScheduleInput(
            task_name="Brake inspection",
            interval_days=365,
            last_done_date=date.today() - timedelta(days=400),
        ),
    )
    maintenance.add_schedule(
        active_vehicle.id,
        ScheduleInput(
            task_name="Coolant service",
            interval_days=365,
            last_done_date=date.today() - timedelta(days=355),
        ),
    )
    controller = gui.ui.notifications
    controller.check_maintenance()
    qtbot.waitUntil(
        lambda: len(controller.service.list_notifications(category="maintenance")) == 2,
        timeout=10_000,
    )
    titles = {n.title: n.severity for n in controller.service.list_notifications()}
    assert titles["Brake inspection: overdue"] is NotificationSeverity.WARNING
    assert titles["Coolant service: upcoming"] is NotificationSeverity.INFORMATION
    controller.check_maintenance()
    qtbot.wait(300)
    assert len(controller.service.list_notifications(category="maintenance")) == 2
    gui.ui.app.settings.maintenance.reminders_enabled = False
    controller.check_maintenance()
    assert controller._maintenance_job is None


def test_model_problems_are_reported_once(gui: GuiApplication, qtbot: QtBot) -> None:
    diagnostics = gui.ui.diagnostics
    qtbot.waitUntil(lambda: diagnostics.models is not None, timeout=20_000)
    diagnostics.models = LoadedModels(
        None, None, {"fault_classifier": LoadStatus.INTEGRITY_FAILED}, {}, {}
    )
    diagnostics.models_changed.emit(diagnostics.models)
    diagnostics.models_changed.emit(diagnostics.models)
    notes = gui.ui.notifications.service.list_notifications(category="model")
    assert len(notes) == 1
    assert "integrity failed" in notes[0].message
    assert "Rule-based diagnostics continue" in notes[0].message


def test_retention_runs_in_the_background(gui: GuiApplication, qtbot: QtBot) -> None:
    service = gui.ui.notifications.service
    old = datetime.now(UTC) - timedelta(days=400)
    note = service.notify(
        NotificationSeverity.INFORMATION, NotificationCategory.APPLICATION, "Old", now=old
    ).notification
    service.mark_read(note.id)
    gui.ui.notifications.purge_old()
    qtbot.waitUntil(lambda: service.list_notifications() == [], timeout=10_000)


class SlowAdapter(MockElm327Transport):
    """A mock adapter that takes a long time to answer, honouring cancellation like the real one."""

    def read_until_prompt(self, timeout_s: float, cancel: threading.Event | None = None) -> str:
        if cancel is not None and cancel.wait(min(timeout_s, 5.0)):
            raise OperationCancelledError("Read cancelled")
        return super().read_until_prompt(timeout_s, cancel)


def test_shutdown_while_connecting_does_not_wait_for_the_adapter(
    qapp: QApplication, tmp_path: Path, fake_speech: FakeSpeech
) -> None:
    ctx = bootstrap(home=tmp_path / "home", console_logging=False)
    ctx.settings.alerts.desktop_notifications = False
    ctx.settings.obd.show_mock_adapter = True

    def factory(params: ConnectionParameters, **kwargs: object) -> ObdSession:
        return ObdSession(
            params,
            transport_factory=lambda _p, _b: SlowAdapter(PROFILES["healthy"]()),
            **kwargs,  # type: ignore[arg-type]
        )

    gui = GuiApplication(
        ctx,
        install_excepthook=False,
        obd_session_factory=factory,
        voice_worker=VoiceWorker(lambda: fake_speech),
    )
    try:
        gui.ui.connection.connect_adapter(MOCK_PORT, vehicle_id=None)
        deadline = time.monotonic() + 5
        while gui.ui.connection.status is not ConnectionStatus.CONNECTING:
            qapp.processEvents()
            assert time.monotonic() < deadline
        started = time.monotonic()
        gui.shutdown()
        assert time.monotonic() - started < 4.0  # cancelled, not waited out
        assert not gui.ui.connection.thread_running()
    finally:
        gui.shutdown()
        shutdown(ctx)


def test_garbage_collection_guard_restores_automatic_collection() -> None:
    was_enabled = gc.isenabled()
    gc.enable()
    guard = MainThreadGarbageCollector(interval_ms=10)
    guard.start()
    try:
        assert not gc.isenabled() and guard.active
        assert guard.collect() >= 0
    finally:
        guard.stop()
    assert gc.isenabled() and not guard.active
    if not was_enabled:
        gc.disable()
