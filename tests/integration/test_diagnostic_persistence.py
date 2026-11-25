"""Diagnostic history, alert deduplication/cooldown, model metadata and the 0002 migration."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select

from smartdrive.ai.model_registry import ModelRegistry
from smartdrive.config.constants import DataSource, DiagnosticSource, FaultCategory, Severity
from smartdrive.database.connection import Database
from smartdrive.database.models import AlertRecord, DiagnosticAssessmentRecord, VehicleRecord
from smartdrive.database.repositories import VehicleRepository
from smartdrive.database.repositories.diagnostic_repository import DiagnosticRepository
from smartdrive.models.diagnostic import (
    AnomalyResult,
    ClassifierResult,
    DiagnosticAssessment,
    DiagnosticStatus,
    Finding,
    HealthScore,
    ModelRunStatus,
)
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.services.diagnostic_service import DiagnosticService
from tests.unit.test_diagnostics_core import window

pytestmark = pytest.mark.integration

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
HISTORY_S = 10.0
COOLDOWN_S = 60.0

OVERHEAT = Finding(
    key="rule:coolant_temperature",
    source=DiagnosticSource.RULE,
    category=FaultCategory.COOLING,
    severity=Severity.WARNING,
    title="Coolant temperature above normal range",
    explanation="Coolant averaged 108 °C over 10 s.",
    evidence={"coolant_10s_mean_c": 108.0},
)


def assessment(
    vehicle_id: int | None, at: datetime, *findings: Finding, session_id: int | None = None
) -> DiagnosticAssessment:
    severity = max(
        (f.severity for f in findings),
        default=Severity.NORMAL,
        key=lambda s: ["unknown", "normal", "information", "warning", "critical"].index(s.value),
    )
    status = {
        Severity.CRITICAL: DiagnosticStatus.CRITICAL,
        Severity.WARNING: DiagnosticStatus.WARNING,
    }.get(severity, DiagnosticStatus.NO_ABNORMALITY)
    return DiagnosticAssessment(
        timestamp=at,
        elapsed_s=0.0,
        data_source=DataSource.SIMULATION,
        status=status,
        severity=severity,
        findings=tuple(findings),
        quality=window().quality(),
        classifier=ClassifierResult(ModelRunStatus.OK, model_version="1.1.0"),
        anomaly=AnomalyResult(ModelRunStatus.OK, score=0.42, threshold=0.6),
        health=HealthScore(85, "Good", ()),
        recommendations=("Have the vehicle inspected by a qualified mechanic.",),
        vehicle_id=vehicle_id,
        session_id=session_id,
    )


@pytest.fixture
def vehicle_id(database: Database, vehicle_profile: VehicleProfile) -> int:
    with database.session() as session:
        return VehicleRepository(session).add(vehicle_profile).id


@pytest.fixture
def service(database: Database) -> DiagnosticService:
    return DiagnosticService(database)


def record(service: DiagnosticService, a: DiagnosticAssessment) -> object:
    return service.record(a, history_interval_s=HISTORY_S, alert_cooldown_s=COOLDOWN_S)


def alerts(database: Database) -> list[AlertRecord]:
    with database.session() as session:
        return list(session.scalars(select(AlertRecord).order_by(AlertRecord.id)))


def assessment_count(database: Database) -> int:
    with database.session() as session:
        return int(session.scalar(select(func.count(DiagnosticAssessmentRecord.id))) or 0)


class TestHistory:
    def test_nothing_is_saved_without_a_vehicle(
        self, service: DiagnosticService, database: Database
    ) -> None:
        outcome = record(service, assessment(None, T0, OVERHEAT))
        assert outcome.assessment_id is None  # type: ignore[attr-defined]
        assert assessment_count(database) == 0
        assert alerts(database) == []

    def test_steady_state_is_throttled_but_changes_are_saved(
        self, service: DiagnosticService, database: Database, vehicle_id: int
    ) -> None:
        for second in range(0, 10, 2):
            record(service, assessment(vehicle_id, T0 + timedelta(seconds=second)))
        assert assessment_count(database) == 1
        record(service, assessment(vehicle_id, T0 + timedelta(seconds=11)))
        assert assessment_count(database) == 2
        record(service, assessment(vehicle_id, T0 + timedelta(seconds=12), OVERHEAT))
        assert assessment_count(database) == 3

    def test_findings_are_stored_with_context(
        self, service: DiagnosticService, database: Database, vehicle_id: int
    ) -> None:
        record(service, assessment(vehicle_id, T0, OVERHEAT))
        (entry,) = service.history(vehicle_id=vehicle_id)
        assert entry.finding_key == OVERHEAT.key
        assert entry.source is DiagnosticSource.RULE
        assert entry.data_source is DataSource.SIMULATION
        assert entry.explanation["evidence"] == {"coolant_10s_mean_c": 108.0}
        assert entry.recommendation
        (point,) = service.health_trend(vehicle_id)
        assert point.health_score == 85

    def test_history_filters(self, service: DiagnosticService, vehicle_id: int) -> None:
        model = replace(
            OVERHEAT,
            key="model:cooling",
            source=DiagnosticSource.CLASSIFIER,
            title="Model: cooling abnormality pattern",
            probability=0.9,
        )
        record(service, assessment(vehicle_id, T0, OVERHEAT, model))
        assert len(service.history(vehicle_id=vehicle_id)) == 2
        assert len(service.history(source=DiagnosticSource.CLASSIFIER)) == 1
        assert len(service.history(severities=[Severity.CRITICAL])) == 0
        assert len(service.history(data_source=DataSource.LIVE)) == 0
        assert len(service.history(search="oil pressure")) == 0
        assert len(service.history(search="cooling abnormality")) == 1


class TestAlerts:
    def test_repeats_within_cooldown_are_deduplicated(
        self, service: DiagnosticService, database: Database, vehicle_id: int
    ) -> None:
        first = record(service, assessment(vehicle_id, T0, OVERHEAT))
        assert len(first.new_alerts) == 1  # type: ignore[attr-defined]
        for second in range(2, 40, 2):
            outcome = record(
                service, assessment(vehicle_id, T0 + timedelta(seconds=second), OVERHEAT)
            )
            assert outcome.new_alerts == ()  # type: ignore[attr-defined]
        (alert,) = alerts(database)
        assert alert.occurrence_count == 20
        assert alert.source is DiagnosticSource.RULE
        assert alert.vehicle_id == vehicle_id

    def test_new_alert_after_cooldown_gap(
        self, service: DiagnosticService, database: Database, vehicle_id: int
    ) -> None:
        record(service, assessment(vehicle_id, T0, OVERHEAT))
        record(service, assessment(vehicle_id, T0 + timedelta(seconds=COOLDOWN_S + 5), OVERHEAT))
        assert len(alerts(database)) == 2

    def test_escalation_updates_existing_alert(
        self, service: DiagnosticService, database: Database, vehicle_id: int
    ) -> None:
        record(service, assessment(vehicle_id, T0, OVERHEAT))
        critical = replace(OVERHEAT, severity=Severity.CRITICAL, title="Coolant critically high")
        record(service, assessment(vehicle_id, T0 + timedelta(seconds=4), critical))
        (alert,) = alerts(database)
        assert alert.severity is Severity.CRITICAL
        assert alert.title == "Coolant critically high"

    def test_information_findings_do_not_alert(
        self, service: DiagnosticService, database: Database, vehicle_id: int
    ) -> None:
        info = replace(
            OVERHEAT,
            key="anomaly:telemetry_pattern",
            source=DiagnosticSource.ANOMALY_DETECTOR,
            severity=Severity.INFORMATION,
        )
        record(service, assessment(vehicle_id, T0, info))
        assert alerts(database) == []
        assert service.recent_alert_count(vehicle_id) == 0

    def test_alerts_are_per_vehicle(
        self,
        service: DiagnosticService,
        database: Database,
        vehicle_id: int,
        vehicle_profile: VehicleProfile,
    ) -> None:
        with database.session() as session:
            other = (
                VehicleRepository(session)
                .add(vehicle_profile.model_copy(update={"name": "Other", "vin": None}))
                .id
            )
        record(service, assessment(vehicle_id, T0, OVERHEAT))
        record(service, assessment(other, T0, OVERHEAT))
        assert len(alerts(database)) == 2


def test_shipped_model_metadata_is_registered(
    service: DiagnosticService, database: Database
) -> None:
    models = ModelRegistry().load()
    service.register_models(models)
    service.register_models(models)
    with database.session() as session:
        active = DiagnosticRepository(session).active_models()
    assert {m.name for m in active} == {"fault_classifier", "anomaly_detector"}
    assert all(m.trained_on_synthetic_data for m in active)
    assert all(len(m.sha256) == 64 for m in active)


def test_upgrade_from_phase_2_schema_preserves_records(tmp_path: Path) -> None:
    db = Database(tmp_path / "phase2.db")
    db.upgrade("0001")
    with closing(sqlite3.connect(db.path)) as conn:
        conn.execute(
            "INSERT INTO vehicles (name, manufacturer, model, year, fuel_type, transmission,"
            " mileage_km, notes, is_active, created_at, updated_at) VALUES"
            " ('Old car','Make','Model',2015,'petrol','manual',1000,'',1,"
            "'2026-01-01 00:00:00','2026-01-01 00:00:00')"
        )
        conn.execute(
            "INSERT INTO alerts (vehicle_id, created_at, last_occurrence_at, severity, category,"
            " title, message, dedup_key, occurrence_count) VALUES"
            " (1,'2026-01-01 00:00:00','2026-01-01 00:00:00','warning','cooling','Old alert',"
            "'', 'k', 1)"
        )
        conn.commit()
    assert "diagnostic_assessments" not in inspect(db.engine).get_table_names()
    db.upgrade()
    assert db.current_revision() == db.head_revision()
    assert "diagnostic_assessments" in inspect(db.engine).get_table_names()
    with db.session() as session:
        (vehicle,) = session.scalars(select(VehicleRecord))
        (alert,) = session.scalars(select(AlertRecord))
    assert vehicle.name == "Old car"
    assert alert.title == "Old alert"
    assert alert.source is None
    db.downgrade("0001")
    with db.session() as session:
        assert session.scalar(select(func.count(VehicleRecord.id))) == 1
    db.dispose()
