"""Persistence of assessments, findings and AI alerts, plus history queries.

Alert policy:
- Only WARNING and CRITICAL findings create alerts.
- The deduplication key is vehicle + finding key (for example ``v3:rule:coolant_temperature``).
- A finding that repeats within the cooldown, or that persists without a gap longer than the
  cooldown, updates the existing alert (occurrence count, last time, escalated severity)
  instead of creating a new one.
- History rows are written every ``history_interval_s`` and immediately whenever the set of
  findings or the status changes, so short events are never lost but steady states do not flood
  the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from smartdrive.ai.model_registry import LoadedModels, LoadStatus
from smartdrive.config.constants import DiagnosticSource, Severity
from smartdrive.database.connection import Database
from smartdrive.database.repositories.diagnostic_repository import (
    DiagnosticHistoryEntry,
    DiagnosticRepository,
    HealthPoint,
)
from smartdrive.models.diagnostic import (
    SEVERITY_RANK,
    DiagnosticAssessment,
    DiagnosticStatus,
    Finding,
)

logger = logging.getLogger(__name__)

ALERT_SEVERITIES = (Severity.WARNING, Severity.CRITICAL)


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    assessment_id: int | None
    new_alerts: tuple[Finding, ...] = ()
    updated_alerts: int = 0


@dataclass
class _StreamState:
    last_saved_at: datetime | None = None
    last_signature: tuple[str, ...] = field(default_factory=tuple)


class DiagnosticService:
    def __init__(self, database: Database) -> None:
        self._db = database
        self._streams: dict[int, _StreamState] = {}

    def reset_stream(self, vehicle_id: int | None = None) -> None:
        if vehicle_id is None:
            self._streams.clear()
        else:
            self._streams.pop(vehicle_id, None)

    # -- writing --------------------------------------------------------------------------------

    def record(
        self,
        assessment: DiagnosticAssessment,
        *,
        history_interval_s: float,
        alert_cooldown_s: float,
    ) -> RecordOutcome:
        vehicle_id = assessment.vehicle_id
        if vehicle_id is None:
            return RecordOutcome(None)
        state = self._streams.setdefault(vehicle_id, _StreamState())
        signature = (
            assessment.status.value,
            *sorted(f"{f.key}:{f.severity.value}" for f in assessment.findings),
        )
        due = (
            state.last_saved_at is None
            or (assessment.timestamp - state.last_saved_at).total_seconds() >= history_interval_s
        )
        changed = signature != state.last_signature
        with self._db.session() as session:
            repo = DiagnosticRepository(session)
            assessment_id = None
            if due or changed:
                assessment_id = self._save(repo, assessment, vehicle_id)
                state.last_saved_at = assessment.timestamp
                state.last_signature = signature
            new_alerts, updated = self._alerts(repo, assessment, alert_cooldown_s)
            self._resolve_cleared(repo, assessment)
        return RecordOutcome(assessment_id, tuple(new_alerts), updated)

    @staticmethod
    def _resolve_cleared(repo: DiagnosticRepository, a: DiagnosticAssessment) -> None:
        """Mark alerts resolved when their finding is absent from an analysis that could have
        detected it. Stale or insufficient data never resolves an alert."""
        if a.status in (DiagnosticStatus.STALE, DiagnosticStatus.INSUFFICIENT_DATA):
            return
        present = {f"v{a.vehicle_id}:{f.key}" for f in a.findings if f.severity in ALERT_SEVERITIES}
        for alert in repo.open_alerts(a.vehicle_id):
            if alert.dedup_key not in present:
                alert.resolved_at = a.timestamp

    def _save(self, repo: DiagnosticRepository, a: DiagnosticAssessment, vehicle_id: int) -> int:
        assessment_id = repo.add_assessment(
            vehicle_id=vehicle_id,
            session_id=a.session_id,
            created_at=a.timestamp,
            data_source=a.data_source,
            status=a.status,
            severity=a.severity,
            health_score=a.health.score,
            data_completeness=round(a.quality.overall_completeness, 4),
            classifier_status=a.classifier.status.value,
            anomaly_status=a.anomaly.status.value,
            anomaly_score=a.anomaly.score,
            is_anomalous=a.anomaly.is_anomalous,
            probabilities={p.category.value: round(p.probability, 4) for p in a.classifier.labels},
            model_versions={
                "classifier": a.classifier.model_version,
                "anomaly": a.anomaly.model_version,
            },
            inference_ms=round(a.inference_ms, 2),
        )
        repo.add_findings(
            {
                "vehicle_id": vehicle_id,
                "session_id": a.session_id,
                "assessment_id": assessment_id,
                "created_at": a.timestamp,
                "data_source": a.data_source,
                "finding_key": f.key,
                "source": f.source,
                "category": f.category,
                "severity": f.severity,
                "summary": f.title[:255],
                "explanation": {
                    "text": f.explanation,
                    "evidence": f.evidence,
                    "corroborated_by": [s.value for s in f.corroborated_by],
                },
                "recommendation": "\n".join(a.recommendations),
                "confidence": f.probability,
                "anomaly_score": a.anomaly.score
                if f.source is DiagnosticSource.ANOMALY_DETECTOR
                else None,
                "model_version": f.model_version,
                "data_quality": round(a.quality.overall_completeness, 4),
            }
            for f in a.findings
        )
        return assessment_id

    def _alerts(
        self, repo: DiagnosticRepository, a: DiagnosticAssessment, cooldown_s: float
    ) -> tuple[list[Finding], int]:
        new: list[Finding] = []
        updated = 0
        cooldown = timedelta(seconds=cooldown_s)
        for finding in a.findings:
            if finding.severity not in ALERT_SEVERITIES:
                continue
            key = f"v{a.vehicle_id}:{finding.key}"
            existing = repo.latest_alert(key)
            if existing is not None and a.timestamp - existing.last_occurrence_at <= cooldown:
                existing.occurrence_count += 1
                existing.last_occurrence_at = a.timestamp
                existing.resolved_at = None
                if SEVERITY_RANK[finding.severity] > SEVERITY_RANK[existing.severity]:
                    existing.severity = finding.severity
                    existing.title = finding.title[:160]
                    existing.acknowledged_at = None
                updated += 1
                continue
            repo.add_alert(
                vehicle_id=a.vehicle_id,
                session_id=a.session_id,
                created_at=a.timestamp,
                last_occurrence_at=a.timestamp,
                severity=finding.severity,
                category=finding.category.value,
                title=finding.title[:160],
                message=finding.explanation,
                data_source=a.data_source,
                source=finding.source,
                dedup_key=key,
                occurrence_count=1,
                evidence={
                    "finding_key": finding.key,
                    "evidence": finding.evidence,
                    "probability": finding.probability,
                    "corroborated_by": [s.value for s in finding.corroborated_by],
                    "model_version": finding.model_version,
                },
            )
            new.append(finding)
        return new, updated

    def register_models(self, models: LoadedModels) -> None:
        with self._db.session() as session:
            repo = DiagnosticRepository(session)
            for name, entry in models.manifest.items():
                if models.status.get(name) is not LoadStatus.AVAILABLE:
                    continue
                repo.upsert_model(
                    name=name,
                    version=entry["version"],
                    model_type=entry["model_type"],
                    file_name=entry["file"],
                    sha256=entry["sha256"],
                    trained_at=datetime.fromisoformat(entry["trained_at"]),
                    trained_on_synthetic_data=bool(entry.get("synthetic", True)),
                    dataset_description=f"{entry['dataset_version']} — {entry['dataset_source']}",
                    metrics=entry.get("evaluation", {}),
                    is_active=True,
                )

    # -- reading --------------------------------------------------------------------------------

    def history(self, **filters: Any) -> list[DiagnosticHistoryEntry]:
        with self._db.session() as session:
            return DiagnosticRepository(session).history(**filters)

    def health_trend(self, vehicle_id: int, *, limit: int = 200) -> list[HealthPoint]:
        with self._db.session() as session:
            return DiagnosticRepository(session).health_trend(vehicle_id, limit=limit)

    def recent_alert_count(self, vehicle_id: int | None, *, minutes: int = 15) -> int:
        if vehicle_id is None:
            return 0
        since = datetime.now(UTC) - timedelta(minutes=minutes)
        with self._db.session() as session:
            return DiagnosticRepository(session).count_alerts_since(vehicle_id, since)
