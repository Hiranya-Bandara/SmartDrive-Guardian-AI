"""Telemetry windows, feature extraction, rule engine, health score and recommendations."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from smartdrive.ai.features import FEATURE_NAMES, describe_feature, extract_features
from smartdrive.config.constants import DiagnosticSource, FaultCategory, FuelType, Severity
from smartdrive.config.settings import DiagnosticThresholds
from smartdrive.core.health_score import band_for, compute_health_score
from smartdrive.core.recommendations import MECHANIC, recommend
from smartdrive.core.rule_engine import RuleEngine, VehicleContext
from smartdrive.core.telemetry_window import MIN_SAMPLES, TelemetryWindow
from smartdrive.models.diagnostic import (
    AnomalyResult,
    ClassifierResult,
    DiagnosticStatus,
    Finding,
    LabelPrediction,
    LabelState,
    ModelRunStatus,
)
from smartdrive.models.telemetry import SENSOR_FIELDS, TelemetrySample

HEALTHY = {
    "coolant_temp_c": 90.0,
    "rpm": 2000.0,
    "speed_kph": 60.0,
    "fuel_level_pct": 60.0,
    "engine_load_pct": 35.0,
    "throttle_pct": 20.0,
    "intake_air_temp_c": 32.0,
    "control_module_voltage_v": 14.1,
    "oil_temp_c": 98.0,
    "oil_pressure_kpa": 250.0,
    "fuel_rate_lph": 5.0,
}


def window(
    end: float = 120.0, seconds: int = 60, step: float = 1.0, **overrides: float | None
) -> TelemetryWindow:
    values = {**HEALTHY, **overrides}
    count = int(seconds / step)
    times = [end - seconds + step * (i + 1) for i in range(count)]
    series = {
        key: [math.nan if values[key] is None else float(values[key])] * count  # type: ignore[arg-type]
        for key in SENSOR_FIELDS
    }
    return TelemetryWindow.from_series(times, series)


class TestTelemetryWindow:
    def test_quality_sufficient_for_a_full_minute(self) -> None:
        quality = window().quality()
        assert quality.sufficient
        assert quality.coverage == pytest.approx(1.0)
        assert quality.overall_completeness == pytest.approx(1.0)

    def test_too_few_samples_is_insufficient(self) -> None:
        quality = window(seconds=MIN_SAMPLES - 5).quality()
        assert not quality.sufficient
        assert "seconds of readings" in quality.reason

    def test_missing_core_sensors_is_insufficient(self) -> None:
        quality = window(coolant_temp_c=None, rpm=None, speed_kph=None).quality()
        assert not quality.sufficient
        assert quality.completeness["rpm"] == 0.0

    def test_empty_window(self) -> None:
        empty = TelemetryWindow.from_samples([])
        assert empty.sample_count == 0
        assert not empty.quality().sufficient

    def test_resampling_makes_refresh_rate_irrelevant(self) -> None:
        coarse = window(step=1.0)
        fine = window(step=0.1)
        assert np.allclose(extract_features(coarse), extract_features(fine), equal_nan=True)

    def test_from_samples_matches_from_series(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        samples = [
            (float(t), TelemetrySample(timestamp=start + timedelta(seconds=t), **HEALTHY))
            for t in range(1, 61)
        ]
        built = TelemetryWindow.from_samples(samples)
        assert built.sample_count == 60
        assert built.latest("rpm") == 2000.0

    def test_slope_per_minute(self) -> None:
        times = [float(t) for t in range(1, 61)]
        series = {key: [HEALTHY[key]] * 60 for key in SENSOR_FIELDS}
        series["coolant_temp_c"] = [80.0 + t / 10 for t in times]
        built = TelemetryWindow.from_series(times, series)
        assert built.slope_per_minute("coolant_temp_c") == pytest.approx(6.0, rel=1e-3)


class TestFeatures:
    def test_vector_matches_schema(self) -> None:
        features = extract_features(window())
        assert features.shape == (len(FEATURE_NAMES),)
        assert np.isfinite(features).sum() > len(FEATURE_NAMES) * 0.9

    def test_missing_sensor_becomes_nan_not_zero(self) -> None:
        features = dict(
            zip(FEATURE_NAMES, extract_features(window(oil_pressure_kpa=None)), strict=True)
        )
        assert math.isnan(features["oil_pressure_kpa__mean"])
        assert math.isnan(features["oil_pressure_per_krpm"])
        assert features["oil_pressure_kpa__completeness"] == 0.0

    def test_no_label_or_identifier_features(self) -> None:
        forbidden = ("scenario", "label", "fault", "severity", "session", "seed", "split")
        assert not [n for n in FEATURE_NAMES if any(term in n for term in forbidden)]

    def test_features_only_use_the_past(self) -> None:
        early = window(end=100.0)
        later = window(end=200.0)
        assert np.allclose(extract_features(early), extract_features(later), equal_nan=True)

    def test_descriptions_are_human_readable(self) -> None:
        assert describe_feature("coolant_temp_c__slope_per_min") == (
            "Engine coolant temperature — trend per minute"
        )
        assert describe_feature("oil_pressure_per_krpm") == "Oil pressure per 1000 rpm"


def run_rules(
    engine: RuleEngine, start: float, stop: float, **overrides: float | None
) -> list[Finding]:
    findings: list[Finding] = []
    t = start
    while t <= stop:
        findings = engine.evaluate(window(end=t, **overrides))
        t += 2.0
    return findings


class TestRuleEngine:
    def test_healthy_telemetry_has_no_findings(self) -> None:
        assert run_rules(RuleEngine(), 60, 200) == []

    def test_persistence_requirement(self) -> None:
        engine = RuleEngine()
        assert engine.evaluate(window(end=60, coolant_temp_c=120.0)) == []
        findings = run_rules(engine, 62, 72, coolant_temp_c=120.0)
        (finding,) = findings
        assert finding.key == "rule:coolant_temperature"
        assert finding.severity is Severity.CRITICAL
        assert finding.source is DiagnosticSource.RULE
        assert "115" in finding.explanation

    def test_hysteresis_keeps_finding_until_clearly_resolved(self) -> None:
        engine = RuleEngine()
        run_rules(engine, 60, 80, coolant_temp_c=107.0)
        assert [f.severity for f in engine.evaluate(window(end=82, coolant_temp_c=103.0))] == [
            Severity.WARNING
        ]
        assert engine.evaluate(window(end=84, coolant_temp_c=100.0)) == []

    def test_severity_does_not_flap_down_while_condition_persists(self) -> None:
        engine = RuleEngine()
        run_rules(engine, 60, 80, coolant_temp_c=118.0)
        findings = engine.evaluate(window(end=82, coolant_temp_c=110.0))
        assert findings[0].severity is Severity.CRITICAL

    def test_simultaneous_findings_in_different_categories(self) -> None:
        findings = run_rules(
            RuleEngine(),
            60,
            100,
            coolant_temp_c=120.0,
            control_module_voltage_v=11.5,
            oil_pressure_kpa=40.0,
        )
        categories = {f.category for f in findings}
        assert {
            FaultCategory.COOLING,
            FaultCategory.ELECTRICAL,
            FaultCategory.LUBRICATION,
        } <= categories

    def test_sensor_open_circuit(self) -> None:
        (finding,) = run_rules(RuleEngine(), 60, 62, coolant_temp_c=-40.0)
        assert finding.category is FaultCategory.SENSOR

    def test_missing_data_never_assumed(self) -> None:
        assert (
            run_rules(
                RuleEngine(),
                60,
                120,
                coolant_temp_c=None,
                control_module_voltage_v=None,
                oil_pressure_kpa=None,
            )
            == []
        )

    def test_thresholds_are_configurable(self) -> None:
        strict = DiagnosticThresholds(coolant_warning_c=88.0, coolant_critical_c=120.0)
        findings = run_rules(RuleEngine(strict), 60, 90)
        assert [f.key for f in findings] == ["rule:coolant_temperature"]

    def test_threshold_ordering_is_validated(self) -> None:
        with pytest.raises(ValueError):
            DiagnosticThresholds(coolant_warning_c=110.0, coolant_critical_c=100.0)

    def test_electric_vehicles_skip_engine_rules(self) -> None:
        engine = RuleEngine(vehicle=VehicleContext(FuelType.ELECTRIC))
        findings = run_rules(engine, 60, 100, control_module_voltage_v=11.0, oil_pressure_kpa=30.0)
        assert not [f for f in findings if f.category is not FaultCategory.COOLING]

    def test_reset_clears_state(self) -> None:
        engine = RuleEngine()
        run_rules(engine, 60, 80, coolant_temp_c=120.0)
        engine.reset()
        assert engine.evaluate(window(end=82, coolant_temp_c=120.0)) == []


def _finding(source: DiagnosticSource, severity: Severity, category: FaultCategory) -> Finding:
    return Finding(f"{source.value}:{category.value}", source, category, severity, "t", "e")


OK_CLASSIFIER = ClassifierResult(ModelRunStatus.OK, labels=(), model_version="test")
OK_ANOMALY = AnomalyResult(ModelRunStatus.OK, score=0.4, threshold=0.6)


class TestHealthScore:
    def test_unavailable_without_sufficient_data(self) -> None:
        quality = window(seconds=10).quality()
        health = compute_health_score([], OK_CLASSIFIER, OK_ANOMALY, quality)
        assert health.score is None
        assert not health.available
        assert "Insufficient" in health.reason

    def test_full_score_without_findings(self) -> None:
        health = compute_health_score([], OK_CLASSIFIER, OK_ANOMALY, window().quality())
        assert health.score == 100
        assert health.components == ()

    def test_penalties_are_itemised_and_bounded(self) -> None:
        findings = [
            _finding(DiagnosticSource.RULE, Severity.CRITICAL, c)
            for c in (
                FaultCategory.COOLING,
                FaultCategory.ELECTRICAL,
                FaultCategory.LUBRICATION,
                FaultCategory.SENSOR,
            )
        ]
        health = compute_health_score(
            findings, OK_CLASSIFIER, OK_ANOMALY, window().quality(), recent_alerts=50
        )
        assert health.score is not None and 0 <= health.score <= 100
        assert len(health.components) >= 4
        assert all(c.explanation for c in health.components)

    def test_model_output_reduces_score_only_when_positive(self) -> None:
        classifier = ClassifierResult(
            ModelRunStatus.OK,
            labels=(LabelPrediction(FaultCategory.FUEL, 0.9, 0.5, LabelState.POSITIVE),),
        )
        with_model = compute_health_score([], classifier, OK_ANOMALY, window().quality())
        assert with_model.score is not None and with_model.score < 100

    def test_bands(self) -> None:
        assert [band_for(s) for s in (100, 70, 40, 10)] == ["Good", "Fair", "Poor", "Severe"]


class TestRecommendations:
    def test_no_abnormality_never_claims_safety(self) -> None:
        (text,) = recommend(DiagnosticStatus.NO_ABNORMALITY, [])
        assert "does not confirm that the vehicle is safe" in text

    def test_findings_point_to_a_qualified_mechanic(self) -> None:
        finding = _finding(DiagnosticSource.RULE, Severity.CRITICAL, FaultCategory.COOLING)
        assert any(MECHANIC in r for r in recommend(DiagnosticStatus.CRITICAL, [finding]))

    def test_insufficient_and_stale_are_explained(self) -> None:
        assert recommend(DiagnosticStatus.INSUFFICIENT_DATA, [])
        assert recommend(DiagnosticStatus.STALE, [])
