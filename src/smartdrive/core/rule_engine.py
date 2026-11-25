"""Transparent, stateful rule-based diagnostics.

Each rule inspects a :class:`TelemetryWindow` and may report an *observation*. An observation
must hold for the rule's persistence time before it becomes an active finding, and an active
finding clears only when the rule's relaxed (hysteresis) condition no longer holds. Rules that
lack the data they need report nothing; they never assume a value.

Thresholds come from :class:`DiagnosticThresholds` — conservative simulation defaults, not
manufacturer specifications.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Final

import numpy as np

from smartdrive.config.constants import DiagnosticSource, FaultCategory, FuelType, Severity
from smartdrive.config.settings import DiagnosticThresholds
from smartdrive.core.telemetry_window import TelemetryWindow
from smartdrive.models.diagnostic import SEVERITY_RANK, Finding

RUNNING_RPM: Final = 600.0
RECENT_S: Final = 10.0
OPEN_CIRCUIT_C: Final = -35.0
PLAUSIBLE_JUMP_C: Final = 25.0


@dataclass(frozen=True, slots=True)
class VehicleContext:
    """Vehicle facts that change which rules apply."""

    fuel_type: FuelType | None = None

    @property
    def has_combustion_engine(self) -> bool:
        return self.fuel_type is not FuelType.ELECTRIC


@dataclass(frozen=True, slots=True)
class Observation:
    severity: Severity
    title: str
    explanation: str
    evidence: dict[str, float | str] = field(default_factory=dict)


def _recent_mean(window: TelemetryWindow, key: str, seconds: float = RECENT_S) -> float | None:
    values = window.recent(key, seconds)
    return float(values.mean()) if values.size >= 3 else None


def _engine_running(window: TelemetryWindow) -> bool:
    rpm = _recent_mean(window, "rpm")
    return rpm is not None and rpm > RUNNING_RPM


class Rule(ABC):
    rule_id: ClassVar[str]
    category: ClassVar[FaultCategory]
    persistence_s: ClassVar[float]
    requires_engine: ClassVar[bool] = True

    @abstractmethod
    def observe(
        self, window: TelemetryWindow, limits: DiagnosticThresholds, active: bool
    ) -> Observation | None:
        """Return an observation, applying relaxed clear conditions when ``active``."""


class CoolantTemperatureRule(Rule):
    rule_id = "coolant_temperature"
    category = FaultCategory.COOLING
    persistence_s = 10.0
    requires_engine = False

    def observe(
        self, window: TelemetryWindow, limits: DiagnosticThresholds, active: bool
    ) -> Observation | None:
        values = window.recent("coolant_temp_c", RECENT_S)
        values = values[values > OPEN_CIRCUIT_C]
        if values.size < 3:
            return None
        mean = float(values.mean())
        warning = limits.coolant_warning_c - (3.0 if active else 0.0)
        evidence: dict[str, float | str] = {"coolant_10s_mean_c": round(mean, 1)}
        if mean >= limits.coolant_critical_c:
            return Observation(
                Severity.CRITICAL,
                "Coolant temperature critically high",
                f"Coolant averaged {mean:.0f} °C over 10 s, at or above the critical limit of "
                f"{limits.coolant_critical_c:.0f} °C.",
                evidence,
            )
        if mean >= warning:
            return Observation(
                Severity.WARNING,
                "Coolant temperature above normal range",
                f"Coolant averaged {mean:.0f} °C over 10 s (warning limit "
                f"{limits.coolant_warning_c:.0f} °C).",
                evidence,
            )
        return None


class CoolantRiseRule(Rule):
    rule_id = "coolant_rise"
    category = FaultCategory.COOLING
    persistence_s = 20.0
    requires_engine = False

    def observe(
        self, window: TelemetryWindow, limits: DiagnosticThresholds, active: bool
    ) -> Observation | None:
        mean = _recent_mean(window, "coolant_temp_c")
        slope = window.slope_per_minute("coolant_temp_c")
        if mean is None or slope is None or mean <= OPEN_CIRCUIT_C:
            return None
        minimum_rate = limits.coolant_rise_per_min * (0.5 if active else 1.0)
        if mean >= 95.0 and slope >= minimum_rate:
            return Observation(
                Severity.WARNING,
                "Persistent coolant temperature increase",
                f"Coolant is {mean:.0f} °C and has been rising {slope:.1f} °C/min over the last "
                "minute, above the normal operating band.",
                {"coolant_c": round(mean, 1), "rise_c_per_min": round(slope, 2)},
            )
        return None


class ChargingVoltageRule(Rule):
    rule_id = "charging_voltage"
    category = FaultCategory.ELECTRICAL
    persistence_s = 15.0

    def observe(
        self, window: TelemetryWindow, limits: DiagnosticThresholds, active: bool
    ) -> Observation | None:
        voltage = _recent_mean(window, "control_module_voltage_v")
        if voltage is None or not _engine_running(window):
            return None
        evidence: dict[str, float | str] = {"voltage_10s_mean_v": round(voltage, 2)}
        low_warning = limits.voltage_low_warning_v + (0.2 if active else 0.0)
        if voltage < limits.voltage_low_critical_v:
            return Observation(
                Severity.CRITICAL,
                "Charging voltage critically low",
                f"Voltage averaged {voltage:.2f} V with the engine running, below "
                f"{limits.voltage_low_critical_v:.1f} V. The charging system may not be "
                "supplying power.",
                evidence,
            )
        if voltage < low_warning:
            return Observation(
                Severity.WARNING,
                "Charging voltage low",
                f"Voltage averaged {voltage:.2f} V with the engine running (warning below "
                f"{limits.voltage_low_warning_v:.1f} V).",
                evidence,
            )
        if voltage > limits.voltage_high_warning_v:
            return Observation(
                Severity.WARNING,
                "Charging voltage high",
                f"Voltage averaged {voltage:.2f} V, above {limits.voltage_high_warning_v:.1f} V.",
                evidence,
            )
        return None


class OilPressureRule(Rule):
    rule_id = "oil_pressure"
    category = FaultCategory.LUBRICATION
    persistence_s = 5.0

    def observe(
        self, window: TelemetryWindow, limits: DiagnosticThresholds, active: bool
    ) -> Observation | None:
        pressure = _recent_mean(window, "oil_pressure_kpa")
        if pressure is None or not _engine_running(window):
            return None
        evidence: dict[str, float | str] = {"oil_pressure_10s_mean_kpa": round(pressure, 0)}
        warning = limits.oil_pressure_warning_kpa + (15.0 if active else 0.0)
        if pressure < limits.oil_pressure_critical_kpa:
            return Observation(
                Severity.CRITICAL,
                "Oil pressure critically low",
                f"Oil pressure averaged {pressure:.0f} kPa with the engine running, below "
                f"{limits.oil_pressure_critical_kpa:.0f} kPa.",
                evidence,
            )
        if pressure < warning:
            return Observation(
                Severity.WARNING,
                "Oil pressure low",
                f"Oil pressure averaged {pressure:.0f} kPa with the engine running (warning "
                f"below {limits.oil_pressure_warning_kpa:.0f} kPa).",
                evidence,
            )
        return None


class CoolantSensorPlausibilityRule(Rule):
    rule_id = "coolant_sensor_plausibility"
    category = FaultCategory.SENSOR
    persistence_s = 0.0
    requires_engine = False

    def observe(
        self, window: TelemetryWindow, limits: DiagnosticThresholds, active: bool
    ) -> Observation | None:
        coolant = window.values["coolant_temp_c"]
        present = coolant[~np.isnan(coolant)]
        if present.size < 5:
            return None
        open_circuit = int(np.count_nonzero(present <= OPEN_CIRCUIT_C))
        jumps = int(np.count_nonzero(np.abs(np.diff(present)) > PLAUSIBLE_JUMP_C))
        needed = 1 if active else 2
        if open_circuit >= needed or jumps >= needed:
            return Observation(
                Severity.WARNING,
                "Coolant temperature sensor reading implausible",
                f"In the last minute the coolant sensor reported {open_circuit} reading(s) at or "
                f"below {OPEN_CIRCUIT_C:.0f} °C and {jumps} jump(s) larger than "
                f"{PLAUSIBLE_JUMP_C:.0f} °C between seconds. A real engine cannot change "
                "temperature this quickly; the sensor or its wiring may be faulty.",
                {"open_circuit_readings": open_circuit, "implausible_jumps": jumps},
            )
        return None


class EngineSpeedStabilityRule(Rule):
    rule_id = "engine_speed_stability"
    category = FaultCategory.FUEL
    persistence_s = 30.0

    def observe(
        self, window: TelemetryWindow, limits: DiagnosticThresholds, active: bool
    ) -> Observation | None:
        rpm = window.recent("rpm", 30.0)
        speed = window.recent("speed_kph", 30.0)
        throttle = window.recent("throttle_pct", 30.0)
        if rpm.size < 15 or speed.size < 15 or throttle.size < 15 or not _engine_running(window):
            return None
        if float(np.std(speed)) > 3.0 or float(np.std(throttle)) > 6.0:
            return None
        jitter = float(np.std(np.diff(rpm)))
        limit = limits.rpm_jitter_warning * (0.8 if active else 1.0)
        if jitter > limit:
            return Observation(
                Severity.WARNING,
                "Unstable engine speed at steady driving",
                f"Engine speed varied second-to-second by {jitter:.0f} rpm (standard deviation) "
                "while road speed and throttle were steady. Possible causes include fuel "
                "delivery, ignition or sensor problems.",
                {"rpm_jitter": round(jitter, 0), "speed_std_kph": round(float(np.std(speed)), 1)},
            )
        return None


class FuelLevelDropRule(Rule):
    rule_id = "fuel_level_drop"
    category = FaultCategory.FUEL
    persistence_s = 10.0
    requires_engine = False

    def observe(
        self, window: TelemetryWindow, limits: DiagnosticThresholds, active: bool
    ) -> Observation | None:
        fuel = window.values["fuel_level_pct"]
        early = fuel[window.times < window.times[0] + 10.0]
        early = early[~np.isnan(early)]
        late = window.recent("fuel_level_pct", RECENT_S)
        if early.size < 3 or late.size < 3:
            return None
        drop = float(early.mean() - late.mean())
        if drop >= limits.fuel_level_drop_pct * (0.6 if active else 1.0):
            return Observation(
                Severity.WARNING,
                "Unexpected fuel level drop",
                f"Fuel level fell {drop:.1f} percentage points within one minute, faster than "
                "normal consumption. This may indicate a leak or a faulty level sender.",
                {"fuel_drop_pct": round(drop, 1)},
            )
        return None


DEFAULT_RULES: Final[tuple[type[Rule], ...]] = (
    CoolantTemperatureRule,
    CoolantRiseRule,
    ChargingVoltageRule,
    OilPressureRule,
    CoolantSensorPlausibilityRule,
    EngineSpeedStabilityRule,
    FuelLevelDropRule,
)


@dataclass(slots=True)
class _RuleState:
    candidate_since: float | None = None
    active: Observation | None = None


class RuleEngine:
    """Evaluates rules over successive windows of one telemetry stream (not thread-safe)."""

    def __init__(
        self,
        thresholds: DiagnosticThresholds | None = None,
        vehicle: VehicleContext | None = None,
        rules: tuple[type[Rule], ...] = DEFAULT_RULES,
    ) -> None:
        self.thresholds = thresholds or DiagnosticThresholds()
        self.vehicle = vehicle or VehicleContext()
        self._rules = [rule() for rule in rules]
        self._state = {rule.rule_id: _RuleState() for rule in self._rules}

    @property
    def rule_ids(self) -> list[str]:
        return [rule.rule_id for rule in self._rules]

    def reset(self) -> None:
        for state in self._state.values():
            state.candidate_since = None
            state.active = None

    def evaluate(self, window: TelemetryWindow) -> list[Finding]:
        now = window.end_elapsed_s
        findings: list[Finding] = []
        for rule in self._rules:
            state = self._state[rule.rule_id]
            if rule.requires_engine and not self.vehicle.has_combustion_engine:
                continue
            observation = rule.observe(window, self.thresholds, active=state.active is not None)
            if observation is None:
                state.candidate_since = None
                state.active = None
                continue
            if state.active is not None:
                state.active = self._escalate(state.active, observation)
            else:
                if state.candidate_since is None or now < state.candidate_since:
                    state.candidate_since = now
                if now - state.candidate_since >= rule.persistence_s:
                    state.active = observation
            if state.active is not None:
                findings.append(
                    Finding(
                        key=f"rule:{rule.rule_id}",
                        source=DiagnosticSource.RULE,
                        category=rule.category,
                        severity=state.active.severity,
                        title=state.active.title,
                        explanation=state.active.explanation,
                        evidence=dict(state.active.evidence),
                    )
                )
        return findings

    @staticmethod
    def _escalate(current: Observation, new: Observation) -> Observation:
        """Active findings follow the latest observation, but never drop severity while the
        condition persists (avoids WARNING/CRITICAL flapping around a limit)."""
        if SEVERITY_RANK[new.severity] >= SEVERITY_RANK[current.severity]:
            return new
        return Observation(current.severity, current.title, new.explanation, new.evidence)
