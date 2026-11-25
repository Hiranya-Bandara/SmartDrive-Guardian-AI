"""Bounded in-memory telemetry history, statistics and staleness tracking.

Memory use is fixed: each sensor keeps at most ``capacity`` points regardless of how long
monitoring runs. Missing readings are kept as NaN so charts show gaps instead of false values.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from smartdrive.models.telemetry import SENSOR_FIELDS, TelemetrySample

MIN_CAPACITY = 10


@dataclass(frozen=True, slots=True)
class SensorStatistics:
    current: float | None
    minimum: float | None
    maximum: float | None
    average: float | None
    valid_count: int
    missing_count: int


class TelemetryBuffer:
    def __init__(self, capacity: int) -> None:
        if capacity < MIN_CAPACITY:
            raise ValueError(f"capacity must be at least {MIN_CAPACITY}")
        self._capacity = capacity
        self._times: deque[float] = deque(maxlen=capacity)
        self._values: dict[str, deque[float]] = {
            key: deque(maxlen=capacity) for key in SENSOR_FIELDS
        }
        self._latest: TelemetrySample | None = None

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def latest(self) -> TelemetrySample | None:
        return self._latest

    @property
    def last_elapsed(self) -> float | None:
        return self._times[-1] if self._times else None

    def __len__(self) -> int:
        return len(self._times)

    def append(self, elapsed_s: float, sample: TelemetrySample) -> None:
        if self._times and elapsed_s < self._times[-1]:
            raise ValueError("Telemetry must be appended in time order.")
        self._times.append(elapsed_s)
        for key, series in self._values.items():
            value = getattr(sample, key)
            series.append(math.nan if value is None else float(value))
        self._latest = sample

    def clear(self) -> None:
        self._times.clear()
        for series in self._values.values():
            series.clear()
        self._latest = None

    def window(self, key: str, seconds: float | None = None) -> tuple[list[float], list[float]]:
        """Return ``(times, values)`` for the last ``seconds`` (all retained data if None)."""
        times = list(self._times)
        values = list(self._values[key])
        if seconds is None or not times:
            return times, values
        cutoff = times[-1] - seconds
        start = next((i for i, t in enumerate(times) if t >= cutoff), len(times))
        return times[start:], values[start:]

    def snapshot(self, seconds: float) -> tuple[list[float], dict[str, list[float]]]:
        """Copy of the last ``seconds`` of every series (for handing to a worker thread)."""
        times = list(self._times)
        if not times:
            return [], {key: [] for key in self._values}
        cutoff = times[-1] - seconds
        start = next((i for i, t in enumerate(times) if t >= cutoff), len(times))
        return times[start:], {key: list(series)[start:] for key, series in self._values.items()}

    def statistics(self, key: str, seconds: float | None = None) -> SensorStatistics:
        _, values = self.window(key, seconds)
        valid = [v for v in values if not math.isnan(v)]
        latest = getattr(self._latest, key) if self._latest is not None else None
        return SensorStatistics(
            current=latest,
            minimum=min(valid) if valid else None,
            maximum=max(valid) if valid else None,
            average=sum(valid) / len(valid) if valid else None,
            valid_count=len(valid),
            missing_count=len(values) - len(valid),
        )


class StalenessTracker:
    """Tracks the monotonic time of the last successful reading."""

    def __init__(self) -> None:
        self._last: float | None = None

    @property
    def has_data(self) -> bool:
        return self._last is not None

    def mark(self, now: float) -> None:
        self._last = now

    def reset(self) -> None:
        self._last = None

    def age(self, now: float) -> float | None:
        return None if self._last is None else max(0.0, now - self._last)

    def is_stale(self, now: float, threshold_s: float) -> bool:
        age = self.age(now)
        return age is not None and age > threshold_s
