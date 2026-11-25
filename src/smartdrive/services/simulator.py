"""Reproducible, time-dependent vehicle simulator.

The model is deliberately simple but coherent: a speed controller drives throttle, an automatic
gearbox maps speed to engine speed, and engine load drives heat, fuel use and oil pressure. A
thermostat regulates coolant temperature against radiator airflow. Faults modify the model
gradually, so their signatures emerge from the dynamics rather than being painted on.

Identical ``SimulationConfig`` values always produce identical output, which makes scenarios
usable as test fixtures and as Phase 3 training data with ground-truth labels.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Final

from smartdrive.config.constants import DataSource
from smartdrive.core.telemetry_processing import build_sample, sensor_bounds
from smartdrive.models.telemetry import SENSOR_FIELDS
from smartdrive.services.data_source import TelemetryFrame, TelemetrySource
from smartdrive.services.scenarios import (
    SCENARIOS,
    DrivingPattern,
    FaultKind,
    ScenarioDefinition,
    ScenarioId,
    SimulationLabels,
)

MAX_SUBSTEP_S: Final = 0.1
IDLE_RPM: Final = 750.0
REDLINE_RPM: Final = 6500.0
TANK_LITRES: Final = 45.0
THERMOSTAT_OPEN_C: Final = 85.0
THERMOSTAT_FULL_C: Final = 95.0
FAN_ON_C: Final = 97.0
COOLANT_LIMIT_C: Final = 128.0
SENSOR_OPEN_CIRCUIT_C: Final = -40.0

_GEAR_RATIOS: Final = (110.0, 65.0, 45.0, 34.0, 28.0, 23.0)  # rpm per km/h
_SHIFT_UP_KPH: Final = (18.0, 32.0, 50.0, 68.0, 88.0)
_NOISE_SD: Final = {
    "coolant_temp_c": 0.3,
    "rpm": 15.0,
    "speed_kph": 0.4,
    "fuel_level_pct": 0.1,
    "engine_load_pct": 1.0,
    "throttle_pct": 0.5,
    "intake_air_temp_c": 0.3,
    "control_module_voltage_v": 0.03,
    "oil_temp_c": 0.3,
    "oil_pressure_kpa": 3.0,
    "fuel_rate_lph": 0.05,
}


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    scenario: ScenarioId = ScenarioId.NORMAL
    seed: int = 42
    noise_scale: float = 1.0
    ambient_c: float = 30.0
    fault_development_s: float | None = None
    custom_definition: ScenarioDefinition | None = None
    initial_coolant_c: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.noise_scale <= 5.0:
            raise ValueError("noise_scale must be between 0 and 5")
        if not -30.0 <= self.ambient_c <= 50.0:
            raise ValueError("ambient_c must be between -30 and 50 °C")
        if self.fault_development_s is not None and self.fault_development_s < 0:
            raise ValueError("fault_development_s cannot be negative")
        if self.initial_coolant_c is not None and not (
            self.ambient_c - 5 <= self.initial_coolant_c <= 110
        ):
            raise ValueError("initial_coolant_c must be between ambient - 5 °C and 110 °C")
        if (self.scenario is ScenarioId.GENERATED) != (self.custom_definition is not None):
            raise ValueError("custom_definition is required for, and only for, generated sessions")

    @property
    def definition(self) -> ScenarioDefinition:
        """Catalogue scenario, or the custom definition used for dataset generation."""
        return self.custom_definition or SCENARIOS[self.scenario]


@dataclass(frozen=True, slots=True)
class SimulationStep:
    elapsed_s: float
    readings: dict[str, float | None] | None
    labels: SimulationLabels


@dataclass(slots=True)
class _VehicleState:
    speed_kph: float = 0.0
    throttle_pct: float = 0.0
    rpm: float = IDLE_RPM
    gear: int = 1
    engine_load_pct: float = 20.0
    coolant_temp_c: float = 70.0
    oil_temp_c: float = 65.0
    oil_pressure_kpa: float = 150.0
    intake_air_temp_c: float = 32.0
    voltage_v: float = 14.1
    fuel_level_pct: float = 70.0
    fuel_rate_lph: float = 1.0


@dataclass(slots=True)
class _Segment:
    end_s: float
    target_kph: float
    full_throttle: bool = False


@dataclass(slots=True)
class _DrivingProfile:
    pattern: DrivingPattern
    rng: random.Random
    segments: list[_Segment] = field(default_factory=list)
    _cursor_s: float = 0.0
    _stopped_next: bool = True

    def segment_at(self, t: float) -> _Segment:
        while not self.segments or self.segments[-1].end_s <= t:
            self._append_next()
        while self.segments[0].end_s <= t:
            self.segments.pop(0)
        return self.segments[0]

    def _add(self, duration: float, target: float, *, full: bool = False) -> None:
        self._cursor_s += duration
        self.segments.append(_Segment(self._cursor_s, target, full))

    def _append_next(self) -> None:
        r = self.rng
        stop = self._stopped_next
        self._stopped_next = not stop
        match self.pattern:
            case DrivingPattern.IDLE:
                self._add(60.0, 0.0)
            case DrivingPattern.HIGHWAY:
                if self._cursor_s == 0:
                    self._add(20.0, 70.0)
                else:
                    self._add(r.uniform(20, 60), r.uniform(85, 110))
            case DrivingPattern.URBAN:
                if stop:
                    self._add(r.uniform(8, 20), 0.0)
                else:
                    self._add(r.uniform(15, 35), r.uniform(30, 55))
            case DrivingPattern.HEAVY_TRAFFIC:
                if stop:
                    self._add(r.uniform(5, 15), 0.0)
                else:
                    self._add(r.uniform(5, 12), r.uniform(5, 18))
            case DrivingPattern.RAPID_ACCELERATION:
                if stop:
                    self._add(10.0, 0.0)
                else:
                    self._add(r.uniform(12, 16), r.uniform(100, 120), full=True)
            case DrivingPattern.MIXED:
                choice = r.random()
                if choice < 0.25:
                    self._add(r.uniform(6, 15), 0.0)
                elif choice < 0.65:
                    self._add(r.uniform(15, 35), r.uniform(30, 55))
                else:
                    self._add(r.uniform(20, 45), r.uniform(60, 80))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class VehicleSimulator:
    def __init__(self, config: SimulationConfig | None = None) -> None:
        self._config = config or SimulationConfig()
        self._output_overrides: dict[str, float] = {}
        self._target_speed_override: float | None = None
        self.reset()

    @property
    def config(self) -> SimulationConfig:
        return self._config

    @property
    def elapsed_s(self) -> float:
        return self._elapsed_s

    @property
    def output_overrides(self) -> dict[str, float]:
        return dict(self._output_overrides)

    @property
    def target_speed_override(self) -> float | None:
        return self._target_speed_override

    def reconfigure(self, config: SimulationConfig) -> None:
        self._config = config
        self.reset()

    def reset(self) -> None:
        """Restart from t=0; with the same config the run repeats exactly."""
        seed = self._config.seed
        self._profile = _DrivingProfile(
            self._config.definition.pattern, random.Random(f"{seed}:profile")
        )
        self._noise_rng = random.Random(f"{seed}:noise")
        self._event_rng = random.Random(f"{seed}:events")
        self._fault_rng = random.Random(f"{seed}:faults")
        init_rng = random.Random(f"{seed}:initial")
        ambient = self._config.ambient_c
        coolant = ambient + 40.0 + init_rng.uniform(0, 10)
        oil = ambient + 35.0
        if self._config.initial_coolant_c is not None:
            coolant = self._config.initial_coolant_c
            oil = coolant - 5.0
        self._state = _VehicleState(
            coolant_temp_c=coolant,
            oil_temp_c=oil,
            intake_air_temp_c=ambient + 2.0,
            fuel_level_pct=init_rng.uniform(55, 85),
        )
        self._elapsed_s = 0.0
        self._connection_lost_until = -1.0

    def set_output_override(self, sensor: str, value: float | None) -> None:
        """Force a reported sensor value (manual control). ``None`` removes the override."""
        if sensor not in SENSOR_FIELDS:
            raise KeyError(sensor)
        if value is None:
            self._output_overrides.pop(sensor, None)
            return
        low, high = sensor_bounds()[sensor]
        if not low <= value <= high:
            raise ValueError(f"{sensor} override must be within [{low}, {high}]")
        self._output_overrides[sensor] = float(value)

    def set_target_speed(self, kph: float | None) -> None:
        """Take over the driver: hold this target speed instead of the scenario profile."""
        if kph is not None and not 0 <= kph <= 200:
            raise ValueError("Target speed must be between 0 and 200 km/h")
        self._target_speed_override = kph

    def fault_severities(self, elapsed_s: float | None = None) -> dict[FaultKind, float]:
        t = self._elapsed_s if elapsed_s is None else elapsed_s
        severities: dict[FaultKind, float] = {}
        for fault in self._config.definition.faults:
            level = fault.severity(t, self._config.fault_development_s)
            if level > 0:
                severities[fault.kind] = max(level, severities.get(fault.kind, 0.0))
        return severities

    def step(self, dt_s: float) -> SimulationStep:
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")
        remaining = dt_s
        while remaining > 1e-9:
            sub = min(MAX_SUBSTEP_S, remaining)
            self._advance(sub)
            remaining -= sub
        return self._observe(dt_s)

    def iter_steps(self, duration_s: float, dt_s: float) -> Iterator[SimulationStep]:
        """Generate a fixed-length run (used for dataset generation and tests)."""
        steps = round(duration_s / dt_s)
        for _ in range(steps):
            yield self.step(dt_s)

    # -- dynamics ------------------------------------------------------------------------------

    def _advance(self, dt: float) -> None:
        s = self._state
        faults = self.fault_severities(self._elapsed_s)
        overheat = faults.get(FaultKind.OVERHEATING, 0.0)
        cooling = faults.get(FaultKind.COOLING_DEGRADATION, 0.0)
        lubrication = faults.get(FaultKind.LOW_OIL_PRESSURE, 0.0)
        charging = faults.get(FaultKind.CHARGING_FAILURE, 0.0)
        fuel = faults.get(FaultKind.FUEL_DELIVERY, 0.0)

        segment = self._profile.segment_at(self._elapsed_s)
        target = (
            self._target_speed_override
            if self._target_speed_override is not None
            else segment.target_kph
        )
        error = target - s.speed_kph
        if segment.full_throttle and error > 5 and self._target_speed_override is None:
            throttle_cmd = 100.0
        elif error > -1.5:
            throttle_cmd = _clamp(18.0 + 4.5 * error, 0.0, 100.0) if target > 0 else 0.0
        else:
            throttle_cmd = 0.0
        s.throttle_pct += (throttle_cmd - s.throttle_pct) * min(1.0, dt * 3.0)

        power_factor = 1.0 - 0.3 * fuel
        drive = s.throttle_pct * 0.08 * power_factor
        drag = 0.3 + 0.00025 * s.speed_kph**2 if s.speed_kph > 0.1 else 0.0
        brake = min(9.0, 1.2 * -error) if error < -1.5 else 0.0
        accel = drive - drag - brake
        if target == 0 and s.speed_kph < 0.5:
            accel = min(accel, 0.0)
        s.speed_kph = _clamp(s.speed_kph + accel * dt, 0.0, 200.0)

        shift_scale = 1.5 if segment.full_throttle else 1.0
        gear = 1
        for threshold in _SHIFT_UP_KPH:
            if s.speed_kph > threshold * shift_scale:
                gear += 1
        s.gear = gear
        if s.speed_kph < 3.0:
            rpm_target = IDLE_RPM + s.throttle_pct * 15.0
        else:
            rpm_target = max(IDLE_RPM, s.speed_kph * _GEAR_RATIOS[gear - 1] + s.throttle_pct * 8)
        if fuel > 0:
            rpm_target += self._fault_rng.gauss(0.0, 160.0 * fuel)
        s.rpm += (_clamp(rpm_target, IDLE_RPM * 0.8, REDLINE_RPM) - s.rpm) * min(1.0, dt * 5.0)

        load_target = 15.0 + s.throttle_pct * 0.75 + max(accel, 0.0) * 2.0 + 8.0 * fuel
        s.engine_load_pct += (_clamp(load_target, 0.0, 100.0) - s.engine_load_pct) * min(
            1.0, dt * 4.0
        )

        s.fuel_rate_lph = (0.7 + s.rpm / 1000.0 * s.engine_load_pct / 100.0 * 4.2) * (
            1.0 + 0.35 * fuel
        )
        s.fuel_level_pct = max(
            0.0, s.fuel_level_pct - s.fuel_rate_lph * dt / 3600.0 / TANK_LITRES * 100.0
        )

        ambient = self._config.ambient_c
        heat = (0.05 + s.engine_load_pct / 100.0 * 0.35 + s.rpm / 7000.0 * 0.15) * (
            1.0 + 0.8 * overheat
        )
        opening = _clamp(
            (s.coolant_temp_c - THERMOSTAT_OPEN_C) / (THERMOSTAT_FULL_C - THERMOSTAT_OPEN_C),
            0.05,
            1.0,
        )
        airflow = 0.15 + min(s.speed_kph, 100.0) / 100.0 * 0.85
        if s.coolant_temp_c > FAN_ON_C and cooling < 0.5:
            airflow += 0.5
        efficiency = (1.0 - 0.85 * overheat) * (1.0 - 0.7 * cooling)
        cooling_rate = 0.02 * opening * airflow * efficiency * (s.coolant_temp_c - ambient)
        s.coolant_temp_c = _clamp(
            s.coolant_temp_c + (heat - cooling_rate) * dt, ambient - 5.0, COOLANT_LIMIT_C
        )

        oil_target = s.coolant_temp_c + 8.0 + s.engine_load_pct * 0.1 + 15.0 * lubrication
        s.oil_temp_c += (oil_target - s.oil_temp_c) * min(1.0, dt * 0.05)
        viscosity = _clamp(1.25 - (s.oil_temp_c - 60.0) / 200.0, 0.8, 1.3)
        s.oil_pressure_kpa = (80.0 + s.rpm * 0.075) * viscosity * (1.0 - 0.7 * lubrication)

        iat_target = (
            ambient + 8.0 * max(0.0, 1.0 - s.speed_kph / 60.0) + (s.coolant_temp_c - 80.0) * 0.05
        )
        s.intake_air_temp_c += (iat_target - s.intake_air_temp_c) * min(1.0, dt * 0.2)

        voltage_target = 14.1 - 2.3 * charging
        s.voltage_v += (voltage_target - s.voltage_v) * min(1.0, dt * 0.5)

        self._elapsed_s += dt

    # -- observation ---------------------------------------------------------------------------

    def _observe(self, dt: float) -> SimulationStep:
        definition = self._config.definition
        faults = self.fault_severities()
        connection_lost = self._update_connection(dt, definition)
        labels_base = SimulationLabels(
            scenario=definition.id,
            faults=faults,
            connection_lost=connection_lost,
            overridden_sensors=tuple(sorted(self._output_overrides)),
        )
        if connection_lost:
            return SimulationStep(self._elapsed_s, None, labels_base)

        s = self._state
        true_values = {
            "coolant_temp_c": s.coolant_temp_c,
            "rpm": s.rpm,
            "speed_kph": s.speed_kph,
            "fuel_level_pct": s.fuel_level_pct,
            "engine_load_pct": s.engine_load_pct,
            "throttle_pct": s.throttle_pct,
            "intake_air_temp_c": s.intake_air_temp_c,
            "control_module_voltage_v": s.voltage_v,
            "oil_temp_c": s.oil_temp_c,
            "oil_pressure_kpa": s.oil_pressure_kpa,
            "fuel_rate_lph": s.fuel_rate_lph,
        }
        bounds = sensor_bounds()
        readings: dict[str, float | None] = {}
        dropped: list[str] = []
        noise_scale = self._config.noise_scale
        for key in SENSOR_FIELDS:
            noise = self._noise_rng.gauss(0.0, _NOISE_SD[key] * noise_scale)
            if key in self._output_overrides:
                readings[key] = self._output_overrides[key]
                continue
            if key in definition.unsupported_sensors:
                readings[key] = None
                continue
            if definition.dropout_probability and (
                self._event_rng.random() < definition.dropout_probability
            ):
                readings[key] = None
                dropped.append(key)
                continue
            low, high = bounds[key]
            value = true_values[key] + noise
            if key == "speed_kph" and true_values[key] < 0.5:
                value = 0.0
            if key == "throttle_pct" and true_values[key] < 0.5:
                value = 0.0
            readings[key] = _clamp(value, low, high)

        sensor_fault = faults.get(FaultKind.COOLANT_SENSOR_FAILURE, 0.0)
        if (
            sensor_fault > 0
            and "coolant_temp_c" not in self._output_overrides
            and readings.get("coolant_temp_c") is not None
            and self._fault_rng.random() < max(sensor_fault, 0.15)
        ):
            readings["coolant_temp_c"] = SENSOR_OPEN_CIRCUIT_C

        labels = replace(labels_base, dropped_sensors=tuple(dropped))
        return SimulationStep(self._elapsed_s, readings, labels)

    def _update_connection(self, dt: float, definition: ScenarioDefinition) -> bool:
        spec = definition.connection_loss
        if spec is None:
            return False
        if self._elapsed_s < self._connection_lost_until:
            return True
        probability = 1.0 - math.exp(-spec.start_probability_per_s * dt)
        if self._event_rng.random() < probability:
            self._connection_lost_until = self._elapsed_s + self._event_rng.uniform(
                spec.min_duration_s, spec.max_duration_s
            )
            return True
        return False


class SimulationSource(TelemetrySource):
    """Adapts :class:`VehicleSimulator` to the common telemetry-source interface."""

    data_source = DataSource.SIMULATION

    def __init__(
        self,
        config: SimulationConfig | None = None,
        *,
        speed_factor: float = 1.0,
        start_time: datetime | None = None,
    ) -> None:
        self.simulator = VehicleSimulator(config)
        self._speed_factor = 1.0
        self.speed_factor = speed_factor
        self._start_time = start_time
        self._origin = start_time or datetime.now(UTC)
        self._is_open = False

    @property
    def description(self) -> str:
        return f"Simulation — {self.simulator.config.definition.title}"

    @property
    def speed_factor(self) -> float:
        return self._speed_factor

    @speed_factor.setter
    def speed_factor(self, value: float) -> None:
        if not 0.1 <= value <= 20.0:
            raise ValueError("Simulation speed must be between 0.1x and 20x")
        self._speed_factor = value

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        self._origin = self._start_time or datetime.now(UTC)
        self._is_open = True

    def reset(self) -> None:
        self.simulator.reset()
        self._origin = self._start_time or datetime.now(UTC)

    def read(self, interval_s: float) -> TelemetryFrame:
        if not self._is_open:
            raise RuntimeError("Simulation source is not open")
        step = self.simulator.step(interval_s * self._speed_factor)
        if step.readings is None:
            return TelemetryFrame(DataSource.SIMULATION, step.elapsed_s, None, labels=step.labels)
        timestamp = self._origin + timedelta(seconds=step.elapsed_s)
        processed = build_sample(timestamp, step.readings, fuel_rate_estimated=True)
        return TelemetryFrame(
            DataSource.SIMULATION,
            step.elapsed_s,
            processed.sample,
            rejected=processed.rejected,
            labels=step.labels,
        )

    def close(self) -> None:
        self._is_open = False
