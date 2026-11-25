"""InferenceWorker slots, called directly on the test thread.

In the application these run in a QThread, which the coverage tracer does not follow; calling the
slots directly verifies the same logic deterministically: model loading (including a failing
registry), analysis without and with persistence, and error reporting.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smartdrive.ai.model_registry import LoadedModels, ModelRegistry
from smartdrive.config.constants import DataSource, Severity
from smartdrive.config.settings import DiagnosticSettings
from smartdrive.database.connection import Database
from smartdrive.database.repositories.vehicle_repository import VehicleRepository
from smartdrive.models.diagnostic import DiagnosticAssessment, DiagnosticStatus
from smartdrive.models.telemetry import SENSOR_FIELDS
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.services.diagnostic_service import DiagnosticService
from smartdrive.ui.workers.inference_worker import (
    InferenceRequest,
    InferenceResult,
    InferenceWorker,
)

pytestmark = pytest.mark.ui

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


class BrokenRegistry(ModelRegistry):
    def load(self) -> LoadedModels:
        raise RuntimeError("disk on fire")


def request(
    *, coolant: float, vehicle_id: int | None = None, generation: int = 1, at: int = 60
) -> InferenceRequest:
    times = [float(t) for t in range(at - 60, at)]
    # Like TelemetryBuffer.snapshot: every sensor present, NaN where a reading is missing.
    readings = {
        "rpm": 2200.0,
        "speed_kph": 60.0,
        "coolant_temp_c": coolant,
        "engine_load_pct": 40.0,
        "battery_voltage_v": 14.1,
        "oil_pressure_kpa": 300.0,
    }
    series = {key: [readings.get(key, math.nan)] * 60 for key in SENSOR_FIELDS}
    return InferenceRequest(
        generation=generation,
        times=times,
        series=series,
        data_source=DataSource.SIMULATION,
        timestamp=NOW,
        data_age_s=0.5,
        stale_after_s=5.0,
        vehicle_id=vehicle_id,
        session_id=None,
        vehicle=None,
        settings=DiagnosticSettings(),
        alert_cooldown_s=300.0,
    )


def collect(worker: InferenceWorker) -> tuple[list[object], list[tuple[int, str]], list[object]]:
    finished: list[object] = []
    failed: list[tuple[int, str]] = []
    loaded: list[object] = []
    worker.finished.connect(finished.append)
    worker.failed.connect(lambda g, m: failed.append((g, m)))
    worker.models_loaded.connect(loaded.append)
    return finished, failed, loaded


def test_failing_registry_is_reported_and_rules_still_run(database: Database) -> None:
    worker = InferenceWorker(BrokenRegistry(), DiagnosticService(database))
    finished, failed, loaded = collect(worker)
    worker.load_models()
    assert len(loaded) == 1
    models = loaded[0]
    assert isinstance(models, LoadedModels)
    assert models.classifier is None and "disk on fire" in models.messages["registry"]

    for at in range(60, 84, 2):  # rules require the condition to persist, as in a live drive
        worker.analyse(request(coolant=118.0, at=at))
    assert not failed
    result = finished[-1]
    assert isinstance(result, InferenceResult) and result.outcome is None
    assessment = result.assessment
    assert isinstance(assessment, DiagnosticAssessment)
    assert any(f.severity is Severity.CRITICAL for f in assessment.findings)


def test_analysis_with_vehicle_is_persisted_and_alerts(
    database: Database, vehicle_profile: VehicleProfile, tmp_path: Path
) -> None:
    with database.session() as session:
        vehicle_id = VehicleRepository(session).add(vehicle_profile).id
    worker = InferenceWorker(ModelRegistry(tmp_path / "no-models"), DiagnosticService(database))
    finished, failed, _ = collect(worker)
    worker.load_models()
    for at in range(60, 84, 2):
        worker.analyse(request(coolant=118.0, vehicle_id=vehicle_id, generation=7, at=at))
    assert not failed
    results = [r for r in finished if isinstance(r, InferenceResult)]
    assert len(results) == len(finished) == 12
    assert all(r.generation == 7 and r.persistence_error is None for r in results)
    outcomes = [r.outcome for r in results if r.outcome is not None]
    assert len(outcomes) == 12
    assert any(o.assessment_id is not None for o in outcomes)
    assert any(o.new_alerts for o in outcomes)
    final = results[-1].assessment
    assert isinstance(final, DiagnosticAssessment)
    assert final.status is DiagnosticStatus.CRITICAL

    worker.reset()  # the next analysis starts a fresh stream rather than reusing state
    worker.analyse(request(coolant=88.0, vehicle_id=vehicle_id, generation=8))
    second = finished[-1]
    assert isinstance(second, InferenceResult)
    assert isinstance(second.assessment, DiagnosticAssessment)
    assert second.assessment.status is not DiagnosticStatus.CRITICAL


def test_bad_input_reports_failure_with_generation(database: Database, tmp_path: Path) -> None:
    worker = InferenceWorker(ModelRegistry(tmp_path), DiagnosticService(database))
    finished, failed, _ = collect(worker)
    worker.load_models()
    worker.analyse("not a request")
    assert not finished and not failed

    broken = request(coolant=90.0, generation=3)
    object.__setattr__(broken, "series", {"rpm": [1.0, 2.0]})  # length mismatch with times
    worker.analyse(broken)
    assert not finished
    assert failed and failed[0][0] == 3 and "Diagnostic analysis failed" in failed[0][1]
