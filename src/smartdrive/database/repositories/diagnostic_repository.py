from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from smartdrive.config.constants import DataSource, DiagnosticSource, FaultCategory, Severity
from smartdrive.database.models import (
    AlertRecord,
    DiagnosticAssessmentRecord,
    DiagnosticResultRecord,
    ModelMetadataRecord,
)
from smartdrive.models.diagnostic import DiagnosticStatus


class DiagnosticHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    created_at: datetime
    vehicle_id: int
    session_id: int | None
    assessment_id: int | None
    data_source: DataSource | None
    finding_key: str | None
    source: DiagnosticSource
    category: FaultCategory
    severity: Severity
    summary: str
    explanation: dict[str, Any]
    recommendation: str
    confidence: float | None
    anomaly_score: float | None
    model_version: str | None


class HealthPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    created_at: datetime
    health_score: int | None
    status: DiagnosticStatus
    session_id: int | None


class DiagnosticRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_assessment(self, **values: Any) -> int:
        record = DiagnosticAssessmentRecord(**values)
        self._session.add(record)
        self._session.flush()
        return record.id

    def add_findings(self, rows: Iterable[dict[str, Any]]) -> int:
        records = [DiagnosticResultRecord(**row) for row in rows]
        self._session.add_all(records)
        self._session.flush()
        return len(records)

    def history(
        self,
        *,
        vehicle_id: int | None = None,
        severities: Iterable[Severity] | None = None,
        source: DiagnosticSource | None = None,
        data_source: DataSource | None = None,
        search: str | None = None,
        limit: int = 200,
    ) -> list[DiagnosticHistoryEntry]:
        stmt = (
            select(DiagnosticResultRecord)
            .order_by(DiagnosticResultRecord.created_at.desc(), DiagnosticResultRecord.id.desc())
            .limit(limit)
        )
        if vehicle_id is not None:
            stmt = stmt.where(DiagnosticResultRecord.vehicle_id == vehicle_id)
        if severities is not None:
            stmt = stmt.where(DiagnosticResultRecord.severity.in_(list(severities)))
        if source is not None:
            stmt = stmt.where(DiagnosticResultRecord.source == source)
        if data_source is not None:
            stmt = stmt.where(DiagnosticResultRecord.data_source == data_source)
        if search and search.strip():
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(DiagnosticResultRecord.summary).like(pattern),
                    func.lower(DiagnosticResultRecord.recommendation).like(pattern),
                    func.lower(DiagnosticResultRecord.category).like(pattern),
                )
            )
        return [DiagnosticHistoryEntry.model_validate(r) for r in self._session.scalars(stmt)]

    def health_trend(self, vehicle_id: int, *, limit: int = 200) -> list[HealthPoint]:
        stmt = (
            select(DiagnosticAssessmentRecord)
            .where(DiagnosticAssessmentRecord.vehicle_id == vehicle_id)
            .order_by(DiagnosticAssessmentRecord.created_at.desc())
            .limit(limit)
        )
        return [HealthPoint.model_validate(r) for r in self._session.scalars(stmt)][::-1]

    def assessment_count(self, vehicle_id: int) -> int:
        stmt = select(func.count(DiagnosticAssessmentRecord.id)).where(
            DiagnosticAssessmentRecord.vehicle_id == vehicle_id
        )
        return int(self._session.scalar(stmt) or 0)

    # -- alerts ---------------------------------------------------------------------------------

    def latest_alert(self, dedup_key: str) -> AlertRecord | None:
        stmt = (
            select(AlertRecord)
            .where(AlertRecord.dedup_key == dedup_key)
            .order_by(AlertRecord.last_occurrence_at.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def open_alerts(self, vehicle_id: int | None) -> list[AlertRecord]:
        stmt = select(AlertRecord).where(
            AlertRecord.vehicle_id == vehicle_id, AlertRecord.resolved_at.is_(None)
        )
        return list(self._session.scalars(stmt))

    def add_alert(self, **values: Any) -> AlertRecord:
        record = AlertRecord(**values)
        self._session.add(record)
        self._session.flush()
        return record

    def count_alerts_since(self, vehicle_id: int, since: datetime) -> int:
        stmt = select(func.count(AlertRecord.id)).where(
            AlertRecord.vehicle_id == vehicle_id,
            AlertRecord.last_occurrence_at >= since,
            AlertRecord.severity.in_([Severity.WARNING, Severity.CRITICAL]),
        )
        return int(self._session.scalar(stmt) or 0)

    # -- model metadata -------------------------------------------------------------------------

    def upsert_model(self, **values: Any) -> int:
        stmt = select(ModelMetadataRecord).where(
            ModelMetadataRecord.name == values["name"],
            ModelMetadataRecord.version == values["version"],
        )
        record = self._session.scalars(stmt).first()
        if record is None:
            record = ModelMetadataRecord(**values)
            self._session.add(record)
        else:
            for key, value in values.items():
                setattr(record, key, value)
        self._session.flush()
        self._session.execute(
            update(ModelMetadataRecord)
            .where(ModelMetadataRecord.name == values["name"], ModelMetadataRecord.id != record.id)
            .values(is_active=False)
        )
        return record.id

    def active_models(self) -> list[ModelMetadataRecord]:
        stmt = select(ModelMetadataRecord).where(ModelMetadataRecord.is_active.is_(True))
        return list(self._session.scalars(stmt))
