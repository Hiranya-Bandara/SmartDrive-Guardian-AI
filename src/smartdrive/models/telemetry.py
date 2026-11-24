"""Telemetry sample model shared by simulation, live OBD-II and replay sources.

A missing sensor is ``None`` — never zero and never an invented value.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Physically plausible bounds; values outside are rejected as sensor or transport errors.
SENSOR_FIELDS: Final = (
    "coolant_temp_c",
    "rpm",
    "speed_kph",
    "fuel_level_pct",
    "engine_load_pct",
    "throttle_pct",
    "intake_air_temp_c",
    "control_module_voltage_v",
    "oil_temp_c",
    "oil_pressure_kpa",
    "fuel_rate_lph",
)


class TelemetrySample(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sensor_fields: ClassVar[tuple[str, ...]] = SENSOR_FIELDS

    timestamp: datetime
    coolant_temp_c: float | None = Field(default=None, ge=-40, le=215)
    rpm: float | None = Field(default=None, ge=0, le=16_384)
    speed_kph: float | None = Field(default=None, ge=0, le=255)
    fuel_level_pct: float | None = Field(default=None, ge=0, le=100)
    engine_load_pct: float | None = Field(default=None, ge=0, le=100)
    throttle_pct: float | None = Field(default=None, ge=0, le=100)
    intake_air_temp_c: float | None = Field(default=None, ge=-40, le=215)
    control_module_voltage_v: float | None = Field(default=None, ge=0, le=65.535)
    oil_temp_c: float | None = Field(default=None, ge=-40, le=215)
    oil_pressure_kpa: float | None = Field(default=None, ge=0, le=1000)
    fuel_rate_lph: float | None = Field(default=None, ge=0, le=3276.75)
    fuel_rate_estimated: bool = False
    extra: dict[str, float] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Telemetry timestamps must be timezone-aware.")
        return value

    def available_sensors(self) -> list[str]:
        return [name for name in SENSOR_FIELDS if getattr(self, name) is not None]

    def to_row(self) -> dict[str, Any]:
        return self.model_dump()
