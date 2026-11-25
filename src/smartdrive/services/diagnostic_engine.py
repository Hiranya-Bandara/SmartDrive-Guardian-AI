"""Hybrid diagnostic engine: rules + Random Forest + Isolation Forest + explanations + health.

Decision policy (documented in docs/ml/README.md):

1. Rule findings are always kept and are never downgraded or removed by a model.
2. A classifier label above its threshold in ``MODEL_CONFIRMATION`` consecutive analyses becomes
   a separate *model* finding. It is WARNING at most, because the model is trained on synthetic
   data and cannot confirm a fault; it is marked *corroborated* when a rule reports the same
   category (agreement is evidence, not proof).
3. An Isolation Forest anomaly becomes a finding only when it persists for N consecutive
   analyses, and is always INFORMATION: it cannot name a cause and, on its own, it is too weak
   evidence to raise alerts (see docs/ml/evaluation_report.md).
4. When the data is stale, no assessment is made. When it is insufficient, the models abstain
   and the status is "insufficient data" unless a rule could still evaluate.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from datetime import datetime
from typing import Any

import numpy as np

from smartdrive.ai.anomaly_detector import AnomalyTracker
from smartdrive.ai.features import extract_features
from smartdrive.ai.model_registry import LoadedModels
from smartdrive.config.constants import DataSource, DiagnosticSource, FaultCategory, Severity
from smartdrive.config.settings import DiagnosticSettings
from smartdrive.core.health_score import compute_health_score
from smartdrive.core.recommendations import recommend
from smartdrive.core.rule_engine import RuleEngine, VehicleContext
from smartdrive.core.sensors import SENSOR_BY_KEY
from smartdrive.core.telemetry_window import DataQuality, TelemetryWindow
from smartdrive.models.diagnostic import (
    AnomalyResult,
    ClassifierResult,
    DiagnosticAssessment,
    DiagnosticStatus,
    Explanation,
    Finding,
    HealthScore,
    LabelState,
    ModelRunStatus,
    max_severity,
)
from smartdrive.models.telemetry import SENSOR_FIELDS

logger = logging.getLogger(__name__)

MODEL_CONFIRMATION = 2

_STATUS_BY_SEVERITY = {
    Severity.CRITICAL: DiagnosticStatus.CRITICAL,
    Severity.WARNING: DiagnosticStatus.WARNING,
    Severity.INFORMATION: DiagnosticStatus.INFORMATION,
}


def _category_label(category: FaultCategory) -> str:
    return category.value.replace("_", " ")


class DiagnosticEngine:
    """One engine per telemetry stream; owned by a single worker thread."""

    def __init__(
        self,
        models: LoadedModels | None,
        settings: DiagnosticSettings,
        vehicle: VehicleContext | None = None,
    ) -> None:
        self.models = models
        self.settings = settings
        self.rules = RuleEngine(settings.thresholds, vehicle)
        self.anomaly = AnomalyTracker(
            models.anomaly if models else None,
            settings.anomaly_sensitivity,
            settings.anomaly_persistence_windows,
        )
        self._model_streak: dict[FaultCategory, int] = {}
        self._block: tuple[ModelRunStatus, str] | None = None

    def reset(self) -> None:
        self.rules.reset()
        self.anomaly.reset()
        self._model_streak.clear()

    def configure(self, settings: DiagnosticSettings, vehicle: VehicleContext | None) -> None:
        self.settings = settings
        self.rules.thresholds = settings.thresholds
        if vehicle is not None and vehicle != self.rules.vehicle:
            self.rules.vehicle = vehicle
            self.reset()
        self.anomaly.sensitivity = settings.anomaly_sensitivity
        self.anomaly.persistence = settings.anomaly_persistence_windows

    # -- assessment ---------------------------------------------------------------------------

    def assess(
        self,
        window: TelemetryWindow,
        *,
        data_source: DataSource,
        timestamp: datetime,
        data_age_s: float | None = None,
        stale_after_s: float = 5.0,
        vehicle_id: int | None = None,
        session_id: int | None = None,
        recent_alerts: int = 0,
        ml_block_reason: str | None = None,
        unavailable_sensors: frozenset[str] = frozenset(),
    ) -> DiagnosticAssessment:
        """Assess one window.

        ``ml_block_reason`` turns the models off for this stream (for example live vehicle data
        when experimental live inference is disabled). ``unavailable_sensors`` lists sensors the
        data source cannot provide at all; the models were trained with every monitored sensor,
        so they report ``INCOMPATIBLE`` instead of predicting from a different input
        distribution. Rules always run on whatever sensors are present.
        """
        started = time.perf_counter()
        self._block = _model_block(ml_block_reason, unavailable_sensors)
        quality = window.quality()
        common: dict[str, Any] = {
            "timestamp": timestamp,
            "elapsed_s": window.end_elapsed_s,
            "data_source": data_source,
            "vehicle_id": vehicle_id,
            "session_id": session_id,
        }

        if data_age_s is not None and data_age_s > stale_after_s:
            self.anomaly.reset()
            reason = f"No new telemetry for {data_age_s:.0f} s."
            return DiagnosticAssessment(
                **common,
                status=DiagnosticStatus.STALE,
                severity=Severity.UNKNOWN,
                findings=(),
                quality=quality,
                classifier=ClassifierResult(ModelRunStatus.ABSTAINED, reason),
                anomaly=AnomalyResult(ModelRunStatus.ABSTAINED, reason),
                health=HealthScore(None, "Unavailable", (), f"Stale data: {reason}"),
                recommendations=tuple(recommend(DiagnosticStatus.STALE, [])),
                inference_ms=(time.perf_counter() - started) * 1000,
            )

        rule_findings = self.rules.evaluate(window)
        features = extract_features(window)
        classifier = self._classify(features, quality)
        anomaly = self._anomaly(features, quality)
        findings = self._merge(rule_findings, classifier, anomaly)

        severity = max_severity([f.severity for f in findings])
        if findings:
            status = _STATUS_BY_SEVERITY.get(severity, DiagnosticStatus.NO_ABNORMALITY)
        elif not quality.sufficient:
            status = DiagnosticStatus.INSUFFICIENT_DATA
            severity = Severity.UNKNOWN
        else:
            status = DiagnosticStatus.NO_ABNORMALITY
        explanations = self._explain(features, classifier)
        health = compute_health_score(
            findings, classifier, anomaly, quality, recent_alerts=recent_alerts
        )
        return DiagnosticAssessment(
            **common,
            status=status,
            severity=severity,
            findings=tuple(findings),
            quality=quality,
            classifier=classifier,
            anomaly=anomaly,
            health=health,
            recommendations=tuple(recommend(status, findings)),
            explanations=explanations,
            inference_ms=(time.perf_counter() - started) * 1000,
        )

    def _classify(self, features: np.ndarray, quality: DataQuality) -> ClassifierResult:
        if not self.settings.machine_learning_enabled:
            return ClassifierResult(ModelRunStatus.DISABLED, "Machine learning is turned off.")
        if self._block is not None:
            return ClassifierResult(self._block[0], self._block[1])
        model = self.models.classifier if self.models else None
        if model is None:
            return ClassifierResult(
                ModelRunStatus.UNAVAILABLE, "Classifier model is not available."
            )
        try:
            return model.predict(features, quality)
        except Exception as exc:
            logger.exception("Classifier inference failed")
            return ClassifierResult(
                ModelRunStatus.FAILED, f"Inference failed: {exc}", model_version=model.version
            )

    def _anomaly(self, features: np.ndarray, quality: DataQuality) -> AnomalyResult:
        if not self.settings.machine_learning_enabled:
            return AnomalyResult(ModelRunStatus.DISABLED, "Machine learning is turned off.")
        if self._block is not None:
            self.anomaly.reset()
            return AnomalyResult(self._block[0], self._block[1])
        try:
            return self.anomaly.evaluate(features, quality)
        except Exception as exc:
            logger.exception("Anomaly inference failed")
            return AnomalyResult(ModelRunStatus.FAILED, f"Inference failed: {exc}")

    def _confirmed_positives(self, classifier: ClassifierResult) -> dict[FaultCategory, Any]:
        current = {p.category: p for p in classifier.positives()}
        if classifier.status is not ModelRunStatus.OK:
            self._model_streak.clear()
            return {}
        for category in list(self._model_streak):
            if category not in current:
                del self._model_streak[category]
        for category in current:
            self._model_streak[category] = self._model_streak.get(category, 0) + 1
        return {c: p for c, p in current.items() if self._model_streak[c] >= MODEL_CONFIRMATION}

    def _merge(
        self, rules: list[Finding], classifier: ClassifierResult, anomaly: AnomalyResult
    ) -> list[Finding]:
        positives = self._confirmed_positives(classifier)
        rule_categories = {f.category for f in rules}
        merged: list[Finding] = [
            dataclasses.replace(f, corroborated_by=(DiagnosticSource.CLASSIFIER,))
            if f.category in positives
            else f
            for f in rules
        ]
        for category, label in positives.items():
            corroborated = category in rule_categories
            merged.append(
                Finding(
                    key=f"model:{category.value}",
                    source=DiagnosticSource.CLASSIFIER,
                    category=category,
                    severity=Severity.WARNING,
                    title=f"Model: {_category_label(category)} abnormality pattern",
                    explanation=(
                        f"The Random Forest assigned probability {label.probability:.2f} "
                        f"(decision threshold {label.threshold:.2f}) to a "
                        f"{_category_label(category)} abnormality. "
                        + (
                            "A rule finding agrees."
                            if corroborated
                            else "No rule finding confirms it; treat it as an early indication."
                        )
                    ),
                    evidence={
                        "probability": round(label.probability, 3),
                        "threshold": label.threshold,
                    },
                    probability=label.probability,
                    model_version=classifier.model_version,
                    corroborated_by=(DiagnosticSource.RULE,) if corroborated else (),
                )
            )
        if anomaly.status is ModelRunStatus.OK and anomaly.persistent and anomaly.score is not None:
            merged.append(
                Finding(
                    key="anomaly:telemetry_pattern",
                    source=DiagnosticSource.ANOMALY_DETECTOR,
                    category=FaultCategory.UNKNOWN_ANOMALY,
                    severity=Severity.INFORMATION,
                    title="Unusual telemetry pattern",
                    explanation=(
                        f"The anomaly score has exceeded the {self.settings.anomaly_sensitivity} "
                        f"threshold for {anomaly.consecutive} consecutive analyses. "
                        "The score measures how different the data is from normal "
                        "simulated driving; it is not a probability of failure."
                    ),
                    evidence={
                        "anomaly_score": round(anomaly.score, 4),
                        "threshold": round(anomaly.threshold or 0.0, 4),
                        "consecutive_windows": anomaly.consecutive,
                    },
                    model_version=anomaly.model_version,
                )
            )
        return merged

    def _explain(
        self, features: np.ndarray, classifier: ClassifierResult
    ) -> dict[FaultCategory, Explanation]:
        model = self.models.classifier if self.models else None
        if model is None or classifier.status is not ModelRunStatus.OK or not classifier.labels:
            return {}
        wanted = [p.category for p in classifier.labels if p.state is not LabelState.NEGATIVE]
        top = max(classifier.labels, key=lambda p: p.probability).category
        if top not in wanted:
            wanted.append(top)
        try:
            return {category: model.explain(features, category) for category in wanted}
        except Exception:
            logger.exception("Explanation failed")
            return {}


def _model_block(
    reason: str | None, unavailable_sensors: frozenset[str]
) -> tuple[ModelRunStatus, str] | None:
    if reason:
        return ModelRunStatus.DISABLED, reason
    missing = [name for name in SENSOR_FIELDS if name in unavailable_sensors]
    if missing:
        labels = ", ".join(SENSOR_BY_KEY[name].label.lower() for name in missing)
        return (
            ModelRunStatus.INCOMPATIBLE,
            "The models were trained with every monitored sensor, but this data source cannot "
            f"provide: {labels}. They are not run, rather than predicting from incomplete input.",
        )
    return None
