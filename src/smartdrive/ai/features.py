"""Feature schema ``fs-1``: numeric features computed from a :class:`TelemetryWindow`.

Features use telemetry only. Scenario identifiers, labels and future readings never enter the
feature vector. Missing information is NaN and is imputed inside the trained pipeline, while
explicit completeness features let the model see how much data it had.
"""

from __future__ import annotations

import warnings
from typing import Final

import numpy as np

from smartdrive.core.sensors import SENSOR_BY_KEY
from smartdrive.core.telemetry_window import TelemetryWindow
from smartdrive.models.telemetry import SENSOR_FIELDS

FEATURE_SCHEMA_VERSION: Final = "fs-1"
RECENT_SECONDS: Final = 10.0
RUNNING_RPM: Final = 600.0

_STATS: Final = ("last", "recent_mean", "mean", "std", "min", "max", "slope_per_min")
_DERIVED: Final = (
    "oil_pressure_per_krpm",
    "fuel_rate_per_load",
    "voltage_while_running",
    "coolant_minus_oil",
    "rpm_jitter",
    "coolant_max_jump",
    "coolant_fraction_above_100",
    "window_coverage",
)

FEATURE_NAMES: Final[tuple[str, ...]] = (
    *(f"{sensor}__{stat}" for sensor in SENSOR_FIELDS for stat in _STATS),
    *(f"{sensor}__completeness" for sensor in SENSOR_FIELDS),
    *_DERIVED,
)


def _nan_stat(func: str, values: np.ndarray) -> float:
    present = values[~np.isnan(values)]
    if present.size == 0:
        return float("nan")
    return float(getattr(np, func)(present))


def _ratio_mean(numerator: np.ndarray, denominator: np.ndarray, floor: float) -> float:
    mask = ~np.isnan(numerator) & ~np.isnan(denominator) & (denominator > floor)
    if not mask.any():
        return float("nan")
    return float(np.mean(numerator[mask] / denominator[mask]))


def extract_features(window: TelemetryWindow) -> np.ndarray:
    """Return a float64 vector ordered as :data:`FEATURE_NAMES`."""
    out: list[float] = []
    quality = window.quality()
    for sensor in SENSOR_FIELDS:
        values = window.values[sensor]
        recent = window.recent(sensor, RECENT_SECONDS)
        latest = window.latest(sensor)
        slope = window.slope_per_minute(sensor)
        out.extend(
            [
                float("nan") if latest is None else latest,
                float(recent.mean()) if recent.size else float("nan"),
                _nan_stat("mean", values),
                _nan_stat("std", values),
                _nan_stat("min", values),
                _nan_stat("max", values),
                float("nan") if slope is None else slope,
            ]
        )
    out.extend(quality.completeness[sensor] for sensor in SENSOR_FIELDS)

    v = window.values
    rpm = v["rpm"]
    running = np.where(rpm > RUNNING_RPM, v["control_module_voltage_v"], np.nan)
    coolant = v["coolant_temp_c"]
    coolant_present = coolant[~np.isnan(coolant)]
    rpm_present = rpm[~np.isnan(rpm)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        out.extend(
            [
                _ratio_mean(v["oil_pressure_kpa"], rpm / 1000.0, RUNNING_RPM / 1000.0),
                _ratio_mean(v["fuel_rate_lph"], v["engine_load_pct"], 5.0),
                _nan_stat("mean", running),
                _nan_stat("mean", coolant - v["oil_temp_c"]),
                float(np.std(np.diff(rpm_present))) if rpm_present.size > 2 else float("nan"),
                float(np.max(np.abs(np.diff(coolant_present))))
                if coolant_present.size > 1
                else float("nan"),
                float(np.mean(coolant_present > 100.0)) if coolant_present.size else float("nan"),
                quality.coverage,
            ]
        )
    vector = np.asarray(out, dtype=np.float64)
    if vector.shape != (len(FEATURE_NAMES),):  # pragma: no cover - schema guard
        raise RuntimeError("Feature vector does not match the feature schema.")
    return vector


_STAT_TEXT: Final = {
    "last": "latest",
    "recent_mean": "10 s average",
    "mean": "60 s average",
    "std": "variability (60 s)",
    "min": "minimum (60 s)",
    "max": "maximum (60 s)",
    "slope_per_min": "trend per minute",
    "completeness": "data completeness",
}
_DERIVED_TEXT: Final = {
    "oil_pressure_per_krpm": "Oil pressure per 1000 rpm",
    "fuel_rate_per_load": "Fuel use per unit of engine load",
    "voltage_while_running": "Voltage while the engine runs",
    "coolant_minus_oil": "Coolant minus oil temperature",
    "rpm_jitter": "Second-to-second engine speed variation",
    "coolant_max_jump": "Largest coolant reading jump",
    "coolant_fraction_above_100": "Share of time coolant above 100 °C",
    "window_coverage": "Share of the minute with readings",
}


def describe_feature(name: str) -> str:
    """Human-readable feature name for explanations."""
    if name in _DERIVED_TEXT:
        return _DERIVED_TEXT[name]
    sensor, _, stat = name.partition("__")
    spec = SENSOR_BY_KEY.get(sensor)
    label = spec.label if spec else sensor
    return f"{label} — {_STAT_TEXT.get(stat, stat)}"
