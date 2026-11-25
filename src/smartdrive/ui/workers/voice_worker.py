"""Speaks announcements one at a time on a dedicated thread.

The speech engine is created on this thread (COM-based SAPI requires it on Windows) and only
used here. Announcements are queued in a bounded, de-duplicated queue and spoken sequentially,
so they never overlap and the GUI thread never waits for speech.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from smartdrive.services.voice import (
    Announcement,
    AnnouncementQueue,
    SpeechBackend,
    create_backend,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VoiceConfig:
    enabled: bool
    voice_id: str | None
    rate: int
    volume: float
    cooldown_s: float


class VoiceWorker(QObject):
    ready = Signal(bool, str, object)  # available, reason, voices
    spoken = Signal(str)  # announcement key
    failed = Signal(str)

    def __init__(self, backend_factory: Callable[[], SpeechBackend] = create_backend) -> None:
        super().__init__()
        self._factory = backend_factory
        self._backend: SpeechBackend | None = None
        self._queue = AnnouncementQueue()
        self._config = VoiceConfig(False, None, 175, 1.0, 300.0)
        self._closed = False
        self._draining = False

    @property
    def queue(self) -> AnnouncementQueue:
        return self._queue

    @Slot()
    def start(self) -> None:
        self._backend = self._factory()
        voices = self._backend.voices() if self._backend.available else []
        self.ready.emit(self._backend.available, self._backend.unavailable_reason or "", voices)

    @Slot(object)
    def configure(self, config: object) -> None:
        if isinstance(config, VoiceConfig):
            self._config = config
            self._queue.cooldown_s = config.cooldown_s
            if not config.enabled:
                self._queue.clear()

    @Slot(object)
    def enqueue(self, announcement: object) -> None:
        if self._closed or not isinstance(announcement, Announcement):
            return
        if not self._config.enabled:
            return
        if self._queue.push(announcement) and not self._draining:
            self._draining = True
            QTimer.singleShot(0, self._drain)

    @Slot(str)
    def test_voice(self, text: str) -> None:
        if self._closed:
            return
        self._speak(Announcement("test", text, priority=10))

    def _drain(self) -> None:
        while not self._closed:
            item = self._queue.pop()
            if item is None:
                break
            self._speak(item)
        self._draining = False

    def _speak(self, item: Announcement) -> None:
        backend = self._backend
        if backend is None or not backend.available:
            self.failed.emit(
                backend.unavailable_reason if backend else "Voice output has not started."
            )
            return
        try:
            backend.speak(
                item.text,
                voice_id=self._config.voice_id,
                rate=self._config.rate,
                volume=self._config.volume,
            )
        except Exception as exc:
            logger.warning("Speech failed", exc_info=True)
            self.failed.emit(f"Voice announcement failed: {exc}")
            return
        self.spoken.emit(item.key)

    @Slot()
    def shutdown(self) -> None:
        self._closed = True
        self._queue.clear()
        if self._backend is not None:
            self._backend.close()
            self._backend = None
