"""Simulation scenario catalogue and ground-truth labels.

Every scenario is synthetic. Fault parameters are chosen to produce plausible, recognisable
signatures for testing and for Phase 3 dataset generation; they are not calibrated to any
specific vehicle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from smartdrive.config.constants import FaultCategory


class ScenarioId(StrEnum):
    NORMAL = "normal_driving"
    IDLE = "engine_idling"
    HIGHWAY = "highway_driving"
    URBAN = "urban_driving"
    HEAVY_TRAFFIC = "heavy_traffic"
    RAPID_ACCELERATION = "rapid_acceleration"
    OVERHEATING = "engine_overheating"
    COOLING = "cooling_system_abnormality"
    LUBRICATION = "lubrication_abnormality"
    ELECTRICAL = "electrical_abnormality"
    FUEL_SYSTEM = "fuel_system_abnormality"
    SENSOR_FAILURE = "sensor_failure"
    MISSING_SENSORS = "missing_sensor_values"
    CONNECTION_LOSS = "intermittent_connection_loss"
    MULTIPLE = "multiple_abnormalities"


class DrivingPattern(StrEnum):
    MIXED = "mixed"
    IDLE = "idle"
    HIGHWAY = "highway"
    URBAN = "urban"
    HEAVY_TRAFFIC = "heavy_traffic"
    RAPID_ACCELERATION = "rapid_acceleration"


class FaultKind(StrEnum):
    OVERHEATING = "overheating"
    COOLING_DEGRADATION = "cooling_degradation"
    LOW_OIL_PRESSURE = "low_oil_pressure"
    CHARGING_FAILURE = "charging_failure"
    FUEL_DELIVERY = "fuel_delivery"
    COOLANT_SENSOR_FAILURE = "coolant_sensor_failure"


FAULT_CATEGORY: Final[Mapping[FaultKind, FaultCategory]] = {
    FaultKind.OVERHEATING: FaultCategory.COOLING,
    FaultKind.COOLING_DEGRADATION: FaultCategory.COOLING,
    FaultKind.LOW_OIL_PRESSURE: FaultCategory.LUBRICATION,
    FaultKind.CHARGING_FAILURE: FaultCategory.ELECTRICAL,
    FaultKind.FUEL_DELIVERY: FaultCategory.FUEL,
    FaultKind.COOLANT_SENSOR_FAILURE: FaultCategory.SENSOR,
}


@dataclass(frozen=True, slots=True)
class FaultSpec:
    """A fault that starts at ``onset_s`` and reaches full severity over ``ramp_s``."""

    kind: FaultKind
    onset_s: float
    ramp_s: float

    def severity(self, elapsed_s: float, ramp_override_s: float | None = None) -> float:
        ramp = self.ramp_s if ramp_override_s is None else ramp_override_s
        if elapsed_s < self.onset_s:
            return 0.0
        if ramp <= 0:
            return 1.0
        return min(1.0, (elapsed_s - self.onset_s) / ramp)


@dataclass(frozen=True, slots=True)
class ConnectionLossSpec:
    start_probability_per_s: float
    min_duration_s: float
    max_duration_s: float


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    id: ScenarioId
    title: str
    description: str
    pattern: DrivingPattern
    faults: tuple[FaultSpec, ...] = ()
    unsupported_sensors: frozenset[str] = frozenset()
    dropout_probability: float = 0.0
    connection_loss: ConnectionLossSpec | None = None

    @property
    def is_abnormal(self) -> bool:
        return (
            bool(self.faults)
            or self.connection_loss is not None
            or bool(self.unsupported_sensors)
            or self.dropout_probability > 0
        )


@dataclass(frozen=True, slots=True)
class SimulationLabels:
    """Ground truth for one simulated reading."""

    scenario: ScenarioId
    faults: Mapping[FaultKind, float] = field(default_factory=dict)
    connection_lost: bool = False
    dropped_sensors: tuple[str, ...] = ()
    overridden_sensors: tuple[str, ...] = ()

    @property
    def categories(self) -> frozenset[FaultCategory]:
        return frozenset(FAULT_CATEGORY[kind] for kind in self.faults)

    @property
    def is_normal(self) -> bool:
        return not self.faults and not self.connection_lost and not self.dropped_sensors


_SLOW: Final = 120.0
_OIL_SENSORS: Final = frozenset({"oil_temp_c", "oil_pressure_kpa"})

SCENARIOS: Final[Mapping[ScenarioId, ScenarioDefinition]] = {
    s.id: s
    for s in (
        ScenarioDefinition(
            ScenarioId.NORMAL,
            "Normal driving",
            "Mixed city and suburban driving with a healthy vehicle.",
            DrivingPattern.MIXED,
        ),
        ScenarioDefinition(
            ScenarioId.IDLE,
            "Engine idling",
            "Stationary vehicle with the engine running at idle.",
            DrivingPattern.IDLE,
        ),
        ScenarioDefinition(
            ScenarioId.HIGHWAY,
            "Highway driving",
            "Sustained cruising between 85 and 110 km/h.",
            DrivingPattern.HIGHWAY,
        ),
        ScenarioDefinition(
            ScenarioId.URBAN,
            "Urban driving",
            "Stop-and-go city driving up to 55 km/h.",
            DrivingPattern.URBAN,
        ),
        ScenarioDefinition(
            ScenarioId.HEAVY_TRAFFIC,
            "Heavy traffic",
            "Crawling traffic below 20 km/h with frequent stops and little airflow.",
            DrivingPattern.HEAVY_TRAFFIC,
        ),
        ScenarioDefinition(
            ScenarioId.RAPID_ACCELERATION,
            "Rapid acceleration",
            "Repeated full-throttle acceleration with late gear changes.",
            DrivingPattern.RAPID_ACCELERATION,
        ),
        ScenarioDefinition(
            ScenarioId.OVERHEATING,
            "Engine overheating",
            "Coolant loss develops gradually; temperature climbs beyond the normal band.",
            DrivingPattern.MIXED,
            faults=(FaultSpec(FaultKind.OVERHEATING, onset_s=30.0, ramp_s=_SLOW),),
        ),
        ScenarioDefinition(
            ScenarioId.COOLING,
            "Cooling system abnormality",
            "Radiator fan failure and reduced radiator efficiency; most visible at low speed.",
            DrivingPattern.HEAVY_TRAFFIC,
            faults=(FaultSpec(FaultKind.COOLING_DEGRADATION, onset_s=20.0, ramp_s=_SLOW),),
        ),
        ScenarioDefinition(
            ScenarioId.LUBRICATION,
            "Lubrication abnormality",
            "Oil pressure falls progressively while oil temperature rises (simulated only).",
            DrivingPattern.URBAN,
            faults=(FaultSpec(FaultKind.LOW_OIL_PRESSURE, onset_s=30.0, ramp_s=_SLOW),),
        ),
        ScenarioDefinition(
            ScenarioId.ELECTRICAL,
            "Electrical abnormality",
            "Alternator output degrades; control module voltage drops toward battery level.",
            DrivingPattern.MIXED,
            faults=(FaultSpec(FaultKind.CHARGING_FAILURE, onset_s=20.0, ramp_s=90.0),),
        ),
        ScenarioDefinition(
            ScenarioId.FUEL_SYSTEM,
            "Fuel system abnormality",
            "Restricted fuel delivery causes unstable engine speed, power loss and higher "
            "fuel use.",
            DrivingPattern.MIXED,
            faults=(FaultSpec(FaultKind.FUEL_DELIVERY, onset_s=30.0, ramp_s=90.0),),
        ),
        ScenarioDefinition(
            ScenarioId.SENSOR_FAILURE,
            "Sensor failure",
            "The coolant temperature sensor becomes intermittent, then reads -40 °C "
            "(open circuit).",
            DrivingPattern.MIXED,
            faults=(FaultSpec(FaultKind.COOLANT_SENSOR_FAILURE, onset_s=20.0, ramp_s=60.0),),
        ),
        ScenarioDefinition(
            ScenarioId.MISSING_SENSORS,
            "Missing sensor values",
            "Oil sensors are not supported by this vehicle and other readings drop out at random.",
            DrivingPattern.MIXED,
            unsupported_sensors=_OIL_SENSORS,
            dropout_probability=0.08,
        ),
        ScenarioDefinition(
            ScenarioId.CONNECTION_LOSS,
            "Intermittent connection loss",
            "The data link drops for a few seconds at random intervals.",
            DrivingPattern.MIXED,
            connection_loss=ConnectionLossSpec(0.02, 2.0, 6.0),
        ),
        ScenarioDefinition(
            ScenarioId.MULTIPLE,
            "Multiple simultaneous abnormalities",
            "Overheating and charging failure develop together with occasional data dropouts.",
            DrivingPattern.URBAN,
            faults=(
                FaultSpec(FaultKind.OVERHEATING, onset_s=30.0, ramp_s=_SLOW),
                FaultSpec(FaultKind.CHARGING_FAILURE, onset_s=45.0, ramp_s=90.0),
            ),
            dropout_probability=0.03,
        ),
    )
}
