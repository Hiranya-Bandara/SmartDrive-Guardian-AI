"""Cautious, evidence-based guidance. Never a repair procedure and never a safety guarantee."""

from __future__ import annotations

from typing import Final

from smartdrive.config.constants import DiagnosticSource, FaultCategory, Severity
from smartdrive.models.diagnostic import DiagnosticStatus, Finding

MECHANIC: Final = "Have the vehicle inspected by a qualified mechanic."

_CATEGORY_ADVICE: Final[dict[FaultCategory, dict[Severity, str]]] = {
    FaultCategory.COOLING: {
        Severity.CRITICAL: (
            "Engine temperature is critically high. When it is safe to do so, stop and switch "
            "off the engine and let it cool. Do not open the cooling system while it is hot. "
            + MECHANIC
        ),
        Severity.WARNING: (
            "Engine temperature is above the configured range. Reduce engine load and watch "
            "the vehicle's own temperature gauge. " + MECHANIC
        ),
    },
    FaultCategory.LUBRICATION: {
        Severity.CRITICAL: (
            "Oil pressure is critically low. Continuing to drive could cause serious engine "
            "damage. When it is safe to do so, stop and switch off the engine. " + MECHANIC
        ),
        Severity.WARNING: (
            "Oil pressure is lower than expected. Check whether the vehicle's oil warning lamp "
            "is lit and avoid high engine speeds. " + MECHANIC
        ),
    },
    FaultCategory.ELECTRICAL: {
        Severity.CRITICAL: (
            "The charging voltage is critically low; the battery may be discharging and the "
            "vehicle could stop running. Avoid unnecessary electrical loads. " + MECHANIC
        ),
        Severity.WARNING: ("The charging voltage is outside the expected range. " + MECHANIC),
    },
    FaultCategory.FUEL: {
        Severity.WARNING: (
            "Engine speed or fuel use is behaving unusually. If you notice hesitation, rough "
            "running or a fuel smell, stop driving. " + MECHANIC
        ),
    },
    FaultCategory.SENSOR: {
        Severity.WARNING: (
            "A sensor is reporting implausible values, so related readings and diagnoses may be "
            "unreliable. Rely on the vehicle's own instruments. " + MECHANIC
        ),
    },
}

NO_ABNORMALITY: Final = (
    "No abnormality was detected in the analysed data. This does not confirm that the vehicle "
    "is safe; continue to follow the manufacturer's maintenance schedule and warning lamps."
)
INSUFFICIENT: Final = (
    "Not enough recent telemetry to analyse. Keep monitoring running so at least 20 seconds of "
    "readings are available within the last minute."
)
STALE: Final = "Telemetry has stopped updating, so no current assessment is possible."
MODEL_ONLY: Final = (
    "The machine-learning model found a pattern resembling {category} abnormalities that the "
    "rules did not confirm. Treat this as a prompt to keep watching, not as a diagnosis."
)
ANOMALY: Final = (
    "Telemetry looks unusual compared with normal simulated driving, but no specific cause was "
    "identified. Keep monitoring; if it persists, " + MECHANIC[0].lower() + MECHANIC[1:]
)


def recommend(status: DiagnosticStatus, findings: list[Finding]) -> list[str]:
    if status is DiagnosticStatus.INSUFFICIENT_DATA:
        return [INSUFFICIENT]
    if status is DiagnosticStatus.STALE:
        return [STALE]
    advice: list[str] = []
    for finding in sorted(findings, key=lambda f: f.severity is not Severity.CRITICAL):
        if finding.source is DiagnosticSource.CLASSIFIER and not finding.corroborated_by:
            text = MODEL_ONLY.format(category=finding.category.value.replace("_", " "))
        elif finding.source is DiagnosticSource.ANOMALY_DETECTOR:
            text = ANOMALY
        else:
            by_severity = _CATEGORY_ADVICE.get(finding.category, {})
            text = by_severity.get(finding.severity) or by_severity.get(Severity.WARNING, MECHANIC)
        if text not in advice:
            advice.append(text)
    return advice or [NO_ABNORMALITY]
