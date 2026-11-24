from __future__ import annotations

import itertools
import statistics
from datetime import UTC, datetime

import pytest

from smartdrive.config.constants import DataSource, FaultCategory
from smartdrive.services.scenarios import SCENARIOS, FaultKind, FaultSpec, ScenarioId
from smartdrive.services.simulator import (
    SENSOR_OPEN_CIRCUIT_C,
    SimulationConfig,
    SimulationSource,
    SimulationStep,
    VehicleSimulator,
)

DT = 0.5


def run(scenario: ScenarioId, seconds: float = 300.0, **config: object) -> list[SimulationStep]:
    sim = VehicleSimulator(SimulationConfig(scenario=scenario, seed=7, **config))  # type: ignore[arg-type]
    return list(sim.iter_steps(seconds, DT))


def values(steps: list[SimulationStep], key: str, after_s: float = 0.0) -> list[float]:
    return [
        v
        for s in steps
        if s.elapsed_s >= after_s and s.readings is not None
        for v in [s.readings[key]]
        if v is not None
    ]


class TestReproducibility:
    def test_same_seed_produces_identical_runs(self) -> None:
        a = run(ScenarioId.MULTIPLE, 120)
        b = run(ScenarioId.MULTIPLE, 120)
        assert [s.readings for s in a] == [s.readings for s in b]
        assert [s.labels for s in a] == [s.labels for s in b]

    def test_different_seeds_differ(self) -> None:
        a = VehicleSimulator(SimulationConfig(seed=1))
        b = VehicleSimulator(SimulationConfig(seed=2))
        assert [a.step(DT).readings for _ in range(100)] != [
            b.step(DT).readings for _ in range(100)
        ]

    def test_reset_replays_from_start(self) -> None:
        sim = VehicleSimulator(SimulationConfig(scenario=ScenarioId.URBAN, seed=3))
        first = [sim.step(DT).readings for _ in range(50)]
        sim.reset()
        assert [sim.step(DT).readings for _ in range(50)] == first
        assert sim.elapsed_s == pytest.approx(25.0)

    def test_step_size_does_not_change_the_vehicle_model(self) -> None:
        config = SimulationConfig(scenario=ScenarioId.IDLE, noise_scale=0.0)
        fine = VehicleSimulator(config)
        for _ in range(100):
            fine.step(0.1)
        coarse = VehicleSimulator(config)
        coarse.step(10.0)
        assert fine.step(0.1).readings == pytest.approx(coarse.step(0.1).readings, rel=1e-6)


class TestTimeDependence:
    def test_values_evolve_smoothly_rather_than_independently(self) -> None:
        steps = run(ScenarioId.NORMAL, 120, noise_scale=0.0)
        coolant = values(steps, "coolant_temp_c")
        biggest_jump = max(abs(b - a) for a, b in itertools.pairwise(coolant))
        assert biggest_jump < 1.0

    def test_no_noise_option_is_deterministic_and_smooth(self) -> None:
        steps = run(ScenarioId.IDLE, 60, noise_scale=0.0)
        speeds = values(steps, "speed_kph")
        assert set(speeds) == {0.0}

    def test_fuel_level_only_decreases(self) -> None:
        fuel = values(run(ScenarioId.HIGHWAY, 300, noise_scale=0.0), "fuel_level_pct")
        assert all(b <= a for a, b in itertools.pairwise(fuel))
        assert fuel[-1] < fuel[0]


class TestDrivingScenarios:
    def test_idle(self) -> None:
        steps = run(ScenarioId.IDLE, 120)
        assert max(values(steps, "speed_kph")) == 0.0
        assert 650 < statistics.mean(values(steps, "rpm", 10)) < 900

    def test_highway(self) -> None:
        assert statistics.mean(values(run(ScenarioId.HIGHWAY), "speed_kph", 60)) > 80

    def test_urban_has_stops(self) -> None:
        speeds = values(run(ScenarioId.URBAN), "speed_kph")
        assert min(speeds) == 0.0
        assert max(speeds) < 70

    def test_heavy_traffic_is_slow(self) -> None:
        assert max(values(run(ScenarioId.HEAVY_TRAFFIC), "speed_kph")) < 25

    def test_rapid_acceleration_reaches_high_rpm(self) -> None:
        steps = run(ScenarioId.RAPID_ACCELERATION)
        assert max(values(steps, "rpm")) > 3800
        assert max(values(steps, "throttle_pct")) > 95

    @pytest.mark.parametrize(
        "scenario",
        [
            ScenarioId.NORMAL,
            ScenarioId.IDLE,
            ScenarioId.HIGHWAY,
            ScenarioId.URBAN,
            ScenarioId.HEAVY_TRAFFIC,
            ScenarioId.RAPID_ACCELERATION,
        ],
    )
    def test_healthy_scenarios_stay_in_normal_bands_and_are_labelled_normal(
        self, scenario: ScenarioId
    ) -> None:
        steps = run(scenario)
        assert max(values(steps, "coolant_temp_c")) < 100
        assert min(values(steps, "control_module_voltage_v", 30)) > 13.5
        assert all(s.labels.is_normal for s in steps)
        assert not SCENARIOS[scenario].is_abnormal


class TestFaultScenarios:
    def test_overheating_develops_gradually(self) -> None:
        steps = run(ScenarioId.OVERHEATING)
        before = max(values(steps, "coolant_temp_c")[: int(30 / DT)])
        assert before < 100
        assert max(values(steps, "coolant_temp_c", 200)) > 110
        severities = [s.labels.faults.get(FaultKind.OVERHEATING, 0.0) for s in steps]
        assert severities == sorted(severities)
        assert severities[0] == 0.0
        assert severities[-1] == 1.0

    def test_cooling_degradation(self) -> None:
        assert max(values(run(ScenarioId.COOLING, 400), "coolant_temp_c", 200)) > 105

    def test_lubrication_lowers_oil_pressure(self) -> None:
        steps = run(ScenarioId.LUBRICATION)
        early = statistics.mean(values(steps, "oil_pressure_kpa")[: int(30 / DT)])
        late = statistics.mean(values(steps, "oil_pressure_kpa", 200))
        assert late < early * 0.5

    def test_electrical_fault_drops_voltage(self) -> None:
        assert (
            statistics.mean(values(run(ScenarioId.ELECTRICAL), "control_module_voltage_v", 200))
            < 12.3
        )

    def test_fuel_system_fault_increases_consumption(self) -> None:
        normal = statistics.mean(values(run(ScenarioId.NORMAL), "fuel_rate_lph", 150))
        faulty = statistics.mean(values(run(ScenarioId.FUEL_SYSTEM), "fuel_rate_lph", 150))
        assert faulty > normal * 1.2

    def test_sensor_failure_reports_open_circuit(self) -> None:
        steps = run(ScenarioId.SENSOR_FAILURE)
        late = values(steps, "coolant_temp_c", 120)
        assert late.count(SENSOR_OPEN_CIRCUIT_C) > len(late) * 0.9
        assert FaultCategory.SENSOR in steps[-1].labels.categories

    def test_missing_sensors_are_none_never_zero(self) -> None:
        steps = run(ScenarioId.MISSING_SENSORS)
        assert all(s.readings is not None and s.readings["oil_pressure_kpa"] is None for s in steps)
        dropped = [s for s in steps if s.labels.dropped_sensors]
        assert dropped
        for step in dropped:
            assert step.readings is not None
            assert all(step.readings[key] is None for key in step.labels.dropped_sensors)

    def test_intermittent_connection_loss(self) -> None:
        steps = run(ScenarioId.CONNECTION_LOSS, 600)
        lost = [s for s in steps if s.readings is None]
        assert 0 < len(lost) < len(steps) * 0.3
        assert all(s.labels.connection_lost for s in lost)

    def test_multiple_simultaneous_abnormalities(self) -> None:
        labels = run(ScenarioId.MULTIPLE)[-1].labels
        assert labels.categories == {FaultCategory.COOLING, FaultCategory.ELECTRICAL}

    def test_fault_development_override(self) -> None:
        sim = VehicleSimulator(
            SimulationConfig(scenario=ScenarioId.OVERHEATING, fault_development_s=0.0)
        )
        list(sim.iter_steps(31, DT))
        assert sim.fault_severities()[FaultKind.OVERHEATING] == 1.0

    def test_fault_spec_severity(self) -> None:
        spec = FaultSpec(FaultKind.OVERHEATING, onset_s=10, ramp_s=20)
        assert [spec.severity(t) for t in (5, 10, 20, 30, 99)] == [0.0, 0.0, 0.5, 1.0, 1.0]


class TestManualControls:
    def test_output_override_is_reported_and_labelled(self) -> None:
        sim = VehicleSimulator()
        sim.set_output_override("coolant_temp_c", 121.0)
        step = sim.step(DT)
        assert step.readings is not None
        assert step.readings["coolant_temp_c"] == 121.0
        assert step.labels.overridden_sensors == ("coolant_temp_c",)
        sim.set_output_override("coolant_temp_c", None)
        assert sim.step(DT).labels.overridden_sensors == ()

    def test_override_validation(self) -> None:
        sim = VehicleSimulator()
        with pytest.raises(ValueError):
            sim.set_output_override("rpm", -1.0)
        with pytest.raises(KeyError):
            sim.set_output_override("boost", 1.0)

    def test_manual_target_speed(self) -> None:
        sim = VehicleSimulator(SimulationConfig(scenario=ScenarioId.IDLE, noise_scale=0.0))
        sim.set_target_speed(80.0)
        steps = list(sim.iter_steps(90, DT))
        assert values(steps, "speed_kph")[-1] == pytest.approx(80.0, abs=3.0)
        with pytest.raises(ValueError):
            sim.set_target_speed(500.0)

    @pytest.mark.parametrize(
        "kwargs",
        [{"noise_scale": -1.0}, {"ambient_c": 90.0}, {"fault_development_s": -5.0}],
    )
    def test_config_validation(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError):
            SimulationConfig(**kwargs)  # type: ignore[arg-type]


class TestSimulationSource:
    def test_frames_are_labelled_validated_and_timestamped(self) -> None:
        start = datetime(2026, 5, 1, tzinfo=UTC)
        source = SimulationSource(SimulationConfig(seed=1), speed_factor=2.0, start_time=start)
        source.open()
        frame = source.read(0.5)
        assert frame.source is DataSource.SIMULATION
        assert frame.elapsed_s == pytest.approx(1.0)
        assert frame.sample is not None
        assert (frame.sample.timestamp - start).total_seconds() == pytest.approx(1.0)
        assert frame.sample.fuel_rate_estimated
        assert frame.labels is not None
        source.close()

    def test_connection_loss_yields_empty_frames(self) -> None:
        source = SimulationSource(SimulationConfig(scenario=ScenarioId.CONNECTION_LOSS, seed=7))
        source.open()
        frames = [source.read(0.5) for _ in range(800)]
        assert any(not f.connected for f in frames)
        assert all(f.sample is None for f in frames if not f.connected)

    def test_read_requires_open_and_speed_is_bounded(self) -> None:
        source = SimulationSource()
        with pytest.raises(RuntimeError):
            source.read(0.1)
        with pytest.raises(ValueError):
            source.speed_factor = 100.0
