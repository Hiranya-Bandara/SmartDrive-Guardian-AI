"""Experimental vehicle condition indicator (0–100).

The score starts at 100 and subtracts documented penalties for current findings, model output
and recent alerts. It is a summary of the evidence SmartDrive has, not a safety rating: a high
score never means the vehicle is safe to drive. When data is insufficient the score is
unavailable rather than guessed.
"""

from __future__ import annotations

from typing import Final

from smartdrive.config.constants import DiagnosticSource, Severity
from smartdrive.core.telemetry_window import DataQuality
from smartdrive.models.diagnostic import (
    AnomalyResult,
    ClassifierResult,
    Finding,
    HealthComponent,
    HealthScore,
    ModelRunStatus,
)

RULE_PENALTY: Final = {Severity.CRITICAL: 35.0, Severity.WARNING: 15.0, Severity.INFORMATION: 3.0}
MODEL_PENALTY_MAX: Final = 20.0
ANOMALY_PERSISTENT_PENALTY: Final = 10.0
ANOMALY_SINGLE_PENALTY: Final = 4.0
ALERT_PENALTY: Final = 2.0
ALERT_PENALTY_CAP: Final = 10.0
EXPERIMENTAL_NOTE: Final = (
    "Experimental indicator derived from simulated-data models and rules. It is not a safety "
    "rating; a high score does not mean the vehicle is safe to drive."
)


def band_for(score: int) -> str:
    if score >= 85:
        return "Good"
    if score >= 60:
        return "Fair"
    if score >= 30:
        return "Poor"
    return "Severe"


def compute_health_score(
    findings: list[Finding],
    classifier: ClassifierResult,
    anomaly: AnomalyResult,
    quality: DataQuality,
    *,
    recent_alerts: int = 0,
) -> HealthScore:
    if not quality.sufficient:
        return HealthScore(None, "Unavailable", (), f"Insufficient data: {quality.reason}")

    components: list[HealthComponent] = []
    rule_categories = set()
    for finding in findings:
        if finding.source is not DiagnosticSource.RULE:
            continue
        rule_categories.add(finding.category)
        penalty = RULE_PENALTY.get(finding.severity, 0.0)
        if penalty:
            components.append(
                HealthComponent(
                    f"Rule: {finding.title}",
                    penalty,
                    f"{finding.severity.value.title()} rule finding reduces the score "
                    f"by {penalty:.0f}.",
                )
            )

    if classifier.status is ModelRunStatus.OK:
        for label in classifier.positives():
            if label.category in rule_categories:
                continue
            penalty = round(MODEL_PENALTY_MAX * label.probability, 1)
            components.append(
                HealthComponent(
                    f"Model: {label.category.value.replace('_', ' ')} pattern",
                    penalty,
                    f"The classifier assigned probability {label.probability:.2f} (threshold "
                    f"{label.threshold:.2f}) without a matching rule finding.",
                )
            )

    if anomaly.status is ModelRunStatus.OK and anomaly.is_anomalous:
        penalty = ANOMALY_PERSISTENT_PENALTY if anomaly.persistent else ANOMALY_SINGLE_PENALTY
        components.append(
            HealthComponent(
                "Unusual telemetry pattern",
                penalty,
                "Persistent anomaly across consecutive analyses."
                if anomaly.persistent
                else "A single analysis window looked unusual.",
            )
        )

    if recent_alerts:
        penalty = min(ALERT_PENALTY_CAP, ALERT_PENALTY * recent_alerts)
        components.append(
            HealthComponent(
                "Recent alerts",
                penalty,
                f"{recent_alerts} warning or critical alert(s) recently.",
            )
        )

    score = max(0, min(100, round(100 - sum(c.penalty for c in components))))
    return HealthScore(score, band_for(score), tuple(components), EXPERIMENTAL_NOTE)
