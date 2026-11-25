"""Isolation Forest anomaly detection over telemetry features.

The detector is trained only on windows from healthy simulated sessions. Its score measures how
unusual a window is relative to that baseline; it is not a probability of failure.

It uses a compact set of physically meaningful features plus operating context (speed, load,
engine speed), so "unusual" is judged relative to how the vehicle is being driven. Using all 96
classifier features diluted the signal (ROC AUC ≈ 0.5 in a pilot run) because Isolation Forest
splits on randomly chosen features. Data-quality features are excluded: gaps in data are handled
by the quality checks, not reported as vehicle anomalies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

import numpy as np
from sklearn.pipeline import Pipeline

from smartdrive.ai.features import FEATURE_NAMES
from smartdrive.core.telemetry_window import DataQuality
from smartdrive.models.diagnostic import AnomalyResult, ModelRunStatus

ARTIFACT_TYPE: Final = "smartdrive.anomaly_detector"
Sensitivity = Literal["low", "standard", "high"]
ANOMALY_FEATURES: Final = (
    "coolant_temp_c__recent_mean",
    "coolant_temp_c__slope_per_min",
    "coolant_temp_c__min",
    "coolant_max_jump",
    "coolant_minus_oil",
    "oil_temp_c__recent_mean",
    "oil_pressure_kpa__recent_mean",
    "oil_pressure_per_krpm",
    "control_module_voltage_v__recent_mean",
    "voltage_while_running",
    "fuel_rate_per_load",
    "rpm_jitter",
    "intake_air_temp_c__recent_mean",
    "speed_kph__recent_mean",
    "engine_load_pct__recent_mean",
    "rpm__recent_mean",
)


def anomaly_feature_indices() -> list[int]:
    return [FEATURE_NAMES.index(name) for name in ANOMALY_FEATURES]


@dataclass(frozen=True)
class AnomalyDetector:
    pipeline: Pipeline
    feature_indices: tuple[int, ...]
    thresholds: dict[str, float]
    version: str

    @classmethod
    def from_artifact(cls, artifact: dict[str, Any], version: str) -> AnomalyDetector:
        return cls(
            pipeline=artifact["pipeline"],
            feature_indices=tuple(int(i) for i in artifact["feature_indices"]),
            thresholds={k: float(v) for k, v in artifact["thresholds"].items()},
            version=version,
        )

    def score(self, features: np.ndarray) -> float:
        """Higher is more unusual (negated Isolation Forest ``score_samples``)."""
        selected = features[list(self.feature_indices)].reshape(1, -1)
        return float(-self.pipeline.score_samples(selected)[0])

    def scores(self, matrix: np.ndarray) -> np.ndarray:
        result: np.ndarray = -self.pipeline.score_samples(matrix[:, list(self.feature_indices)])
        return result


@dataclass
class AnomalyTracker:
    """Turns per-window scores into persistent anomalies (N consecutive anomalous windows)."""

    detector: AnomalyDetector | None
    sensitivity: Sensitivity = "standard"
    persistence: int = 3
    _consecutive: int = field(default=0, init=False)

    def reset(self) -> None:
        self._consecutive = 0

    def evaluate(self, features: np.ndarray, quality: DataQuality) -> AnomalyResult:
        if self.detector is None:
            return AnomalyResult(ModelRunStatus.UNAVAILABLE, "Anomaly model is not available.")
        if features.shape != (len(FEATURE_NAMES),):
            return AnomalyResult(
                ModelRunStatus.INCOMPATIBLE,
                "Feature vector does not match the trained schema.",
                model_version=self.detector.version,
            )
        if not quality.sufficient:
            self._consecutive = 0
            return AnomalyResult(
                ModelRunStatus.ABSTAINED, quality.reason, model_version=self.detector.version
            )
        score = self.detector.score(features)
        threshold = self.detector.thresholds[self.sensitivity]
        anomalous = score >= threshold
        self._consecutive = self._consecutive + 1 if anomalous else 0
        return AnomalyResult(
            ModelRunStatus.OK,
            "",
            score,
            threshold,
            anomalous,
            self._consecutive,
            self._consecutive >= self.persistence,
            self.detector.version,
        )
