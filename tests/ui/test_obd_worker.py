"""ObdWorker slots on the test thread, with the mock adapter (in the app they run on a QThread).

Covers discovery, connection success and failure, ECU retry, polling, pause, code scans,
bounded reconnection after a lost link, and shutdown.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from smartdrive.obd.mock import MOCK_PORT, PROFILES, MockElm327Transport
from smartdrive.obd.session import (
    ConnectionParameters,
    ConnectionReport,
    ConnectionStatus,
    DtcScanResult,
    ObdSession,
    PollResult,
    ReconnectPolicy,
)
from smartdrive.services.data_source import TelemetryFrame
from smartdrive.ui.workers.obd_worker import ObdWorker

pytestmark = pytest.mark.ui


class Harness:
    def __init__(self, profile: str = "healthy", *, attempts: int = 2) -> None:
        self.transports: list[MockElm327Transport] = []
        self.profile = profile
        self.cancel = threading.Event()
        self.adapter_present = True
        self.worker = ObdWorker(
            self.cancel,
            policy=ReconnectPolicy(max_attempts=attempts, initial_delay_s=0.05),
            session_factory=self._session,
        )
        self.events: dict[str, list[Any]] = {}
        for name in (
            "status_changed",
            "ports_listed",
            "connected",
            "connect_failed",
            "frame_ready",
            "polled",
            "quality_changed",
            "scan_finished",
            "scan_failed",
            "link_lost",
            "reconnected",
            "reconnect_failed",
            "disconnected",
        ):
            bucket: list[Any] = []
            self.events[name] = bucket
            getattr(self.worker, name).connect(lambda *args, b=bucket: b.append(args))

    def _session(self, params: ConnectionParameters, **kwargs: Any) -> ObdSession:
        def factory(_params: ConnectionParameters, _baud: int) -> MockElm327Transport:
            transport = MockElm327Transport(PROFILES[self.profile]())
            if not self.adapter_present:
                transport.profile.reconnectable = False
                transport.unplug()
            self.transports.append(transport)
            return transport

        return ObdSession(params, transport_factory=factory, **kwargs)

    def statuses(self) -> list[str]:
        return [args[0] for args in self.events["status_changed"]]

    def connect(self, port: str | None = MOCK_PORT) -> None:
        self.worker.connect_adapter(ConnectionParameters(port=port))


def test_discovery_lists_the_mock_only_when_asked(qtbot: QtBot) -> None:
    h = Harness()
    h.worker.list_ports(True)
    h.worker.list_ports(False)
    with_mock, without = (args[0] for args in h.events["ports_listed"])
    assert MOCK_PORT in [p.port for p in with_mock]
    assert MOCK_PORT not in [p.port for p in without]
    assert h.statuses()[0] == ConnectionStatus.DISCOVERING.value


def test_connect_poll_pause_scan_and_disconnect(qtbot: QtBot) -> None:
    h = Harness("stored_codes")
    h.connect()
    ((report,),) = h.events["connected"]
    assert isinstance(report, ConnectionReport) and report.ecu_connected
    h.worker.start_polling(50)
    qtbot.waitUntil(lambda: len(h.events["frame_ready"]) >= 2)
    frame = h.events["frame_ready"][0][0]
    assert isinstance(frame, TelemetryFrame) and frame.sample is not None
    assert isinstance(h.events["polled"][0][0], PollResult)
    assert h.events["quality_changed"]
    h.worker.set_paused(True)
    count = len(h.events["frame_ready"])
    qtbot.wait(150)
    assert len(h.events["frame_ready"]) <= count + 1
    h.worker.set_paused(False)
    h.worker.set_interval(80)
    qtbot.waitUntil(lambda: len(h.events["frame_ready"]) > count + 1)
    h.worker.scan_codes(True)
    ((scan,),) = h.events["scan_finished"]
    assert isinstance(scan, DtcScanResult) and "P0301" in scan.stored
    h.worker.stop_polling()
    assert h.statuses()[-1] == ConnectionStatus.ECU_CONNECTED.value
    h.worker.disconnect_adapter()
    assert h.events["disconnected"] == [("Disconnected by the user.",)]
    assert h.statuses()[-1] == ConnectionStatus.DISCONNECTED.value
    h.worker.scan_codes(True)
    assert h.events["scan_failed"]
    h.worker.shutdown()


def test_connection_failures_are_reported(qtbot: QtBot) -> None:
    h = Harness()
    h.connect(None)
    assert h.events["connect_failed"]
    assert h.statuses()[-1] == ConnectionStatus.FAILED.value
    h.cancel.set()
    h.connect()
    assert h.events["connect_failed"][-1] == ("Connection cancelled.",)


def test_ecu_that_does_not_answer_can_be_retried(qtbot: QtBot) -> None:
    h = Harness("no_ecu")
    h.connect()
    ((report,),) = h.events["connected"]
    assert not report.ecu_connected
    h.worker.start_polling(50)  # refused: no ECU
    qtbot.wait(100)
    assert h.events["frame_ready"] == []
    h.worker.retry_ecu()
    assert len(h.events["connected"]) == 2
    assert not h.events["connected"][-1][0].ecu_connected


def test_lost_link_reconnects_then_gives_up_after_the_limit(qtbot: QtBot) -> None:
    h = Harness(attempts=2)
    h.connect()
    h.worker.start_polling(30)
    qtbot.waitUntil(lambda: bool(h.events["frame_ready"]))
    h.transports[-1].unplug()
    qtbot.waitUntil(lambda: bool(h.events["link_lost"]), timeout=5000)
    qtbot.waitUntil(lambda: bool(h.events["reconnected"]), timeout=5000)
    frames = len(h.events["frame_ready"])
    qtbot.waitUntil(lambda: len(h.events["frame_ready"]) > frames, timeout=5000)
    # Now the adapter is removed for good: every attempt fails until the limit is reached.
    h.adapter_present = False
    h.transports[-1].unplug()
    qtbot.waitUntil(lambda: bool(h.events["reconnect_failed"]), timeout=5000)
    assert "after 2 attempts" in h.events["reconnect_failed"][-1][0]
    assert h.statuses()[-1] == ConnectionStatus.FAILED.value
    reconnecting = [s for s in h.statuses() if s == ConnectionStatus.RECONNECTING.value]
    assert len(reconnecting) >= 3  # two attempts after the second loss, one after the first
    h.worker.shutdown()
