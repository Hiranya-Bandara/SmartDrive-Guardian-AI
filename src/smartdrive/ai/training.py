"""Reproducible training for the fault classifier and the anomaly detector.

Model selection and threshold tuning use only the validation split; the test split is touched
only by :mod:`smartdrive.ai.evaluation`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Final

import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.metrics import f1_score, precision_score
from sklearn.pipeline import Pipeline

from smartdrive.ai import anomaly_detector, classifier
from smartdrive.ai.dataset import LABELS, Dataset
from smartdrive.ai.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION

THRESHOLD_GRID: Final = tuple(round(x, 2) for x in np.arange(0.2, 0.81, 0.05))
ANOMALY_PERCENTILES: Final = {"low": 99.5, "standard": 98.0, "high": 95.0}
MIN_VALIDATION_PRECISION: Final = 0.9


@dataclass(frozen=True)
class TrainingConfig:
    seed: int = 42
    n_estimators: int = 150
    grid: tuple[dict[str, Any], ...] = (
        {"max_depth": 12, "min_samples_leaf": 2},
        {"max_depth": 18, "min_samples_leaf": 2},
        {"max_depth": 18, "min_samples_leaf": 5},
        {"max_depth": None, "min_samples_leaf": 5},
    )
    anomaly_estimators: int = 200
    importance_repeats: int = 3
    n_jobs: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "grid": [dict(g) for g in self.grid]}


@dataclass
class ClassifierTraining:
    artifact: dict[str, Any]
    selection: list[dict[str, Any]] = field(default_factory=list)
    chosen: dict[str, Any] = field(default_factory=dict)


def make_classifier_pipeline(params: dict[str, Any], config: TrainingConfig) -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            (
                "forest",
                RandomForestClassifier(
                    n_estimators=config.n_estimators,
                    class_weight="balanced_subsample",
                    max_features="sqrt",
                    random_state=config.seed,
                    n_jobs=config.n_jobs,
                    **params,
                ),
            ),
        ]
    )


def positive_probabilities(pipeline: Pipeline, features: np.ndarray) -> np.ndarray:
    raw = pipeline.predict_proba(features)
    outputs = raw if isinstance(raw, list) else [raw]
    classes = pipeline[-1].classes_
    columns = []
    for index, proba in enumerate(outputs):
        label_classes = np.asarray(classes[index] if isinstance(classes, list) else classes)
        positive = np.flatnonzero(label_classes == 1)
        columns.append(proba[:, positive[0]] if positive.size else np.zeros(len(features)))
    return np.column_stack(columns)


def tune_thresholds(
    probabilities: np.ndarray, labels: np.ndarray, min_precision: float = MIN_VALIDATION_PRECISION
) -> list[float]:
    """Per-label decision threshold chosen on validation data.

    Policy: the highest-F1 threshold among those reaching ``min_precision``; if none does, the
    highest-F1 threshold overall. Requiring precision limits false warnings during normal
    driving at some cost in recall. Ties go to the higher threshold.
    """
    chosen = []
    for index in range(labels.shape[1]):
        truth = labels[:, index]
        best_precise: tuple[float, float] | None = None
        best_any = (-1.0, 0.5)
        for threshold in THRESHOLD_GRID:
            predicted = probabilities[:, index] >= threshold
            score = f1_score(truth, predicted, zero_division=0)
            precision = precision_score(truth, predicted, zero_division=0)
            if score >= best_any[0]:
                best_any = (score, threshold)
            if precision >= min_precision and (best_precise is None or score >= best_precise[0]):
                best_precise = (score, threshold)
        chosen.append((best_precise or best_any)[1])
    return chosen


def train_classifier(dataset: Dataset, config: TrainingConfig) -> ClassifierTraining:
    x_train, y_train = dataset.subset("train")
    x_val, y_val = dataset.subset("validation")
    selection: list[dict[str, Any]] = []
    best: tuple[float, Pipeline | None, dict[str, Any], list[float]] = (-1.0, None, {}, [])
    for params in config.grid:
        pipeline = make_classifier_pipeline(params, config).fit(x_train, y_train)
        probabilities = positive_probabilities(pipeline, x_val)
        thresholds = tune_thresholds(probabilities, y_val)
        predictions = probabilities >= np.asarray(thresholds)
        macro = float(f1_score(y_val, predictions, average="macro", zero_division=0))
        selection.append(
            {
                "params": {k: v for k, v in params.items()},
                "validation_macro_f1": round(macro, 4),
                "thresholds": thresholds,
            }
        )
        if macro > best[0]:
            best = (macro, pipeline, params, thresholds)
    _, pipeline, params, thresholds = best
    if pipeline is None:  # pragma: no cover - grid is never empty
        raise RuntimeError("No classifier was trained.")

    importance = permutation_importance(
        pipeline,
        x_val,
        y_val,
        scoring="f1_macro",
        n_repeats=config.importance_repeats,
        random_state=config.seed,
        n_jobs=1,
    )
    forest = pipeline[-1]
    ranked = np.argsort(importance.importances_mean)[::-1]
    artifact = {
        "artifact_type": classifier.ARTIFACT_TYPE,
        "format_version": 1,
        "pipeline": pipeline,
        "feature_names": list(FEATURE_NAMES),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "labels": [c.value for c in LABELS],
        "thresholds": {c.value: t for c, t in zip(LABELS, thresholds, strict=True)},
        "range_low": np.nanpercentile(x_train, 0.5, axis=0),
        "range_high": np.nanpercentile(x_train, 99.5, axis=0),
        "global_importance": [
            {
                "feature": FEATURE_NAMES[i],
                "permutation_mean": float(importance.importances_mean[i]),
                "permutation_std": float(importance.importances_std[i]),
                "impurity": float(forest.feature_importances_[i]),
            }
            for i in ranked
        ],
    }
    return ClassifierTraining(artifact, selection, {"params": params, "thresholds": thresholds})


def train_anomaly_detector(dataset: Dataset, config: TrainingConfig) -> dict[str, Any]:
    indices = anomaly_detector.anomaly_feature_indices()
    train_mask = dataset.mask("train") & (dataset.labels.sum(axis=1) == 0)
    val_mask = dataset.mask("validation") & (dataset.labels.sum(axis=1) == 0)
    pipeline = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            (
                "forest",
                IsolationForest(
                    n_estimators=config.anomaly_estimators,
                    contamination="auto",
                    random_state=config.seed,
                    n_jobs=config.n_jobs,
                ),
            ),
        ]
    ).fit(dataset.features[train_mask][:, indices])
    validation_scores = -pipeline.score_samples(dataset.features[val_mask][:, indices])
    thresholds = {
        name: float(np.percentile(validation_scores, pct))
        for name, pct in ANOMALY_PERCENTILES.items()
    }
    return {
        "artifact_type": anomaly_detector.ARTIFACT_TYPE,
        "format_version": 1,
        "pipeline": pipeline,
        "feature_names": list(FEATURE_NAMES),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_indices": indices,
        "thresholds": thresholds,
        "threshold_percentiles": ANOMALY_PERCENTILES,
        "baseline_rows": int(train_mask.sum()),
    }
