"""Polls a telemetry source on its own thread.

The worker never touches widgets. Results leave the thread only as Qt signals, and every
mutation of the source (overrides, reset, speed) is executed *inside* the worker thread via
:meth:`execute`, so the source needs no locking.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from smartdrive.services.data_source import TelemetrySource

logger = logging.getLogger(__name__)

SourceCommand = Callable[[TelemetrySource], None]


class MonitoringWorker(QObject):
    frame_ready = Signal(object)
    failed = Signal(str)  # fatal: the worker has stopped
    command_failed = Signal(str)  # non-fatal: one configuration change was rejected
    stopped = Signal()

    def __init__(self, source: TelemetrySource, interval_ms: int) -> None:
        super().__init__()
        self._source = source
        self._interval_ms = interval_ms
        self._timer: QTimer | None = None
        self._last_tick: float | None = None
        self._paused = False
        self._running = False

    @property
    def interval_ms(self) -> int:
        return self._interval_ms

    @Slot()
    def start(self) -> None:
        try:
            self._source.open()
        except Exception as exc:
            logger.exception("Telemetry source failed to open")
            self.failed.emit(f"Could not start {self._source.description}: {exc}")
            self.stopped.emit()
            return
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._running = True
        self._last_tick = time.monotonic()
        self._timer.start(self._interval_ms)
        logger.info("Monitoring started", extra={"source": self._source.description})

    @Slot(bool)
    def set_paused(self, paused: bool) -> None:
        if self._timer is None or paused == self._paused:
            return
        self._paused = paused
        if paused:
            self._timer.stop()
        else:
            self._last_tick = time.monotonic()
            self._timer.start(self._interval_ms)

    @Slot(int)
    def set_interval(self, interval_ms: int) -> None:
        self._interval_ms = interval_ms
        if self._timer is not None and not self._paused:
            self._timer.start(interval_ms)

    @Slot(object)
    def execute(self, command: object) -> None:
        if not callable(command):
            return
        try:
            command(self._source)
        except Exception as exc:
            logger.exception("Telemetry source command failed")
            self.command_failed.emit(str(exc))

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        if self._running:
            self._running = False
            try:
                self._source.close()
            except Exception:
                logger.exception("Telemetry source failed to close cleanly")
            logger.info("Monitoring stopped")
        self.stopped.emit()

    def _tick(self) -> None:
        now = time.monotonic()
        nominal = self._interval_ms / 1000.0
        elapsed = nominal if self._last_tick is None else now - self._last_tick
        self._last_tick = now
        interval_s = min(max(elapsed, nominal * 0.5), nominal * 5.0)
        try:
            frames = self._source.read_frames(interval_s)
        except Exception as exc:
            logger.exception("Telemetry read failed")
            self.failed.emit(f"Telemetry read failed: {exc}")
            self.stop()
            return
        for frame in frames:
            self.frame_ready.emit(frame)
