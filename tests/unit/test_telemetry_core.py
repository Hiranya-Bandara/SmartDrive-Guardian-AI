from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from smartdrive.config.constants import UnitSystem
from smartdrive.core.monitoring import StalenessTracker, TelemetryBuffer
from smartdrive.core.sensors import SENSOR_BY_KEY, SENSORS
from smartdrive.core.telemetry_processing import build_sample, sensor_bounds
from smartdrive.core.units import MISSING_TEXT, Quantity, convert, unit_label
from smartdrive.models.telemetry import SENSOR_FIELDS, TelemetrySample

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class TestUnits:
    @pytest.mark.parametrize(
        ("quantity", "metric", "imperial"),
        [
            (Quantity.TEMPERATURE, 100.0, 212.0),
            (Quantity.SPEED, 160.9344, 100.0),
            (Quantity.PRESSURE, 6.894757, 1.0),
            (Quantity.FLOW, 3.785411784, 1.0),
            (Quantity.ROTATION, 2500.0, 2500.0),
        ],
    )
    def test_imperial_conversion(self, quantity: Quantity, metric: float, imperial: float) -> None:
        assert convert(metric, quantity, UnitSystem.IMPERIAL) == pytest.approx(imperial)
        assert convert(metric, quantity, UnitSystem.METRIC) == metric

    def test_unit_labels(self) -> None:
        assert unit_label(Quantity.TEMPERATURE, UnitSystem.IMPERIAL) == "°F"
        assert unit_label(Quantity.SPEED, UnitSystem.METRIC) == "km/h"

    def test_missing_values_format_as_dash_not_zero(self) -> None:
        spec = SENSOR_BY_KEY["oil_pressure_kpa"]
        assert spec.format(None, UnitSystem.METRIC) == MISSING_TEXT
        assert spec.format(250.0, UnitSystem.METRIC) == "250 kPa"

    def test_sensor_metadata_covers_every_telemetry_field(self) -> None:
        assert tuple(s.key for s in SENSORS) == SENSOR_FIELDS


class TestTelemetryProcessing:
    def test_bounds_come_from_model_constraints(self) -> None:
        assert sensor_bounds()["rpm"] == (0.0, 16_384.0)
        assert sensor_bounds()["coolant_temp_c"] == (-40.0, 215.0)

    def test_valid_values_pass_through(self) -> None:
        result = build_sample(NOW, {"rpm": 900.0, "speed_kph": 0.0})
        assert result.sample.rpm == 900.0
        assert result.sample.speed_kph == 0.0
        assert result.rejected == ()

    def test_missing_values_stay_missing(self) -> None:
        result = build_sample(NOW, {"rpm": None})
        assert result.sample.rpm is None
        assert "oil_pressure_kpa" in result.missing
        assert result.rejected == ()

    @pytest.mark.parametrize("value", [-5.0, 99_999.0, math.nan, math.inf])
    def test_implausible_values_are_rejected_not_clamped(self, value: float) -> None:
        result = build_sample(NOW, {"rpm": value})
        assert result.sample.rpm is None
        assert result.rejected == ("rpm",)

    def test_unknown_fields_raise(self) -> None:
        with pytest.raises(KeyError):
            build_sample(NOW, {"boost_kpa": 10.0})

    def test_fuel_rate_estimate_flag_requires_a_value(self) -> None:
        assert not build_sample(NOW, {}, fuel_rate_estimated=True).sample.fuel_rate_estimated
        assert build_sample(
            NOW, {"fuel_rate_lph": 2.0}, fuel_rate_estimated=True
        ).sample.fuel_rate_estimated


def _sample(**values: float | None) -> TelemetrySample:
    return TelemetrySample(timestamp=NOW, **values)  # type: ignore[arg-type]


class TestTelemetryBuffer:
    def test_capacity_bounds_memory(self) -> None:
        buffer = TelemetryBuffer(capacity=50)
        for i in range(500):
            buffer.append(float(i), _sample(rpm=float(i)))
        assert len(buffer) == 50
        times, values = buffer.window("rpm")
        assert times[0] == 450.0
        assert values[-1] == 499.0

    def test_rejects_tiny_capacity_and_out_of_order_time(self) -> None:
        with pytest.raises(ValueError):
            TelemetryBuffer(capacity=5)
        buffer = TelemetryBuffer(capacity=10)
        buffer.append(2.0, _sample(rpm=1.0))
        with pytest.raises(ValueError):
            buffer.append(1.0, _sample(rpm=1.0))

    def test_statistics_ignore_missing_values(self) -> None:
        buffer = TelemetryBuffer(capacity=20)
        for t, value in enumerate([10.0, None, 30.0, None, 20.0]):
            buffer.append(float(t), _sample(coolant_temp_c=value))
        stats = buffer.statistics("coolant_temp_c")
        assert (stats.minimum, stats.maximum, stats.average) == (10.0, 30.0, 20.0)
        assert stats.valid_count == 3
        assert stats.missing_count == 2
        assert stats.current == 20.0

    def test_missing_values_are_nan_gaps_in_series(self) -> None:
        buffer = TelemetryBuffer(capacity=20)
        buffer.append(0.0, _sample(rpm=None))
        _, values = buffer.window("rpm")
        assert math.isnan(values[0])

    def test_window_selects_recent_seconds(self) -> None:
        buffer = TelemetryBuffer(capacity=100)
        for t in range(60):
            buffer.append(float(t), _sample(rpm=float(t)))
        times, _ = buffer.window("rpm", 10)
        assert times[0] == 49.0
        assert buffer.statistics("rpm", 10).minimum == 49.0

    def test_empty_statistics(self) -> None:
        stats = TelemetryBuffer(capacity=10).statistics("rpm")
        assert stats.current is None
        assert stats.average is None

    def test_clear(self) -> None:
        buffer = TelemetryBuffer(capacity=10)
        buffer.append(1.0, _sample(rpm=1.0))
        buffer.clear()
        assert len(buffer) == 0
        assert buffer.latest is None
        assert buffer.last_elapsed is None


class TestStaleness:
    def test_age_and_threshold(self) -> None:
        tracker = StalenessTracker()
        assert tracker.age(100.0) is None
        assert not tracker.is_stale(100.0, 5.0)
        tracker.mark(100.0)
        assert tracker.age(103.0) == pytest.approx(3.0)
        assert not tracker.is_stale(104.0, 5.0)
        assert tracker.is_stale(106.0, 5.0)
        tracker.reset()
        assert not tracker.has_data
