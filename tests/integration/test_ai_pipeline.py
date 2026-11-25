"""Dataset generation, training, trusted model loading, inference, explanations and the hybrid
engine. Uses a deliberately tiny dataset so it runs in seconds; full training is a separate,
reproducible script (scripts/train_models.py)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pytest
import sklearn

from smartdrive.ai.dataset import (
    LABELS,
    Dataset,
    DatasetConfig,
    assign_splits,
    build_dataset,
    dataset_fingerprint,
    load_dataset,
    plan_sessions,
    save_dataset,
    validate_dataset,
)
from smartdrive.ai.evaluation import (
    binary_metrics,
    evaluate_anomaly,
    evaluate_catalogue,
    evaluate_classifier,
)
from smartdrive.ai.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, extract_features
from smartdrive.ai.model_registry import (
    ANOMALY_NAME,
    CLASSIFIER_NAME,
    MANIFEST_NAME,
    LoadedModels,
    LoadStatus,
    ModelRegistry,
    sha256_file,
)
from smartdrive.ai.reporting import write_reports
from smartdrive.ai.training import TrainingConfig, train_anomaly_detector, train_classifier
from smartdrive.config.constants import DataSource, DiagnosticSource, FaultCategory, Severity
from smartdrive.config.settings import DiagnosticSettings
from smartdrive.core.telemetry_window import TelemetryWindow
from smartdrive.models.diagnostic import DiagnosticStatus, ModelRunStatus
from smartdrive.services.diagnostic_engine import DiagnosticEngine
from smartdrive.services.scenarios import SCENARIOS, ScenarioId
from smartdrive.services.simulator import SimulationConfig, SimulationSource
from tests.unit.test_diagnostics_core import window

pytestmark = pytest.mark.integration

TINY = DatasetConfig.small(
    version="sdg-ds-tiny",
    healthy_sessions=3,
    sessions_per_fault=4,
    multiple_fault_sessions=2,
    degraded_data_sessions=3,
    min_duration_s=230,
    max_duration_s=250,
)
FAST = TrainingConfig(
    n_estimators=25,
    anomaly_estimators=50,
    importance_repeats=1,
    grid=({"max_depth": 10, "min_samples_leaf": 2},),
    n_jobs=1,
)


@pytest.fixture(scope="module")
def tiny_dataset() -> Dataset:
    return build_dataset(TINY)


@pytest.fixture(scope="module")
def trained_dir(tiny_dataset: Dataset, tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("models")
    classifier = train_classifier(tiny_dataset, FAST).artifact
    anomaly = train_anomaly_detector(tiny_dataset, FAST)
    write_models(directory, classifier, anomaly)
    return directory


def write_models(directory: Path, classifier: dict[str, Any], anomaly: dict[str, Any]) -> None:
    entries = []
    for name, artifact, model_type in (
        (CLASSIFIER_NAME, classifier, "RandomForestClassifier"),
        (ANOMALY_NAME, anomaly, "IsolationForest"),
    ):
        path = directory / f"{name}-test.joblib"
        joblib.dump(artifact, path, compress=3)
        entries.append(
            {
                "name": name,
                "version": "test",
                "file": path.name,
                "sha256": sha256_file(path),
                "model_type": model_type,
                "trained_at": datetime.now(UTC).isoformat(),
                "synthetic": True,
                "dataset_version": TINY.version,
                "dataset_source": "test",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "sklearn_version": sklearn.__version__,
            }
        )
    (directory / MANIFEST_NAME).write_text(json.dumps({"schema": 1, "models": entries}), "utf-8")


@pytest.fixture(scope="module")
def shipped() -> LoadedModels:
    return ModelRegistry().load()


@pytest.fixture
def model_copy(trained_dir: Path, tmp_path: Path) -> Iterator[Path]:
    target = tmp_path / "models"
    shutil.copytree(trained_dir, target)
    yield target


def edit_manifest(directory: Path, name: str, **changes: Any) -> None:
    path = directory / MANIFEST_NAME
    data = json.loads(path.read_text("utf-8"))
    for entry in data["models"]:
        if entry["name"] == name:
            entry.update(changes)
    path.write_text(json.dumps(data), "utf-8")


class TestDataset:
    def test_plan_is_reproducible(self) -> None:
        assert [p.describe() for p in plan_sessions(TINY)] == [
            p.describe() for p in plan_sessions(TINY)
        ]

    def test_healthy_sessions_cover_every_driving_pattern(self) -> None:
        config = replace(TINY, healthy_sessions=12)
        patterns = {p.definition.pattern for p in plan_sessions(config) if p.group == "healthy"}
        assert len(patterns) == 6

    def test_splits_assign_whole_sessions_and_every_group(self) -> None:
        plans = plan_sessions(TINY)
        splits = assign_splits(plans, TINY)
        assert set(splits) == {p.session_id for p in plans}
        for group in {p.group for p in plans}:
            members = {splits[p.session_id] for p in plans if p.group == group}
            assert {"test", "validation"} <= members

    def test_no_session_spans_two_splits(self, tiny_dataset: Dataset) -> None:
        for session in np.unique(tiny_dataset.session_ids):
            assert len(set(tiny_dataset.split[tiny_dataset.session_ids == session])) == 1

    def test_dataset_validates(self, tiny_dataset: Dataset) -> None:
        report = validate_dataset(tiny_dataset)
        assert report.ok, report.errors
        assert tiny_dataset.features.shape[1] == len(FEATURE_NAMES)
        assert tiny_dataset.metadata["synthetic"] is True

    def test_labels_come_from_ground_truth(self, tiny_dataset: Dataset) -> None:
        healthy = {int(s["session_id"]) for s in tiny_dataset.sessions if s["group"] == "healthy"}
        mask = np.isin(tiny_dataset.session_ids, list(healthy))
        assert mask.any()
        assert tiny_dataset.labels[mask].sum() == 0
        assert tiny_dataset.labels.sum(axis=0).min() > 0

    def test_validation_rejects_leaking_feature_names(self, tiny_dataset: Dataset) -> None:
        leaky = replace(tiny_dataset, feature_names=("scenario_id", *FEATURE_NAMES[1:]))
        assert not validate_dataset(leaky).ok

    def test_save_load_round_trip(self, tiny_dataset: Dataset, tmp_path: Path) -> None:
        save_dataset(tiny_dataset, tmp_path / "ds")
        loaded = load_dataset(tmp_path / "ds")
        assert np.array_equal(loaded.labels, tiny_dataset.labels)
        assert np.allclose(loaded.features, tiny_dataset.features, equal_nan=True)
        assert dataset_fingerprint(loaded) == dataset_fingerprint(tiny_dataset)

    def test_generation_is_reproducible(self, tiny_dataset: Dataset) -> None:
        small = replace(
            TINY,
            healthy_sessions=1,
            sessions_per_fault=1,
            multiple_fault_sessions=0,
            degraded_data_sessions=0,
        )
        assert dataset_fingerprint(build_dataset(small)) == dataset_fingerprint(
            build_dataset(small)
        )


class TestModelRegistry:
    def test_trusted_models_load(self, trained_dir: Path) -> None:
        models = ModelRegistry(trained_dir).load()
        assert models.status == {
            CLASSIFIER_NAME: LoadStatus.AVAILABLE,
            ANOMALY_NAME: LoadStatus.AVAILABLE,
        }
        assert models.classifier is not None and models.anomaly is not None

    def test_tampered_file_fails_integrity_check(self, model_copy: Path) -> None:
        artifact = next(model_copy.glob(f"{CLASSIFIER_NAME}-*.joblib"))
        artifact.write_bytes(artifact.read_bytes() + b"tampered")
        models = ModelRegistry(model_copy).load()
        assert models.status[CLASSIFIER_NAME] is LoadStatus.INTEGRITY_FAILED
        assert models.classifier is None
        assert models.status[ANOMALY_NAME] is LoadStatus.AVAILABLE

    def test_other_scikit_learn_version_is_incompatible(self, model_copy: Path) -> None:
        edit_manifest(model_copy, CLASSIFIER_NAME, sklearn_version="0.1.0")
        assert ModelRegistry(model_copy).load().status[CLASSIFIER_NAME] is LoadStatus.INCOMPATIBLE

    def test_other_feature_schema_is_incompatible(self, model_copy: Path) -> None:
        edit_manifest(model_copy, ANOMALY_NAME, feature_schema_version="fs-0")
        assert ModelRegistry(model_copy).load().status[ANOMALY_NAME] is LoadStatus.INCOMPATIBLE

    def test_missing_file_and_missing_manifest(self, model_copy: Path, tmp_path: Path) -> None:
        next(model_copy.glob(f"{ANOMALY_NAME}-*.joblib")).unlink()
        assert ModelRegistry(model_copy).load().status[ANOMALY_NAME] is LoadStatus.MISSING
        empty = ModelRegistry(tmp_path / "nothing").load()
        assert not empty.any_available
        assert set(empty.status.values()) == {LoadStatus.MISSING}

    def test_wrong_artifact_type_is_refused(self, model_copy: Path) -> None:
        artifact = next(model_copy.glob(f"{ANOMALY_NAME}-*.joblib"))
        joblib.dump({"artifact_type": "something.else"}, artifact)
        edit_manifest(model_copy, ANOMALY_NAME, sha256=sha256_file(artifact))
        assert ModelRegistry(model_copy).load().status[ANOMALY_NAME] is LoadStatus.INCOMPATIBLE

    def test_manifest_paths_cannot_escape_the_directory(self, model_copy: Path) -> None:
        edit_manifest(model_copy, CLASSIFIER_NAME, file="../../outside.joblib")
        assert ModelRegistry(model_copy).load().status[CLASSIFIER_NAME] is LoadStatus.MISSING


class TestShippedModels:
    """The artifacts bundled with the application."""

    def test_load_and_carry_metadata(self, shipped: LoadedModels) -> None:
        assert shipped.classifier is not None and shipped.anomaly is not None
        entry = shipped.manifest[CLASSIFIER_NAME]
        assert entry["synthetic"] is True
        assert entry["feature_schema_version"] == FEATURE_SCHEMA_VERSION
        assert entry["evaluation"]["test_macro_f1"] > 0
        assert entry["global_importance"]

    def test_explanations_are_exact_decompositions(self, shipped: LoadedModels) -> None:
        assert shipped.classifier is not None
        features = extract_features(window(coolant_temp_c=112.0))
        probabilities = shipped.classifier.probabilities(features)
        for index, category in enumerate(LABELS):
            explanation = shipped.classifier.explain(features, category)
            total = explanation.base_value + sum(c.contribution for c in explanation.contributions)
            assert total == pytest.approx(explanation.probability, abs=1e-6)
            assert explanation.probability == pytest.approx(float(probabilities[index]), abs=1e-6)

    def test_abstains_on_insufficient_data(self, shipped: LoadedModels) -> None:
        assert shipped.classifier is not None
        short = window(seconds=10)
        result = shipped.classifier.predict(
            extract_features(short),
            short.quality(),
        )
        assert result.status is ModelRunStatus.ABSTAINED
        assert result.labels == ()

    def test_lubrication_is_not_assessed_without_oil_pressure(self, shipped: LoadedModels) -> None:
        assert shipped.classifier is not None
        without_oil = window(oil_pressure_kpa=None, oil_temp_c=None)
        result = shipped.classifier.predict(extract_features(without_oil), without_oil.quality())
        assert result.status is ModelRunStatus.OK
        categories = {label.category for label in result.labels}
        assert FaultCategory.LUBRICATION not in categories
        assert FaultCategory.COOLING in categories

    def test_abstains_far_outside_training_distribution(self, shipped: LoadedModels) -> None:
        assert shipped.classifier is not None
        absurd = np.full(len(FEATURE_NAMES), 1e6)
        result = shipped.classifier.predict(absurd, window().quality())
        assert result.status is ModelRunStatus.ABSTAINED
        assert result.out_of_range_fraction is not None and result.out_of_range_fraction > 0.25


def assess_drive(
    models: LoadedModels | None,
    scenario: ScenarioId,
    *,
    seconds: int = 300,
    settings: DiagnosticSettings | None = None,
) -> list[Any]:
    engine = DiagnosticEngine(models, settings or DiagnosticSettings())
    source = SimulationSource(SimulationConfig(scenario=scenario, seed=21))
    source.open()
    samples: list[Any] = []
    assessments = []
    for step in range(seconds):
        frame = source.read(1.0)
        if frame.sample is not None:
            samples.append((frame.elapsed_s, frame.sample))
        if step % 2 == 1:
            assessments.append(
                engine.assess(
                    TelemetryWindow.from_samples(samples[-120:]),
                    data_source=DataSource.SIMULATION,
                    timestamp=datetime.now(UTC),
                )
            )
    return assessments


class TestHybridEngine:
    def test_insufficient_data_state(self, shipped: LoadedModels) -> None:
        first = assess_drive(shipped, ScenarioId.NORMAL, seconds=4)[0]
        assert first.status is DiagnosticStatus.INSUFFICIENT_DATA
        assert first.health.score is None
        assert first.classifier.status is ModelRunStatus.ABSTAINED

    def test_stale_data_state(self, shipped: LoadedModels) -> None:
        engine = DiagnosticEngine(shipped, DiagnosticSettings())
        result = engine.assess(
            window(),
            data_source=DataSource.SIMULATION,
            timestamp=datetime.now(UTC),
            data_age_s=30.0,
            stale_after_s=5.0,
        )
        assert result.status is DiagnosticStatus.STALE
        assert result.findings == ()

    def test_rules_keep_working_without_models(self) -> None:
        last = assess_drive(None, ScenarioId.OVERHEATING, seconds=400)[-1]
        assert last.classifier.status is ModelRunStatus.UNAVAILABLE
        assert any(f.source is DiagnosticSource.RULE for f in last.findings)
        assert last.status in (DiagnosticStatus.WARNING, DiagnosticStatus.CRITICAL)

    def test_machine_learning_can_be_turned_off(self, shipped: LoadedModels) -> None:
        settings = DiagnosticSettings(machine_learning_enabled=False)
        last = assess_drive(shipped, ScenarioId.OVERHEATING, seconds=400, settings=settings)[-1]
        assert last.classifier.status is ModelRunStatus.DISABLED
        assert all(f.source is DiagnosticSource.RULE for f in last.findings)

    def test_model_never_downgrades_a_critical_rule_finding(self, shipped: LoadedModels) -> None:
        engine = DiagnosticEngine(shipped, DiagnosticSettings())
        last = None
        for end in range(60, 120, 2):
            last = engine.assess(
                window(end=float(end), coolant_temp_c=124.0),
                data_source=DataSource.SIMULATION,
                timestamp=datetime.now(UTC),
            )
        assert last is not None
        rule = next(f for f in last.findings if f.key == "rule:coolant_temperature")
        assert rule.severity is Severity.CRITICAL
        assert last.severity is Severity.CRITICAL
        assert all(
            f.severity is not Severity.CRITICAL
            for f in last.findings
            if f.source is not DiagnosticSource.RULE
        )

    def test_fault_scenario_yields_explained_model_finding(self, shipped: LoadedModels) -> None:
        last = assess_drive(shipped, ScenarioId.ELECTRICAL, seconds=300)[-1]
        categories = {f.category for f in last.findings}
        assert FaultCategory.ELECTRICAL in categories
        assert FaultCategory.ELECTRICAL in last.explanations
        assert last.health.score is not None and last.health.score < 100


class TestEvaluationAndReporting:
    """The evaluation code that produces the published metrics, run end to end on tiny models."""

    def test_binary_metrics_match_hand_counts(self) -> None:
        truth = np.array([1, 1, 1, 0, 0, 0, 0, 1])
        predicted = np.array([1, 1, 0, 1, 0, 0, 0, 0])
        m = binary_metrics(truth, predicted)
        assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 2, 3)
        assert m["precision"] == pytest.approx(2 / 3, abs=1e-4)
        assert m["recall"] == 0.5
        assert m["false_positive_rate"] == 0.25
        assert binary_metrics(np.zeros(3), np.zeros(3))["f1"] == 0.0

    def test_metrics_and_reports_are_consistent(
        self, tiny_dataset: Dataset, trained_dir: Path, tmp_path: Path
    ) -> None:
        loaded = ModelRegistry(trained_dir).load()
        assert loaded.classifier is not None and loaded.anomaly is not None
        metrics = evaluate_classifier(loaded.classifier, tiny_dataset)
        anomaly = evaluate_anomaly(loaded.anomaly, tiny_dataset)
        catalogue = evaluate_catalogue(loaded, seeds=(9101,), duration_s=80)

        test_rows = int(tiny_dataset.mask("test").sum())
        overall = metrics["all_rows_model_output"]
        assert overall["rows"] == test_rows
        for counts in overall["per_label"].values():
            assert counts["tp"] + counts["fp"] + counts["fn"] + counts["tn"] == test_rows
        # The union can only add detections to the model alone.
        for label, counts in metrics["hybrid_union"]["per_label"].items():
            assert counts["tp"] >= overall["per_label"][label]["tp"]
        assert 0.0 <= anomaly["roc_auc_normal_vs_abnormal"] <= 1.0
        assert set(catalogue) == {s.value for s in SCENARIOS}
        assert all(entry["runs"] == 1 and entry["analyses"] > 0 for entry in catalogue.values())

        manifest = {
            e["name"]: {
                **e,
                "dataset_fingerprint": tiny_dataset.metadata["fingerprint"],
                "parameters": {"n_estimators": 25},
                "thresholds": {"standard": 0.5},
                "baseline_rows": 10,
            }
            for e in json.loads((trained_dir / MANIFEST_NAME).read_text("utf-8"))["models"]
        }
        test = tiny_dataset.mask("test")
        scores = loaded.anomaly.scores(tiny_dataset.features[test])
        abnormal = tiny_dataset.labels[test].any(axis=1)
        written = write_reports(
            tmp_path,
            metrics=metrics,
            anomaly=anomaly,
            dataset_meta=tiny_dataset.metadata,
            manifest=manifest,
            selection=[{"params": {"max_depth": 10}, "validation_macro_f1": 0.5}],
            importance=joblib.load(trained_dir / f"{CLASSIFIER_NAME}-test.joblib")[
                "global_importance"
            ],
            normal_scores=scores[~abnormal],
            abnormal_scores=scores[abnormal],
            latency={"runs": 1.0, "median_ms": 1.0, "p95_ms": 1.0, "max_ms": 1.0},
            catalogue=catalogue,
        )
        names = {p.name for p in written}
        assert {
            "metrics.json",
            "classification_report.json",
            "model_card.md",
            "dataset_card.md",
            "evaluation_report.md",
            "confusion_matrix.png",
            "feature_importance.png",
        } <= names
        assert all(p.stat().st_size > 0 for p in written)
        saved = json.loads((tmp_path / "metrics.json").read_text("utf-8"))
        assert saved["classifier"]["all_rows_model_output"]["macro_f1"] == overall["macro_f1"]
        report = (tmp_path / "evaluation_report.md").read_text("utf-8")
        assert f"{overall['macro_f1']:.3f}" in report
        assert "No real vehicle data was used" in report
