"""Writes telemetry to the database in batches on a background thread."""

from __future__ import annotations

import logging
from collections import deque
from typing import Final

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from smartdrive.models.telemetry import TelemetrySample
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.utils.exceptions import SmartDriveError

logger = logging.getLogger(__name__)

DEFAULT_FLUSH_MS: Final = 1000
DEFAULT_BATCH: Final = 250
DEFAULT_MAX_PENDING: Final = 10_000


class PersistenceWorker(QObject):
    persisted = Signal(int)
    dropped = Signal(int)
    failed = Signal(str)

    def __init__(
        self,
        service: TelemetryService,
        session_id: int,
        *,
        flush_interval_ms: int = DEFAULT_FLUSH_MS,
        batch_size: int = DEFAULT_BATCH,
        max_pending: int = DEFAULT_MAX_PENDING,
    ) -> None:
        super().__init__()
        self._service = service
        self._session_id = session_id
        self._flush_interval_ms = flush_interval_ms
        self._batch_size = batch_size
        self._pending: deque[TelemetrySample] = deque(maxlen=max_pending)
        self._timer: QTimer | None = None
        self.total_persisted = 0
        self.total_dropped = 0
        self._failed = False

    @property
    def session_id(self) -> int:
        return self._session_id

    @Slot()
    def start(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.flush)
        self._timer.start(self._flush_interval_ms)

    @Slot(object)
    def enqueue(self, sample: object) -> None:
        if self._failed or not isinstance(sample, TelemetrySample):
            return
        if len(self._pending) == self._pending.maxlen:
            self.total_dropped += 1
            self.dropped.emit(self.total_dropped)
        self._pending.append(sample)
        if len(self._pending) >= self._batch_size:
            self.flush()

    @Slot()
    def flush(self) -> None:
        if self._failed or not self._pending:
            return
        batch = list(self._pending)
        try:
            written = self._service.append(self._session_id, batch)
        except SmartDriveError as exc:
            self._failed = True
            logger.exception("Telemetry persistence failed")
            self.failed.emit(exc.user_message)
            return
        self._pending.clear()
        self.total_persisted += written
        self.persisted.emit(self.total_persisted)

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        self.flush()
