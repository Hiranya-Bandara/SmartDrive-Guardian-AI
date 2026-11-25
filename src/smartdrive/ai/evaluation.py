"""Evaluation on the held-out test split (independent simulated sessions)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import numpy as np
from sklearn.metrics import f1_score, hamming_loss, roc_auc_score

from smartdrive.ai.anomaly_detector import AnomalyDetector
from smartdrive.ai.classifier import MAX_OUT_OF_RANGE, FaultClassifier
from smartdrive.ai.dataset import LABELS, Dataset, iter_split_sessions
from smartdrive.ai.training import positive_probabilities
from smartdrive.config.constants import DataSource, Severity
from smartdrive.config.settings import DiagnosticSettings
from smartdrive.core.telemetry_processing import build_sample
from smartdrive.core.telemetry_window import WINDOW_SECONDS, TelemetryWindow
from smartdrive.services.diagnostic_engine import DiagnosticEngine
from smartdrive.services.scenarios import FAULT_CATEGORY, SCENARIOS
from smartdrive.services.simulator import SimulationConfig, VehicleSimulator

CALIBRATION_BINS: Final = 10
MISSING_COMPLETENESS: Final = 0.97
NOISY_SCALE: Final = 1.5


def binary_metrics(truth: np.ndarray, predicted: np.ndarray) -> dict[str, float | int]:
    truth = truth.astype(bool)
    predicted = predicted.astype(bool)
    tp = int(np.sum(truth & predicted))
    fp = int(np.sum(~truth & predicted))
    fn = int(np.sum(truth & ~predicted))
    tn = int(np.sum(~truth & ~predicted))

    def ratio(a: int, b: int) -> float:
        return round(a / b, 4) if b else 0.0

    precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "support": tp + fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": ratio(fp, fp + tn),
        "false_negative_rate": ratio(fn, fn + tp),
    }


def multilabel_metrics(truth: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    per_label = {
        c.value: binary_metrics(truth[:, i], predicted[:, i]) for i, c in enumerate(LABELS)
    }
    any_truth, any_pred = truth.any(axis=1), predicted.any(axis=1)
    return {
        "rows": len(truth),
        "per_label": per_label,
        "macro_f1": round(float(f1_score(truth, predicted, average="macro", zero_division=0)), 4),
        "micro_f1": round(float(f1_score(truth, predicted, average="micro", zero_division=0)), 4),
        "subset_accuracy": round(float(np.mean(np.all(truth == predicted, axis=1))), 4),
        "hamming_loss": round(float(hamming_loss(truth, predicted)), 4),
        "any_abnormality": binary_metrics(any_truth, any_pred),
    }


def calibration(truth: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    edges = np.linspace(0.0, 1.0, CALIBRATION_BINS + 1)
    for index, category in enumerate(LABELS):
        p, y = probabilities[:, index], truth[:, index]
        bins = []
        ece = 0.0
        for low, high in itertools.pairwise(edges):
            mask = (p >= low) & ((p < high) if high < 1.0 else (p <= high))
            if mask.any():
                gap = abs(float(p[mask].mean()) - float(y[mask].mean()))
                ece += gap * mask.mean()
                bins.append(
                    {
                        "low": round(float(low), 2),
                        "high": round(float(high), 2),
                        "count": int(mask.sum()),
                        "mean_probability": round(float(p[mask].mean()), 4),
                        "observed_rate": round(float(y[mask].mean()), 4),
                    }
                )
        result[category.value] = {
            "brier": round(float(np.mean((p - y) ** 2)), 4),
            "expected_calibration_error": round(ece, 4),
            "bins": bins,
        }
    return result


def classifier_outputs(
    model: FaultClassifier, features: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    probabilities = positive_probabilities(model.pipeline, features)
    thresholds = np.asarray([model.thresholds[c] for c in model.labels])
    predicted = probabilities >= thresholds
    abstained = np.array([model.out_of_range_fraction(row) > MAX_OUT_OF_RANGE for row in features])
    return probabilities, predicted, abstained


def confirm_consecutive(dataset: Dataset, predicted_all: np.ndarray, windows: int) -> np.ndarray:
    """Apply the runtime rule: a model finding is shown only after ``windows`` consecutive
    positive analyses of the same category within one session (in time order)."""
    confirmed = np.zeros_like(predicted_all, dtype=bool)
    for rows in iter_split_sessions(dataset, "test"):
        run = np.zeros(predicted_all.shape[1], dtype=int)
        for row in rows:
            run = np.where(predicted_all[row], run + 1, 0)
            confirmed[row] = run >= windows
    return confirmed


def recall_by_pattern(
    dataset: Dataset, mask: np.ndarray, predicted: np.ndarray
) -> dict[str, dict[str, dict[str, float | int]]]:
    """Recall of each category per driving pattern, with the number of sessions behind it."""
    pattern_of = {int(str(s["session_id"])): str(s["pattern"]) for s in dataset.sessions}
    sessions = dataset.session_ids[mask]
    patterns = np.array([pattern_of[int(sid)] for sid in sessions])
    truth = dataset.labels[mask].astype(bool)
    result: dict[str, dict[str, dict[str, float | int]]] = {}
    for index, category in enumerate(LABELS):
        per_pattern: dict[str, dict[str, float | int]] = {}
        for pattern in sorted(set(patterns.tolist())):
            positives = truth[:, index] & (patterns == pattern)
            if not positives.any():
                continue
            per_pattern[pattern] = {
                "windows": int(positives.sum()),
                "sessions": int(np.unique(sessions[positives]).size),
                "recall": round(float(predicted[positives, index].mean()), 3),
            }
        result[category.value] = per_pattern
    return result


def evaluate_classifier(
    model: FaultClassifier, dataset: Dataset, *, confirmation_windows: int = 2
) -> dict[str, Any]:
    mask = dataset.mask("test")
    features, truth = dataset.features[mask], dataset.labels[mask]
    probabilities, predicted, abstained = classifier_outputs(model, features)
    answered = ~abstained
    gated = predicted & answered[:, None]
    completeness, noise = dataset.completeness[mask], dataset.noise_scale[mask]
    subsets = {
        "missing_telemetry (completeness < 0.97)": completeness < MISSING_COMPLETENESS,
        "complete_telemetry": completeness >= MISSING_COMPLETENESS,
        "noisy (noise scale >= 1.5)": noise >= NOISY_SCALE,
        "low_noise (noise scale < 1.0)": noise < 1.0,
    }
    predicted_all = np.zeros_like(dataset.labels, dtype=bool)
    predicted_all[mask] = predicted
    confirmed = confirm_consecutive(dataset, predicted_all, confirmation_windows)[mask]
    return {
        "split": "test",
        "sessions": int(np.unique(dataset.session_ids[mask]).size),
        "confirmation_windows": confirmation_windows,
        "runtime_confirmed": multilabel_metrics(truth, confirmed),
        "abstention_rate": round(float(abstained.mean()), 4),
        "all_rows_model_output": multilabel_metrics(truth, predicted),
        "with_abstention_as_no_finding": multilabel_metrics(truth, gated),
        "answered_rows_only": multilabel_metrics(truth[answered], predicted[answered]),
        "calibration": calibration(truth, probabilities),
        "robustness": {
            name: multilabel_metrics(truth[subset], predicted[subset])
            for name, subset in subsets.items()
            if subset.sum() >= 20
        },
        "recall_by_pattern": recall_by_pattern(dataset, mask, predicted),
        "rule_baseline": multilabel_metrics(truth, dataset.rule_labels[mask].astype(bool)),
        "hybrid_union": multilabel_metrics(
            truth, predicted | dataset.rule_labels[mask].astype(bool)
        ),
    }


def evaluate_anomaly(
    detector: AnomalyDetector,
    dataset: Dataset,
    *,
    sensitivity: str = "standard",
    persistence: int = 3,
) -> dict[str, Any]:
    mask = dataset.mask("test")
    scores = detector.scores(dataset.features[mask])
    truth = dataset.labels[mask]
    abnormal = truth.any(axis=1)
    threshold = detector.thresholds[sensitivity]
    flagged = scores >= threshold
    per_category = {
        c.value: round(float(flagged[truth[:, i] == 1].mean()), 4) if truth[:, i].any() else None
        for i, c in enumerate(LABELS)
    }
    healthy_sessions = alarmed_healthy = fault_sessions = detected_fault = 0
    for rows in iter_split_sessions(dataset, "test"):
        session_scores = detector.scores(dataset.features[rows]) >= threshold
        run, persistent_hits, persistent_after_fault = 0, 0, False
        for flag, labels in zip(session_scores, dataset.labels[rows], strict=True):
            run = run + 1 if flag else 0
            if run >= persistence:
                persistent_hits += 1
                persistent_after_fault |= bool(labels.any())
        if dataset.labels[rows].any():
            fault_sessions += 1
            detected_fault += int(persistent_after_fault)
        else:
            healthy_sessions += 1
            alarmed_healthy += int(persistent_hits > 0)
    return {
        "sensitivity": sensitivity,
        "threshold": round(threshold, 5),
        "roc_auc_normal_vs_abnormal": round(float(roc_auc_score(abnormal, scores)), 4),
        "window_level": binary_metrics(abnormal, flagged),
        "detection_rate_by_category": per_category,
        "session_level": {
            "persistence_windows": persistence,
            "healthy_sessions": healthy_sessions,
            "healthy_sessions_with_persistent_alarm": alarmed_healthy,
            "fault_sessions": fault_sessions,
            "fault_sessions_detected_after_onset": detected_fault,
        },
    }


# -- catalogue scenarios through the complete hybrid engine ---------------------------------------

CATALOGUE_SEEDS: Final = (9101, 9102, 9103, 9104, 9105)
CATALOGUE_DURATION_S: Final = 600
CATALOGUE_ANALYSIS_EVERY_S: Final = 2


def evaluate_catalogue(
    models: Any,
    *,
    seeds: tuple[int, ...] = CATALOGUE_SEEDS,
    duration_s: int = CATALOGUE_DURATION_S,
) -> dict[str, Any]:
    """Run the full hybrid engine, as the application does, over every built-in scenario.

    These drives use the catalogue scenario definitions and seeds that appear nowhere in the
    training data. For healthy scenarios every warning or critical finding is a false alarm.
    For fault scenarios the first time a finding of the right category appears is recorded.
    """
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    results: dict[str, Any] = {}
    for scenario_id, definition in SCENARIOS.items():
        expected = sorted({FAULT_CATEGORY[f.kind].value for f in definition.faults})
        per_seed: list[dict[str, Any]] = []
        for seed in seeds:
            engine = DiagnosticEngine(models, DiagnosticSettings())
            simulator = VehicleSimulator(SimulationConfig(scenario=scenario_id, seed=seed))
            samples: list[Any] = []
            analyses = alarms = 0
            sources: dict[str, int] = {}
            first: dict[str, float] = {}
            for step in simulator.iter_steps(duration_s, 1.0):
                now = step.elapsed_s
                if step.readings is not None:
                    stamp = origin + timedelta(seconds=now)
                    samples.append((now, build_sample(stamp, step.readings).sample))
                if round(now) % CATALOGUE_ANALYSIS_EVERY_S:
                    continue
                recent = [s for s in samples if s[0] > now - WINDOW_SECONDS]
                window = TelemetryWindow.from_samples(recent)
                window = TelemetryWindow(
                    now, window.times, window.values, window.sample_count, window.window_s
                )
                assessment = engine.assess(
                    window, data_source=DataSource.SIMULATION, timestamp=origin
                )
                analyses += 1
                alerting = [
                    f
                    for f in assessment.findings
                    if f.severity in (Severity.WARNING, Severity.CRITICAL)
                ]
                if alerting:
                    alarms += 1
                for finding in alerting:
                    sources[finding.source.value] = sources.get(finding.source.value, 0) + 1
                    first.setdefault(finding.category.value, now)
            per_seed.append(
                {
                    "seed": seed,
                    "analyses": analyses,
                    "alarm_analyses": alarms,
                    "alarms_by_source": sources,
                    "first_detection_s": first,
                }
            )
        total = sum(r["analyses"] for r in per_seed)
        alarm_total = sum(r["alarm_analyses"] for r in per_seed)
        entry: dict[str, Any] = {
            "healthy": not definition.faults,
            "expected_categories": expected,
            "analyses": total,
            "alarm_rate": round(alarm_total / total, 4) if total else 0.0,
            "runs_with_any_alarm": sum(1 for r in per_seed if r["alarm_analyses"]),
            "runs": len(per_seed),
            "per_seed": per_seed,
        }
        if expected:
            detected = [
                min(r["first_detection_s"][c] for c in expected if c in r["first_detection_s"])
                for r in per_seed
                if any(c in r["first_detection_s"] for c in expected)
            ]
            onset = min(f.onset_s for f in definition.faults)
            entry["runs_detected"] = len(detected)
            entry["median_detection_after_onset_s"] = (
                round(float(np.median(detected)) - onset, 1) if detected else None
            )
        results[scenario_id.value] = entry
    return results
