"""Trip replay as a telemetry source.

The recorded samples are loaded once and never modified. Playback time advances with the
wall clock multiplied by the playback speed, and only samples whose original offset is at or
before the playback position are emitted, so recorded data from the future can never enter a
diagnostic window. Frames carry the original recording timestamps; their data source is
``REPLAY``. A replay never touches OBD-II hardware.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from smartdrive.config.constants import DataSource
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.services.data_source import TelemetryFrame, TelemetrySource

PLAYBACK_SPEEDS: Final = (0.5, 1.0, 2.0, 4.0)
MAX_FRAMES_PER_READ: Final = 400


@dataclass(frozen=True, slots=True)
class ReplayPosition:
    position_s: float
    duration_s: float
    index: int
    total: int
    finished: bool

    @property
    def progress(self) -> float:
        return 1.0 if self.duration_s <= 0 else min(1.0, self.position_s / self.duration_s)


class ReplaySource(TelemetrySource):
    data_source = DataSource.REPLAY

    def __init__(
        self,
        samples: Sequence[TelemetrySample],
        *,
        session_id: int,
        original_source: DataSource,
        speed: float = 1.0,
    ) -> None:
        if not samples:
            raise ValueError("A trip without telemetry cannot be replayed.")
        ordered = sorted(samples, key=lambda s: s.timestamp)
        start = ordered[0].timestamp
        self._samples: tuple[TelemetrySample, ...] = tuple(ordered)
        self._offsets: tuple[float, ...] = tuple(
            (s.timestamp - start).total_seconds() for s in ordered
        )
        self.session_id = session_id
        self.original_source = original_source
        self._speed = 1.0
        self.speed = speed
        self._position = 0.0
        self._next_index = 0

    @property
    def description(self) -> str:
        return f"Replay of trip {self.session_id} ({self.original_source.value} recording)"

    @property
    def duration_s(self) -> float:
        return self._offsets[-1]

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        if value not in PLAYBACK_SPEEDS:
            raise ValueError(f"Playback speed must be one of {PLAYBACK_SPEEDS}")
        self._speed = value

    @property
    def finished(self) -> bool:
        return self._next_index >= len(self._samples)

    def position(self) -> ReplayPosition:
        return ReplayPosition(
            position_s=min(self._position, self.duration_s),
            duration_s=self.duration_s,
            index=self._next_index,
            total=len(self._samples),
            finished=self.finished,
        )

    def seek(self, position_s: float) -> None:
        """Jump to ``position_s``. The next read emits the first sample at or after it."""
        target = min(max(0.0, position_s), self.duration_s)
        self._position = target
        self._next_index = bisect.bisect_left(self._offsets, target)

    def open(self) -> None:
        self.seek(0.0)

    def close(self) -> None:
        pass

    def read(self, interval_s: float) -> TelemetryFrame:
        frames = self.read_frames(interval_s)
        return frames[-1] if frames else self._empty()

    def read_frames(self, interval_s: float) -> list[TelemetryFrame]:
        if self.finished:
            return []
        self._position += max(0.0, interval_s) * self._speed
        frames: list[TelemetryFrame] = []
        while (
            self._next_index < len(self._samples)
            and self._offsets[self._next_index] <= self._position
            and len(frames) < MAX_FRAMES_PER_READ
        ):
            index = self._next_index
            frames.append(
                TelemetryFrame(
                    source=DataSource.REPLAY,
                    elapsed_s=self._offsets[index],
                    sample=self._samples[index],
                )
            )
            self._next_index += 1
        return frames

    def _empty(self) -> TelemetryFrame:
        return TelemetryFrame(source=DataSource.REPLAY, elapsed_s=self._position, sample=None)
