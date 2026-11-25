"""Runtime diagnostic result types. Immutable, so they can cross thread boundaries safely."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from smartdrive.config.constants import DataSource, DiagnosticSource, FaultCategory, Severity
from smartdrive.core.telemetry_window import DataQuality

SEVERITY_RANK: dict[Severity, int] = {
    Severity.UNKNOWN: 0,
    Severity.NORMAL: 1,
    Severity.INFORMATION: 2,
    Severity.WARNING: 3,
    Severity.CRITICAL: 4,
}


def max_severity(severities: list[Severity], default: Severity = Severity.NORMAL) -> Severity:
    return max(severities, key=SEVERITY_RANK.__getitem__, default=default)


class DiagnosticStatus(StrEnum):
    INSUFFICIENT_DATA = "insufficient_data"
    STALE = "stale"
    NO_ABNORMALITY = "no_abnormality"
    INFORMATION = "information"
    WARNING = "warning"
    CRITICAL = "critical"


class ModelRunStatus(StrEnum):
    OK = "ok"
    ABSTAINED = "abstained"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    FAILED = "failed"
    DISABLED = "disabled"


class LabelState(StrEnum):
    POSITIVE = "positive"
    UNCERTAIN = "uncertain"
    NEGATIVE = "negative"


@dataclass(frozen=True, slots=True)
class Finding:
    """One diagnostic observation. ``key`` is stable across evaluations (for deduplication)."""

    key: str
    source: DiagnosticSource
    category: FaultCategory
    severity: Severity
    title: str
    explanation: str
    evidence: dict[str, float | str] = field(default_factory=dict)
    probability: float | None = None
    model_version: str | None = None
    corroborated_by: tuple[DiagnosticSource, ...] = ()


@dataclass(frozen=True, slots=True)
class LabelPrediction:
    category: FaultCategory
    probability: float
    threshold: float
    state: LabelState


@dataclass(frozen=True, slots=True)
class ClassifierResult:
    status: ModelRunStatus
    reason: str = ""
    labels: tuple[LabelPrediction, ...] = ()
    model_version: str | None = None
    out_of_range_fraction: float | None = None

    def positives(self) -> list[LabelPrediction]:
        return [label for label in self.labels if label.state is LabelState.POSITIVE]


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    status: ModelRunStatus
    reason: str = ""
    score: float | None = None
    threshold: float | None = None
    is_anomalous: bool = False
    consecutive: int = 0
    persistent: bool = False
    model_version: str | None = None


@dataclass(frozen=True, slots=True)
class FeatureContribution:
    feature: str
    value: float
    contribution: float


@dataclass(frozen=True, slots=True)
class Explanation:
    """Exact additive decomposition of one predicted probability (tree-path attribution)."""

    category: FaultCategory
    probability: float
    base_value: float
    contributions: tuple[FeatureContribution, ...]

    def supporting(self, limit: int = 6) -> list[FeatureContribution]:
        ranked = sorted(
            (c for c in self.contributions if c.contribution > 0),
            key=lambda c: c.contribution,
            reverse=True,
        )
        return ranked[:limit]

    def opposing(self, limit: int = 6) -> list[FeatureContribution]:
        ranked = sorted(
            (c for c in self.contributions if c.contribution < 0), key=lambda c: c.contribution
        )
        return ranked[:limit]


@dataclass(frozen=True, slots=True)
class HealthComponent:
    name: str
    penalty: float
    explanation: str


@dataclass(frozen=True, slots=True)
class HealthScore:
    score: int | None
    band: str
    components: tuple[HealthComponent, ...]
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.score is not None


@dataclass(frozen=True, slots=True)
class DiagnosticAssessment:
    timestamp: datetime
    elapsed_s: float
    data_source: DataSource
    status: DiagnosticStatus
    severity: Severity
    findings: tuple[Finding, ...]
    quality: DataQuality
    classifier: ClassifierResult
    anomaly: AnomalyResult
    health: HealthScore
    recommendations: tuple[str, ...]
    explanations: dict[FaultCategory, Explanation] = field(default_factory=dict)
    inference_ms: float = 0.0
    vehicle_id: int | None = None
    session_id: int | None = None

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in (Severity.WARNING, Severity.CRITICAL))
