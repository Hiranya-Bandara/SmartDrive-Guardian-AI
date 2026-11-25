"""Runtime wrapper around the trained multi-label Random Forest.

The wrapper never invents output: probabilities come from ``predict_proba`` of the trained
pipeline, and the model abstains when its input is incomplete, out of distribution or
incompatible with the trained feature schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from sklearn.pipeline import Pipeline

from smartdrive.ai.explainability import decompose
from smartdrive.ai.features import FEATURE_NAMES
from smartdrive.config.constants import FaultCategory
from smartdrive.core.telemetry_window import DataQuality
from smartdrive.models.diagnostic import (
    ClassifierResult,
    Explanation,
    FeatureContribution,
    LabelPrediction,
    LabelState,
    ModelRunStatus,
)

ARTIFACT_TYPE: Final = "smartdrive.fault_classifier"
UNCERTAIN_FRACTION: Final = 0.6
MAX_OUT_OF_RANGE: Final = 0.25
REQUIRED_SENSORS: Final[dict[FaultCategory, str]] = {
    FaultCategory.LUBRICATION: "oil_pressure_kpa",
}


@dataclass(frozen=True)
class FaultClassifier:
    pipeline: Pipeline
    labels: tuple[FaultCategory, ...]
    thresholds: dict[FaultCategory, float]
    range_low: np.ndarray
    range_high: np.ndarray
    version: str
    feature_names: tuple[str, ...] = FEATURE_NAMES

    @classmethod
    def from_artifact(cls, artifact: dict[str, Any], version: str) -> FaultClassifier:
        labels = tuple(FaultCategory(v) for v in artifact["labels"])
        return cls(
            pipeline=artifact["pipeline"],
            labels=labels,
            thresholds={FaultCategory(k): float(v) for k, v in artifact["thresholds"].items()},
            range_low=np.asarray(artifact["range_low"], dtype=float),
            range_high=np.asarray(artifact["range_high"], dtype=float),
            version=version,
            feature_names=tuple(artifact["feature_names"]),
        )

    def out_of_range_fraction(self, features: np.ndarray) -> float:
        present = ~np.isnan(features)
        if not present.any():
            return 1.0
        span = self.range_high - self.range_low
        margin = 0.1 * np.where(span > 0, span, 1.0)
        outside = (features < self.range_low - margin) | (features > self.range_high + margin)
        return float(np.count_nonzero(outside & present) / np.count_nonzero(present))

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        raw = self.pipeline.predict_proba(features.reshape(1, -1))
        per_label = raw if isinstance(raw, list) else [raw]
        result = []
        for index, proba in enumerate(per_label):
            classes = self.pipeline[-1].classes_
            label_classes = classes[index] if isinstance(classes, list) else classes
            positive = np.flatnonzero(np.asarray(label_classes) == 1)
            result.append(float(proba[0, positive[0]]) if positive.size else 0.0)
        return np.asarray(result)

    def predict(self, features: np.ndarray, quality: DataQuality) -> ClassifierResult:
        if features.shape != (len(self.feature_names),):
            return ClassifierResult(
                ModelRunStatus.INCOMPATIBLE,
                "Feature vector does not match the trained schema.",
                model_version=self.version,
            )
        if not quality.sufficient:
            return ClassifierResult(
                ModelRunStatus.ABSTAINED, quality.reason, model_version=self.version
            )
        outside = self.out_of_range_fraction(features)
        if outside > MAX_OUT_OF_RANGE:
            return ClassifierResult(
                ModelRunStatus.ABSTAINED,
                f"{outside:.0%} of inputs are outside the range seen in training data.",
                model_version=self.version,
                out_of_range_fraction=outside,
            )
        probabilities = self.probabilities(features)
        predictions = []
        for category, probability in zip(self.labels, probabilities, strict=True):
            required = REQUIRED_SENSORS.get(category)
            if required and quality.completeness.get(required, 0.0) == 0.0:
                # The vehicle does not report the signal this category depends on, so the model
                # cannot assess it; omitting the label shows "not assessed", never "negative".
                continue
            threshold = self.thresholds[category]
            if probability >= threshold:
                state = LabelState.POSITIVE
            elif probability >= threshold * UNCERTAIN_FRACTION:
                state = LabelState.UNCERTAIN
            else:
                state = LabelState.NEGATIVE
            predictions.append(LabelPrediction(category, float(probability), threshold, state))
        return ClassifierResult(ModelRunStatus.OK, "", tuple(predictions), self.version, outside)

    def explain(self, features: np.ndarray, category: FaultCategory) -> Explanation:
        index = self.labels.index(category)
        base, contributions, probability = decompose(self.pipeline, features, index)
        items = tuple(
            FeatureContribution(name, float(features[i]), float(contributions[i]))
            for i, name in enumerate(self.feature_names)
            if contributions[i] != 0.0
        )
        return Explanation(category, probability, base, items)
