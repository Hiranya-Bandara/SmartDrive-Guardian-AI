"""Fixed-length, time-binned view of recent telemetry shared by rules and feature extraction.

Readings are resampled onto a 1-second grid (the last reading in each second wins). This makes
features independent of the refresh interval, so data recorded at 1 Hz (training) and data
polled at 100 ms (runtime) describe the same signal. Missing readings stay NaN.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from smartdrive.models.telemetry import SENSOR_FIELDS, TelemetrySample

WINDOW_SECONDS: Final = 60
BIN_SECONDS: Final = 1.0
MIN_SAMPLES: Final = 20
MIN_COVERAGE: Final = 0.5
MIN_CORE_COMPLETENESS: Final = 0.5
CORE_SENSORS: Final = (
    "coolant_temp_c",
    "rpm",
    "speed_kph",
    "engine_load_pct",
    "control_module_voltage_v",
)

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class DataQuality:
    sample_count: int
    coverage: float
    completeness: dict[str, float]
    sufficient: bool
    reason: str

    @property
    def overall_completeness(self) -> float:
        return float(np.mean([self.completeness[k] for k in CORE_SENSORS]))


@dataclass(frozen=True)
class TelemetryWindow:
    """``times`` are bin start offsets (seconds, ascending); ``values[sensor]`` align with them."""

    end_elapsed_s: float
    times: FloatArray
    values: dict[str, FloatArray]
    sample_count: int
    window_s: int = WINDOW_SECONDS

    @classmethod
    def from_samples(
        cls,
        samples: Iterable[tuple[float, TelemetrySample]],
        *,
        window_s: int = WINDOW_SECONDS,
    ) -> TelemetryWindow:
        """Build a window from ``(elapsed_s, sample)`` pairs; only the last ``window_s`` count."""
        times: list[float] = []
        series: dict[str, list[float]] = {key: [] for key in SENSOR_FIELDS}
        for elapsed, sample in samples:
            times.append(elapsed)
            for key in SENSOR_FIELDS:
                value = getattr(sample, key)
                series[key].append(math.nan if value is None else float(value))
        return cls.from_series(times, series, window_s=window_s)

    @classmethod
    def from_series(
        cls,
        times: list[float],
        series: dict[str, list[float]],
        *,
        window_s: int = WINDOW_SECONDS,
    ) -> TelemetryWindow:
        """Build from the column-oriented data held by ``TelemetryBuffer``."""
        if not times:
            empty = np.full(int(window_s / BIN_SECONDS), np.nan)
            return cls(
                0.0,
                np.arange(len(empty), dtype=float) - window_s,
                {k: empty.copy() for k in SENSOR_FIELDS},
                0,
                window_s,
            )
        end = times[-1]
        start = end - window_s
        bins = int(window_s / BIN_SECONDS)
        grid = {key: np.full(bins, np.nan) for key in SENSOR_FIELDS}
        count = 0
        for position, elapsed in enumerate(times):
            if elapsed <= start:
                continue
            index = min(bins - 1, int((elapsed - start) / BIN_SECONDS - 1e-9))
            count += 1
            for key in SENSOR_FIELDS:
                value = series[key][position]
                if not math.isnan(value):
                    grid[key][index] = value
        rel = np.arange(bins, dtype=float) * BIN_SECONDS - window_s
        return cls(end, rel, grid, count, window_s)

    # -- quality ------------------------------------------------------------------------------

    def occupied(self) -> NDArray[np.bool_]:
        stacked = np.vstack([self.values[k] for k in SENSOR_FIELDS])
        result: NDArray[np.bool_] = ~np.all(np.isnan(stacked), axis=0)
        return result

    def quality(self) -> DataQuality:
        occupied = self.occupied()
        bins_with_data = int(occupied.sum())
        coverage = bins_with_data / len(occupied)
        completeness = {
            key: (
                float(np.count_nonzero(~np.isnan(self.values[key][occupied]))) / bins_with_data
                if bins_with_data
                else 0.0
            )
            for key in SENSOR_FIELDS
        }
        core = float(np.mean([completeness[k] for k in CORE_SENSORS]))
        if self.sample_count < MIN_SAMPLES or bins_with_data < MIN_SAMPLES:
            reason, ok = (
                f"Only {bins_with_data} seconds of readings in the last {self.window_s} s.",
                False,
            )
        elif coverage < MIN_COVERAGE:
            reason, ok = f"Readings cover only {coverage:.0%} of the analysis window.", False
        elif core < MIN_CORE_COMPLETENESS:
            reason, ok = f"Core sensors are only {core:.0%} complete.", False
        else:
            reason, ok = "Sufficient data", True
        return DataQuality(self.sample_count, coverage, completeness, ok, reason)

    # -- helpers for rules --------------------------------------------------------------------

    def recent(self, key: str, seconds: float) -> FloatArray:
        mask = self.times >= -seconds
        values = self.values[key][mask]
        result: FloatArray = values[~np.isnan(values)]
        return result

    def latest(self, key: str) -> float | None:
        values = self.values[key]
        present = np.flatnonzero(~np.isnan(values))
        return float(values[present[-1]]) if present.size else None

    def slope_per_minute(self, key: str, seconds: float | None = None) -> float | None:
        mask = ~np.isnan(self.values[key])
        if seconds is not None:
            mask &= self.times >= -seconds
        if mask.sum() < 5:
            return None
        x = self.times[mask]
        if float(x.max() - x.min()) < 10.0:
            return None
        y = self.values[key][mask]
        slope = float(np.polyfit(x, y, 1)[0])
        return slope * 60.0
