"""Generate the synthetic dataset, train both models, evaluate them and write all artefacts.

    python scripts/train_models.py                 # full run (writes the shipped models)
    python scripts/train_models.py --profile small --artifacts-dir out/models --reports-dir out/ml

Outputs:
- src/smartdrive/ai/artifacts/   model files + manifest.json (SHA-256, versions, metadata)
- docs/ml/                       metrics, model card, dataset card, evaluation report, figures
- datasets/<version>/            dataset.npz (git-ignored) + metadata.json + sessions.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import scipy
import sklearn

from smartdrive.ai.dataset import (
    Dataset,
    DatasetConfig,
    assign_splits,
    build_dataset,
    plan_sessions,
    save_dataset,
    validate_dataset,
)
from smartdrive.ai.evaluation import evaluate_anomaly, evaluate_catalogue, evaluate_classifier
from smartdrive.ai.features import FEATURE_SCHEMA_VERSION
from smartdrive.ai.model_registry import (
    ANOMALY_NAME,
    CLASSIFIER_NAME,
    MANIFEST_NAME,
    ModelRegistry,
    sha256_file,
)
from smartdrive.ai.reporting import write_reports
from smartdrive.ai.training import TrainingConfig, train_anomaly_detector, train_classifier
from smartdrive.config.constants import DataSource
from smartdrive.config.settings import DiagnosticSettings
from smartdrive.core.telemetry_processing import build_sample
from smartdrive.core.telemetry_window import TelemetryWindow
from smartdrive.services.diagnostic_engine import DiagnosticEngine
from smartdrive.services.simulator import VehicleSimulator

ROOT = Path(__file__).resolve().parents[1]
MODEL_VERSION = "1.1.0"


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def library_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "joblib": joblib.__version__,
    }


def save_artifact(artifact: dict[str, Any], directory: Path, name: str) -> Path:
    # Runtime inference scores one window at a time; a thread pool per call only adds latency.
    artifact["pipeline"][-1].set_params(n_jobs=1)
    path = directory / f"{name}-{MODEL_VERSION}.joblib"
    joblib.dump(artifact, path, compress=3)
    return path


def measure_latency(
    dataset_config: DatasetConfig, models: Any, sessions: int = 3
) -> dict[str, float]:
    plans = plan_sessions(dataset_config)
    splits = assign_splits(plans, dataset_config)
    test_plans = [p for p in plans if splits[p.session_id] == "test" and p.definition.faults]
    engine = DiagnosticEngine(models, DiagnosticSettings())
    timings: list[float] = []
    for plan in test_plans[:sessions]:
        engine.reset()
        simulator = VehicleSimulator(plan.simulation_config())
        history = []
        for step in simulator.iter_steps(plan.duration_s, 1.0):
            if step.readings is None:
                continue
            sample = build_sample(datetime.now(UTC), step.readings).sample
            history.append((step.elapsed_s, sample))
            if len(history) >= 60 and int(step.elapsed_s) % 5 == 0:
                window = TelemetryWindow.from_samples(history[-90:])
                started = time.perf_counter()
                engine.assess(
                    window, data_source=DataSource.SIMULATION, timestamp=datetime.now(UTC)
                )
                timings.append((time.perf_counter() - started) * 1000)
    ordered = sorted(timings)
    return {
        "runs": float(len(timings)),
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[int(0.95 * (len(ordered) - 1))],
        "max_ms": ordered[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--profile", choices=("full", "small"), default="full")
    parser.add_argument(
        "--artifacts-dir", type=Path, default=ROOT / "src" / "smartdrive" / "ai" / "artifacts"
    )
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "docs" / "ml")
    parser.add_argument("--datasets-dir", type=Path, default=ROOT / "datasets")
    args = parser.parse_args()

    dataset_config = DatasetConfig() if args.profile == "full" else DatasetConfig.small()
    training_config = (
        TrainingConfig()
        if args.profile == "full"
        else TrainingConfig(
            n_estimators=40, importance_repeats=1, grid=({"max_depth": 12, "min_samples_leaf": 2},)
        )
    )

    log(f"Generating dataset {dataset_config.version} ({args.profile})")
    started = time.perf_counter()
    dataset: Dataset = build_dataset(
        dataset_config,
        progress=lambda done, total: log(f"  {done}/{total} sessions") if done % 50 == 0 else None,
    )
    log(f"  {dataset.features.shape[0]} windows in {time.perf_counter() - started:.1f} s")
    report = validate_dataset(dataset)
    for warning in report.warnings:
        log(f"  validation warning: {warning}")
    if not report.ok:
        for error in report.errors:
            log(f"  validation error: {error}")
        return 1
    save_dataset(dataset, args.datasets_dir / dataset_config.version)

    log("Training Random Forest (model selection on validation split)")
    started = time.perf_counter()
    classifier_training = train_classifier(dataset, training_config)
    classifier_seconds = time.perf_counter() - started
    for row in classifier_training.selection:
        log(f"  {row['params']} -> validation macro-F1 {row['validation_macro_f1']}")

    log("Training Isolation Forest on normal training windows")
    started = time.perf_counter()
    anomaly_artifact = train_anomaly_detector(dataset, training_config)
    anomaly_seconds = time.perf_counter() - started

    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now(UTC).isoformat(timespec="seconds")
    common = {
        "version": MODEL_VERSION,
        "trained_at": trained_at,
        "synthetic": True,
        "dataset_version": dataset_config.version,
        "dataset_fingerprint": dataset.metadata["fingerprint"],
        "dataset_source": dataset.metadata["source"],
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "sklearn_version": sklearn.__version__,
        "library_versions": library_versions(),
        "training_config": training_config.to_dict(),
    }
    classifier_path = save_artifact(
        classifier_training.artifact, args.artifacts_dir, CLASSIFIER_NAME
    )
    anomaly_path = save_artifact(anomaly_artifact, args.artifacts_dir, ANOMALY_NAME)
    forest = classifier_training.artifact["pipeline"][-1]
    isolation = anomaly_artifact["pipeline"][-1]
    manifest = {
        CLASSIFIER_NAME: {
            **common,
            "name": CLASSIFIER_NAME,
            "model_type": "RandomForestClassifier (multi-label)",
            "file": classifier_path.name,
            "sha256": sha256_file(classifier_path),
            "parameters": {
                k: forest.get_params()[k]
                for k in (
                    "n_estimators",
                    "max_depth",
                    "min_samples_leaf",
                    "max_features",
                    "class_weight",
                )
            },
            "thresholds": classifier_training.artifact["thresholds"],
            "labels": classifier_training.artifact["labels"],
            "training_seconds": round(classifier_seconds, 1),
        },
        ANOMALY_NAME: {
            **common,
            "name": ANOMALY_NAME,
            "model_type": "IsolationForest",
            "file": anomaly_path.name,
            "sha256": sha256_file(anomaly_path),
            "parameters": {
                k: isolation.get_params()[k]
                for k in ("n_estimators", "contamination", "max_samples")
            },
            "thresholds": anomaly_artifact["thresholds"],
            "baseline_rows": anomaly_artifact["baseline_rows"],
            "training_seconds": round(anomaly_seconds, 1),
        },
    }
    for stale in args.artifacts_dir.glob("*.joblib"):
        if stale not in (classifier_path, anomaly_path):
            stale.unlink()

    log("Verifying artefacts through the trusted registry")
    registry = ModelRegistry(args.artifacts_dir)
    (args.artifacts_dir / MANIFEST_NAME).write_text(
        json.dumps({"schema": 1, "models": list(manifest.values())}, indent=2), "utf-8"
    )
    loaded = registry.load()
    if loaded.classifier is None or loaded.anomaly is None:
        log(f"  registry refused artefacts: {loaded.messages}")
        return 1

    log("Evaluating on the held-out test sessions")
    metrics = evaluate_classifier(loaded.classifier, dataset)
    anomaly_metrics = evaluate_anomaly(loaded.anomaly, dataset)
    manifest[CLASSIFIER_NAME]["evaluation"] = {
        "test_macro_f1": metrics["all_rows_model_output"]["macro_f1"],
        "test_micro_f1": metrics["all_rows_model_output"]["micro_f1"],
        "rule_baseline_macro_f1": metrics["rule_baseline"]["macro_f1"],
        "test_sessions": metrics["sessions"],
    }
    manifest[ANOMALY_NAME]["evaluation"] = {
        "test_roc_auc": anomaly_metrics["roc_auc_normal_vs_abnormal"],
        "window_false_positive_rate": anomaly_metrics["window_level"]["false_positive_rate"],
    }
    manifest[CLASSIFIER_NAME]["global_importance"] = classifier_training.artifact[
        "global_importance"
    ][:25]
    (args.artifacts_dir / MANIFEST_NAME).write_text(
        json.dumps({"schema": 1, "models": list(manifest.values())}, indent=2), "utf-8"
    )

    log("Running built-in scenarios through the complete hybrid engine")
    catalogue = evaluate_catalogue(
        registry.load(),
        **({} if args.profile == "full" else {"seeds": (9101,), "duration_s": 240}),
    )
    healthy_alarm = max(e["alarm_rate"] for e in catalogue.values() if e["healthy"])
    log(f"  worst healthy-scenario alarm rate {healthy_alarm:.3f}")
    manifest[CLASSIFIER_NAME]["evaluation"]["catalogue_worst_healthy_alarm_rate"] = healthy_alarm
    (args.artifacts_dir / MANIFEST_NAME).write_text(
        json.dumps({"schema": 1, "models": list(manifest.values())}, indent=2), "utf-8"
    )

    log("Measuring inference latency")
    latency = measure_latency(dataset_config, registry.load())

    test = dataset.mask("test")
    scores = loaded.anomaly.scores(dataset.features[test])
    abnormal = dataset.labels[test].any(axis=1)
    written = write_reports(
        args.reports_dir,
        metrics=metrics,
        anomaly=anomaly_metrics,
        dataset_meta=dataset.metadata,
        manifest=manifest,
        selection=classifier_training.selection,
        importance=classifier_training.artifact["global_importance"],
        normal_scores=scores[~abnormal],
        abnormal_scores=scores[abnormal],
        latency=latency,
        catalogue=catalogue,
    )
    for path in written:
        log(f"  wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    log(
        f"Done. Test macro-F1 {metrics['all_rows_model_output']['macro_f1']:.3f} "
        f"(rules {metrics['rule_baseline']['macro_f1']:.3f}); anomaly ROC AUC "
        f"{anomaly_metrics['roc_auc_normal_vs_abnormal']:.3f}; median inference "
        f"{latency['median_ms']:.1f} ms"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
