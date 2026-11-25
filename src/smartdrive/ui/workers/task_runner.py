"""A single background thread that runs short jobs one at a time.

Used for work that touches the database or the file system but not Qt widgets: finalising a
trip, loading a trip for replay, generating a PDF or CSV export, checking maintenance schedules.
Jobs run in submission order. The queue is bounded so a burst of requests cannot pile up work;
``submit`` returns ``None`` when it is full. Results come back on the GUI thread as
``finished(job_id, result)`` or ``failed(job_id, message)``.

A job must not touch widgets. A job that is running when the application closes is allowed to
finish (database transactions are short); jobs still queued are dropped.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from PySide6.QtCore import QObject, QThread, Signal, Slot

from smartdrive.utils.exceptions import SmartDriveError

logger = logging.getLogger(__name__)

MAX_PENDING: Final = 16
THREAD_JOIN_TIMEOUT_MS: Final = 15_000


@dataclass(frozen=True, slots=True)
class Job:
    job_id: int
    name: str
    function: Callable[[], Any]


class _JobWorker(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    started = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._jobs: deque[Job] = deque()
        self._closed = False

    def push(self, job: Job) -> bool:
        with self._lock:
            if self._closed or len(self._jobs) >= MAX_PENDING:
                return False
            self._jobs.append(job)
            return True

    def pending(self) -> int:
        with self._lock:
            return len(self._jobs)

    def close(self) -> int:
        with self._lock:
            self._closed = True
            dropped = len(self._jobs)
            self._jobs.clear()
            return dropped

    @Slot()
    def drain(self) -> None:
        while True:
            with self._lock:
                if self._closed or not self._jobs:
                    return
                job = self._jobs.popleft()
            self.started.emit(job.job_id, job.name)
            try:
                result = job.function()
            except SmartDriveError as exc:
                logger.warning("Background job failed", extra={"job": job.name, "error": str(exc)})
                self.failed.emit(job.job_id, exc.user_message)
            except Exception as exc:
                logger.exception("Background job crashed", extra={"job": job.name})
                self.failed.emit(job.job_id, f"{job.name} failed unexpectedly: {exc}")
            else:
                self.finished.emit(job.job_id, result)


class TaskRunner(QObject):
    """Main-thread handle to the job thread."""

    finished = Signal(int, object)
    failed = Signal(int, str)
    busy_changed = Signal(bool)
    _wake = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ids = itertools.count(1)
        self._running: set[int] = set()
        self._names: dict[int, str] = {}
        self._closed = False
        self._worker = _JobWorker()
        self._thread = QThread()
        self._thread.setObjectName("smartdrive-tasks")
        self._worker.moveToThread(self._thread)
        self._wake.connect(self._worker.drain)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    @property
    def busy(self) -> bool:
        return bool(self._running)

    def is_pending(self, job_id: int) -> bool:
        return job_id in self._running

    def thread_running(self) -> bool:
        return self._thread.isRunning()

    def submit(self, name: str, function: Callable[[], Any]) -> int | None:
        """Queue ``function``. Returns its job id, or ``None`` if closed or the queue is full."""
        if self._closed:
            return None
        job_id = next(self._ids)
        if not self._worker.push(Job(job_id, name, function)):
            logger.warning("Background queue full; job rejected", extra={"job": name})
            return None
        was_busy = self.busy
        self._running.add(job_id)
        self._names[job_id] = name
        if not was_busy:
            self.busy_changed.emit(True)
        self._wake.emit()
        return job_id

    def _done(self, job_id: int) -> None:
        self._running.discard(job_id)
        self._names.pop(job_id, None)
        if not self._running:
            self.busy_changed.emit(False)

    def _on_finished(self, job_id: int, result: object) -> None:
        self._done(job_id)
        self.finished.emit(job_id, result)

    def _on_failed(self, job_id: int, message: str) -> None:
        self._done(job_id)
        self.failed.emit(job_id, message)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        dropped = self._worker.close()
        if dropped:
            logger.info("Dropped queued background jobs at shutdown", extra={"jobs": dropped})
        self._thread.quit()
        if not self._thread.wait(THREAD_JOIN_TIMEOUT_MS):
            logger.error("Background job thread did not stop within timeout")
        self._running.clear()
