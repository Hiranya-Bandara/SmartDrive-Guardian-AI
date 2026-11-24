"""Display-unit conversion. Values are always stored in metric units."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from smartdrive.config.constants import UnitSystem

MISSING_TEXT: Final = "—"


class Quantity(StrEnum):
    TEMPERATURE = "temperature"
    SPEED = "speed"
    PRESSURE = "pressure"
    FLOW = "flow"
    ROTATION = "rotation"
    PERCENT = "percent"
    VOLTAGE = "voltage"


_METRIC_UNITS: Final = {
    Quantity.TEMPERATURE: "°C",
    Quantity.SPEED: "km/h",
    Quantity.PRESSURE: "kPa",
    Quantity.FLOW: "L/h",
    Quantity.ROTATION: "rpm",
    Quantity.PERCENT: "%",
    Quantity.VOLTAGE: "V",
}
_IMPERIAL_UNITS: Final = {
    **_METRIC_UNITS,
    Quantity.TEMPERATURE: "°F",
    Quantity.SPEED: "mph",
    Quantity.PRESSURE: "psi",
    Quantity.FLOW: "gal/h",
}

KM_PER_MILE: Final = 1.609344
KPA_PER_PSI: Final = 6.894757
LITRES_PER_US_GALLON: Final = 3.785411784


def unit_label(quantity: Quantity, system: UnitSystem) -> str:
    table = _IMPERIAL_UNITS if system is UnitSystem.IMPERIAL else _METRIC_UNITS
    return table[quantity]


def convert(value: float, quantity: Quantity, system: UnitSystem) -> float:
    """Convert a metric value into the requested display system."""
    if system is UnitSystem.METRIC:
        return value
    match quantity:
        case Quantity.TEMPERATURE:
            return value * 9.0 / 5.0 + 32.0
        case Quantity.SPEED:
            return value / KM_PER_MILE
        case Quantity.PRESSURE:
            return value / KPA_PER_PSI
        case Quantity.FLOW:
            return value / LITRES_PER_US_GALLON
        case _:
            return value


def distance_label(system: UnitSystem) -> str:
    return "mi" if system is UnitSystem.IMPERIAL else "km"


def convert_distance(km: float, system: UnitSystem) -> float:
    return km / KM_PER_MILE if system is UnitSystem.IMPERIAL else km
