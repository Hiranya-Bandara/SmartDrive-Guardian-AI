"""Display of a single diagnostic finding: severity, source, explanation and evidence."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from smartdrive.config.constants import DiagnosticSource, Severity
from smartdrive.models.diagnostic import Finding
from smartdrive.ui.widgets.base import label
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel

SEVERITY_LEVEL: dict[Severity, StatusLevel] = {
    Severity.CRITICAL: StatusLevel.CRITICAL,
    Severity.WARNING: StatusLevel.WARNING,
    Severity.INFORMATION: StatusLevel.INFO,
    Severity.NORMAL: StatusLevel.NORMAL,
    Severity.UNKNOWN: StatusLevel.OFFLINE,
}

SOURCE_TEXT: dict[DiagnosticSource, str] = {
    DiagnosticSource.RULE: "Rule engine",
    DiagnosticSource.CLASSIFIER: "Random Forest model",
    DiagnosticSource.ANOMALY_DETECTOR: "Anomaly detector",
    DiagnosticSource.DTC: "Trouble code",
    DiagnosticSource.COMBINED: "Combined",
}


def severity_text(severity: Severity) -> str:
    return "Insufficient data" if severity is Severity.UNKNOWN else severity.value.title()


def format_evidence(evidence: dict[str, float | str]) -> str:
    parts = []
    for key, value in evidence.items():
        name = key.replace("_", " ")
        shown = f"{value:.3g}" if isinstance(value, float) else str(value)
        parts.append(f"{name}: {shown}")
    return " · ".join(parts)


class FindingCard(QFrame):
    def __init__(self, finding: Finding, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.finding = finding
        self.setProperty("role", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.severity_pill = StatusIndicator(
            severity_text(finding.severity), SEVERITY_LEVEL[finding.severity]
        )
        self.title_label = label(finding.title, "section-title", wrap=True)
        header.addWidget(self.severity_pill)
        header.addWidget(self.title_label, 1)
        layout.addLayout(header)
        sources = SOURCE_TEXT[finding.source]
        if finding.corroborated_by:
            agreeing = ", ".join(SOURCE_TEXT[s] for s in finding.corroborated_by)
            sources += f" · agrees with: {agreeing}"
        if finding.model_version:
            sources += f" · model {finding.model_version}"
        self.source_label: QLabel = label(f"Source: {sources}", "muted", wrap=True)
        self.explanation_label = label(finding.explanation, wrap=True)
        layout.addWidget(self.source_label)
        layout.addWidget(self.explanation_label)
        if finding.evidence:
            self.evidence_label = label(
                f"Evidence — {format_evidence(finding.evidence)}", "muted", wrap=True
            )
            layout.addWidget(self.evidence_label)
        self.setAccessibleName(f"{severity_text(finding.severity)} finding: {finding.title}")
