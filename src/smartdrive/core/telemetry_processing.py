"""Shared telemetry validation pipeline used by every data source.

Readings outside the physically plausible range of a sensor, or non-finite numbers, are treated
as invalid: the value becomes *missing* (``None``) and the sensor is reported in ``rejected``.
Nothing is ever replaced by an invented value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import cache

from smartdrive.models.telemetry import SENSOR_FIELDS, TelemetrySample


@dataclass(frozen=True, slots=True)
class ProcessedReading:
    sample: TelemetrySample
    rejected: tuple[str, ...]

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(k for k in SENSOR_FIELDS if getattr(self.sample, k) is None)


@cache
def sensor_bounds() -> dict[str, tuple[float, float]]:
    """Plausibility bounds, read from the TelemetrySample field constraints (single source)."""
    bounds: dict[str, tuple[float, float]] = {}
    for name in SENSOR_FIELDS:
        low, high = -math.inf, math.inf
        for constraint in TelemetrySample.model_fields[name].metadata:
            if (ge := getattr(constraint, "ge", None)) is not None:
                low = float(ge)
            if (le := getattr(constraint, "le", None)) is not None:
                high = float(le)
        bounds[name] = (low, high)
    return bounds


def build_sample(
    timestamp: datetime,
    raw: Mapping[str, float | None],
    *,
    fuel_rate_estimated: bool = False,
) -> ProcessedReading:
    unknown = set(raw) - set(SENSOR_FIELDS)
    if unknown:
        raise KeyError(f"Unknown telemetry fields: {sorted(unknown)}")
    values: dict[str, float | None] = {}
    rejected: list[str] = []
    for name, (low, high) in sensor_bounds().items():
        value = raw.get(name)
        if value is None:
            values[name] = None
        elif not math.isfinite(value) or not low <= value <= high:
            values[name] = None
            rejected.append(name)
        else:
            values[name] = float(value)
    sample = TelemetrySample(
        timestamp=timestamp,
        fuel_rate_estimated=fuel_rate_estimated and values["fuel_rate_lph"] is not None,
        **values,
    )
    return ProcessedReading(sample=sample, rejected=tuple(rejected))
