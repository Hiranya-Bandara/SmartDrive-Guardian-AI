"""Optional offline voice announcements.

The speech backend is pyttsx3, which drives the operating system's own synthesiser (SAPI 5 on
Windows, eSpeak on Linux, NSSpeechSynthesizer on macOS). Nothing is downloaded and no cloud
service is used. If the backend cannot start, :class:`NullSpeechBackend` reports why and the
visual notifications continue to work. Voice supplements the screen; it is not a safety system.
"""

from __future__ import annotations

import logging
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

logger = logging.getLogger(__name__)

QUEUE_LIMIT: Final = 8
# A plain flag (not an inline sys.platform check) so both branches are type-checked everywhere
# and the COM handling can be tested off Windows with a stand-in comtypes module.
_IS_WINDOWS: Final = sys.platform == "win32"
MAX_TEXT_LENGTH: Final = 200


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    voice_id: str
    name: str


@dataclass(frozen=True, slots=True)
class Announcement:
    key: str
    text: str
    priority: int = 0
    """Higher numbers are spoken first (critical before warnings before reminders)."""


class SpeechBackend(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def unavailable_reason(self) -> str | None: ...

    def voices(self) -> list[VoiceInfo]: ...

    def speak(self, text: str, *, voice_id: str | None, rate: int, volume: float) -> None: ...

    def close(self) -> None: ...


class NullSpeechBackend:
    def __init__(self, reason: str = "Voice output is not available.") -> None:
        self._reason = reason

    @property
    def available(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return self._reason

    def voices(self) -> list[VoiceInfo]:
        return []

    def speak(self, text: str, *, voice_id: str | None, rate: int, volume: float) -> None:
        raise RuntimeError(self._reason)

    def close(self) -> None:
        pass


class Pyttsx3Backend:
    """Created and used on the voice worker thread only."""

    def __init__(self) -> None:
        self._com_initialised = _com_initialise()
        try:
            import pyttsx3

            self._engine: Any = pyttsx3.init()
        except Exception:
            self._release_com()
            raise

    @property
    def available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    def voices(self) -> list[VoiceInfo]:
        found = self._engine.getProperty("voices") or []
        return [VoiceInfo(str(v.id), str(getattr(v, "name", v.id))) for v in found]

    def speak(self, text: str, *, voice_id: str | None, rate: int, volume: float) -> None:
        if voice_id:
            self._engine.setProperty("voice", voice_id)
        self._engine.setProperty("rate", rate)
        self._engine.setProperty("volume", volume)
        self._engine.say(text)
        self._engine.runAndWait()

    def close(self) -> None:
        try:
            self._engine.stop()
        except Exception:  # pragma: no cover - best effort during shutdown
            logger.debug("Speech engine stop failed", exc_info=True)
        self._engine = None
        self._release_com()

    def _release_com(self) -> None:
        if self._com_initialised:
            self._com_initialised = False
            _com_uninitialise()


def _com_initialise() -> bool:
    """Initialise COM on the calling (voice worker) thread. Windows only; balanced by close()."""
    if not _IS_WINDOWS:
        return False
    try:
        import comtypes

        # Typed on Windows (comtypes installed); absent elsewhere, hence unused-ignore.
        comtypes.CoInitialize()  # type: ignore[no-untyped-call,unused-ignore]
    except Exception:
        logger.warning("COM initialisation for speech failed", exc_info=True)
        return False
    return True


def _com_uninitialise() -> None:
    try:
        import comtypes

        comtypes.CoUninitialize()  # type: ignore[no-untyped-call,unused-ignore]
    except Exception:
        logger.debug("COM uninitialisation failed", exc_info=True)


def create_backend() -> SpeechBackend:
    try:
        return Pyttsx3Backend()
    except Exception as exc:
        logger.warning("Offline speech is unavailable", extra={"error": str(exc)})
        return NullSpeechBackend(
            "No offline speech engine could be started on this computer "
            f"({type(exc).__name__}). Visual notifications are unaffected."
        )


class AnnouncementQueue:
    """Bounded, de-duplicated queue. The same key is not spoken again within the cooldown."""

    def __init__(
        self,
        cooldown_s: float = 300.0,
        *,
        limit: int = QUEUE_LIMIT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cooldown_s = cooldown_s
        self._limit = limit
        self._clock = clock
        self._items: deque[Announcement] = deque()
        self._last_spoken: dict[str, float] = {}
        self.dropped = 0
        self.suppressed = 0

    def __len__(self) -> int:
        return len(self._items)

    def push(self, announcement: Announcement) -> bool:
        if any(item.key == announcement.key for item in self._items):
            self.suppressed += 1
            return False
        last = self._last_spoken.get(announcement.key)
        if last is not None and self._clock() - last < self.cooldown_s:
            self.suppressed += 1
            return False
        if len(self._items) >= self._limit:
            lowest = min(self._items, key=lambda a: a.priority)
            if lowest.priority >= announcement.priority:
                self.dropped += 1
                return False
            self._items.remove(lowest)
            self.dropped += 1
        text = announcement.text.strip()[:MAX_TEXT_LENGTH]
        self._items.append(Announcement(announcement.key, text, announcement.priority))
        return True

    def pop(self) -> Announcement | None:
        if not self._items:
            return None
        best = max(self._items, key=lambda a: a.priority)
        self._items.remove(best)
        self._last_spoken[best.key] = self._clock()
        return best

    def clear(self) -> None:
        self._items.clear()
