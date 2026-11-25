"""What a connected vehicle can report, derived from its supported-PID bitmaps."""

from __future__ import annotations

from dataclasses import dataclass

from smartdrive.models.telemetry import SENSOR_FIELDS
from smartdrive.obd.pids import DATA_PIDS, NOT_AVAILABLE_OVER_OBD, PidSpec


@dataclass(frozen=True, slots=True)
class VehicleCapabilities:
    supported_pids: frozenset[int]

    @property
    def pollable(self) -> tuple[PidSpec, ...]:
        """SmartDrive parameters the vehicle supports, in a stable order."""
        return tuple(spec for spec in DATA_PIDS if spec.pid in self.supported_pids)

    @property
    def unsupported(self) -> tuple[PidSpec, ...]:
        return tuple(spec for spec in DATA_PIDS if spec.pid not in self.supported_pids)

    @property
    def available_sample_fields(self) -> tuple[str, ...]:
        return tuple(s.sample_field for s in self.pollable if s.sample_field is not None)

    @property
    def missing_sample_fields(self) -> tuple[str, ...]:
        """Monitored sensors this vehicle cannot provide (including oil pressure, never on OBD)."""
        available = set(self.available_sample_fields)
        return tuple(name for name in SENSOR_FIELDS if name not in available)

    @property
    def sensor_count(self) -> int:
        return len(self.pollable)

    def describe_missing(self) -> list[str]:
        notes: list[str] = []
        for name in self.missing_sample_fields:
            reason = (
                "not defined in generic OBD-II"
                if name in NOT_AVAILABLE_OVER_OBD
                else "not reported by this vehicle"
            )
            notes.append(f"{name}: {reason}")
        return notes
