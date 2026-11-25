"""Run Python's cyclic garbage collector on the GUI thread only.

CPython triggers automatic collection in whichever thread happens to allocate. If a collection
on a worker thread frees an unreachable Qt object, its C++ destructor runs on that worker. The
destructor takes Qt's connection lock and then needs the GIL, while the GUI thread may hold the
GIL and be waiting for the same lock: a deadlock (observed while a model was loading during
start-up). Disabling automatic collection and collecting from a GUI-thread timer removes the
race. Reference counting still frees most objects immediately; only cycles wait for the timer.
"""

from __future__ import annotations

import gc
from typing import Final

from PySide6.QtCore import QObject, QTimer

INTERVAL_MS: Final = 1000


class MainThreadGarbageCollector(QObject):
    def __init__(self, interval_ms: int = INTERVAL_MS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.collect)
        self._was_enabled: bool | None = None

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        if self.active:
            return
        self._was_enabled = gc.isenabled()
        gc.disable()
        self._timer.start()

    def collect(self) -> int:
        """Collect the generations whose allocation counts exceed their thresholds."""
        collected = 0
        count0, count1, count2 = gc.get_count()
        threshold0, threshold1, threshold2 = gc.get_threshold()
        if count0 > threshold0:
            collected += gc.collect(0)
            if count1 > threshold1:
                collected += gc.collect(1)
                if count2 > threshold2:
                    collected += gc.collect(2)
        return collected

    def stop(self) -> None:
        """Collect everything on this thread, then restore automatic collection."""
        self._timer.stop()
        gc.collect()
        if self._was_enabled:
            gc.enable()
        self._was_enabled = None
