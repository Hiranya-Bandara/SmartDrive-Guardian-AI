"""The hybrid engine on live OBD-II-shaped data: compatibility, abstention and rule independence.

Uses the shipped models. These tests check behaviour (when the models run or abstain and how
findings are attributed), not accuracy: the models are validated on simulated data only.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from smartdrive.ai.model_registry import LoadedModels, ModelRegistry
from smartdrive.config.constants import DataSource, DiagnosticSource, Severity
from smartdrive.config.settings import DiagnosticSettings
from smartdrive.core.telemetry_window import TelemetryWindow
from smartdrive.models.diagnostic import DiagnosticAssessment, DiagnosticStatus, ModelRunStatus
from smartdrive.models.telemetry import SENSOR_FIELDS
from smartdrive.obd.capabilities import VehicleCapabilities
from smartdrive.obd.pids import DATA_PIDS
from smartdrive.services.diagnostic_engine import DiagnosticEngine
from smartdrive.services.dtc_reference import is_generic, lookup, reference_size

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
HEALTHY = {
    "coolant_temp_c": 88.0,
    "rpm": 2100.0,
    "speed_kph": 60.0,
    "fuel_level_pct": 55.0,
    "engine_load_pct": 35.0,
    "throttle_pct": 18.0,
    "intake_air_temp_c": 30.0,
    "control_module_voltage_v": 14.1,
    "oil_temp_c": 92.0,
    "oil_pressure_kpa": 280.0,
    "fuel_rate_lph": 5.5,
}


@pytest.fixture(scope="module")
def models() -> Iterator[LoadedModels]:
    loaded = ModelRegistry().load()
    assert loaded.classifier is not None and loaded.anomaly is not None
    yield loaded


def stream(**overrides: float | None) -> list[TelemetryWindow]:
    """A minute-long window every 2 s for ~40 s, as the controller would analyse."""
    values = {**HEALTHY, **overrides}
    windows = []
    for end in range(60, 100, 2):
        times = [float(t) for t in range(end - 60, end)]
        series = {
            key: [math.nan if values[key] is None else float(values[key])] * len(times)  # type: ignore[arg-type]
            for key in SENSOR_FIELDS
        }
        windows.append(TelemetryWindow.from_series(times, series))
    return windows


def run(
    engine: DiagnosticEngine,
    windows: list[TelemetryWindow],
    *,
    source: DataSource = DataSource.LIVE,
    unavailable: frozenset[str] = frozenset(),
    block: str | None = None,
) -> DiagnosticAssessment:
    result = None
    for window in windows:
        result = engine.assess(
            window,
            data_source=source,
            timestamp=NOW,
            unavailable_sensors=unavailable,
            ml_block_reason=block,
        )
    assert result is not None
    return result


def generic_obd_unavailable() -> frozenset[str]:
    """What a vehicle that supports every standard PID SmartDrive reads still cannot provide."""
    caps = VehicleCapabilities(frozenset(spec.pid for spec in DATA_PIDS))
    return frozenset(caps.missing_sample_fields)


def test_generic_obd_can_never_supply_oil_pressure() -> None:
    assert "oil_pressure_kpa" in generic_obd_unavailable()


def test_models_do_not_run_on_incompatible_live_input(models: LoadedModels) -> None:
    engine = DiagnosticEngine(models, DiagnosticSettings(live_ml_enabled=True))
    result = run(engine, stream(oil_pressure_kpa=None), unavailable=generic_obd_unavailable())
    assert result.classifier.status is ModelRunStatus.INCOMPATIBLE
    assert result.anomaly.status is ModelRunStatus.INCOMPATIBLE
    assert "oil pressure" in result.classifier.reason.lower()
    assert result.classifier.labels == ()
    assert not result.explanations
    assert all(f.source is DiagnosticSource.RULE for f in result.findings)


def test_live_ml_switch_blocks_models_but_not_rules(models: LoadedModels) -> None:
    engine = DiagnosticEngine(models, DiagnosticSettings())
    result = run(
        engine,
        stream(coolant_temp_c=121.0, oil_pressure_kpa=None),
        unavailable=generic_obd_unavailable(),
        block="Experimental inference is off for live data.",
    )
    assert result.classifier.status is ModelRunStatus.DISABLED
    assert result.anomaly.status is ModelRunStatus.DISABLED
    assert result.status is DiagnosticStatus.CRITICAL
    critical = [f for f in result.findings if f.severity is Severity.CRITICAL]
    assert critical and all(f.source is DiagnosticSource.RULE for f in critical)
    assert result.data_source is DataSource.LIVE


def test_partial_sensors_never_become_invented_values(models: LoadedModels) -> None:
    engine = DiagnosticEngine(models, DiagnosticSettings())
    windows = stream(rpm=None, speed_kph=None, coolant_temp_c=None, oil_pressure_kpa=None)
    result = run(engine, windows, unavailable=frozenset({"rpm", "speed_kph", "coolant_temp_c"}))
    assert result.status is DiagnosticStatus.INSUFFICIENT_DATA
    assert result.health.score is None
    assert not result.quality.sufficient


def test_stale_live_data_is_not_assessed(models: LoadedModels) -> None:
    engine = DiagnosticEngine(models, DiagnosticSettings())
    result = engine.assess(
        stream()[-1],
        data_source=DataSource.LIVE,
        timestamp=NOW,
        data_age_s=30.0,
        stale_after_s=5.0,
    )
    assert result.status is DiagnosticStatus.STALE
    assert result.findings == ()


def test_full_simulated_input_still_runs_the_models(models: LoadedModels) -> None:
    engine = DiagnosticEngine(models, DiagnosticSettings())
    result = run(engine, stream(), source=DataSource.SIMULATION)
    assert result.classifier.status is ModelRunStatus.OK
    assert result.anomaly.status is ModelRunStatus.OK


class TestTroubleCodeReference:
    def test_generic_codes_have_sourced_descriptions(self) -> None:
        info = lookup("p0217")
        assert info.code == "P0217" and info.known and info.generic
        assert "SAE J2012" in info.source
        assert info.next_steps
        assert reference_size() > 50

    def test_manufacturer_specific_codes_are_never_given_a_meaning(self) -> None:
        for code in ("P1234", "B1A00", "C1100", "U1000", "P3000"):
            info = lookup(code)
            assert not info.generic and not info.known
            assert "Manufacturer-specific" in info.display_description

    def test_unknown_generic_codes_show_an_unknown_state(self) -> None:
        info = lookup("P0999")
        assert info.generic and not info.known
        assert info.display_description.startswith("Unknown code")
        assert is_generic("U0100") and not is_generic("U1100")

    def test_invalid_codes_are_rejected(self) -> None:
        for bad in ("", "X0100", "P01", "P01000", "PZZZZ"):
            with pytest.raises(ValueError):
                lookup(bad)

    def test_descriptions_do_not_claim_component_failure(self) -> None:
        for code in ("P0300", "P0420", "P0217"):
            text = lookup(code).display_description.lower()
            assert "failed" not in text and "replace" not in text
