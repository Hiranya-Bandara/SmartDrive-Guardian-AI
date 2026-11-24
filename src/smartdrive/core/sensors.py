"""Metadata for every monitored telemetry parameter, shared by charts, gauges and tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from smartdrive.config.constants import UnitSystem
from smartdrive.core.units import MISSING_TEXT, Quantity, convert, unit_label
from smartdrive.models.telemetry import SENSOR_FIELDS


@dataclass(frozen=True, slots=True)
class SensorSpec:
    key: str
    label: str
    quantity: Quantity
    decimals: int
    display_min: float
    display_max: float

    def unit(self, system: UnitSystem) -> str:
        return unit_label(self.quantity, system)

    def to_display(self, value: float, system: UnitSystem) -> float:
        return convert(value, self.quantity, system)

    def display_range(self, system: UnitSystem) -> tuple[float, float]:
        return self.to_display(self.display_min, system), self.to_display(self.display_max, system)

    def format(self, value: float | None, system: UnitSystem, *, with_unit: bool = True) -> str:
        if value is None:
            return MISSING_TEXT
        text = f"{self.to_display(value, system):.{self.decimals}f}"
        return f"{text} {self.unit(system)}" if with_unit else text


SENSORS: Final[tuple[SensorSpec, ...]] = (
    SensorSpec("coolant_temp_c", "Engine coolant temperature", Quantity.TEMPERATURE, 0, 0, 130),
    SensorSpec("rpm", "Engine speed", Quantity.ROTATION, 0, 0, 7000),
    SensorSpec("speed_kph", "Vehicle speed", Quantity.SPEED, 0, 0, 200),
    SensorSpec("fuel_level_pct", "Fuel level", Quantity.PERCENT, 0, 0, 100),
    SensorSpec("engine_load_pct", "Engine load", Quantity.PERCENT, 0, 0, 100),
    SensorSpec("throttle_pct", "Throttle position", Quantity.PERCENT, 0, 0, 100),
    SensorSpec("intake_air_temp_c", "Intake air temperature", Quantity.TEMPERATURE, 0, -10, 80),
    SensorSpec("control_module_voltage_v", "Control module voltage", Quantity.VOLTAGE, 2, 10, 16),
    SensorSpec("oil_temp_c", "Engine oil temperature", Quantity.TEMPERATURE, 0, 0, 150),
    SensorSpec("oil_pressure_kpa", "Engine oil pressure", Quantity.PRESSURE, 0, 0, 700),
    SensorSpec("fuel_rate_lph", "Fuel consumption rate", Quantity.FLOW, 1, 0, 30),
)

SENSOR_BY_KEY: Final = {spec.key: spec for spec in SENSORS}

if tuple(SENSOR_BY_KEY) != SENSOR_FIELDS:  # pragma: no cover - import-time consistency guard
    raise RuntimeError("Sensor metadata is out of sync with TelemetrySample fields.")
