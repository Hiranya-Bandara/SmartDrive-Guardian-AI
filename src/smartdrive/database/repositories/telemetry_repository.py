from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from smartdrive.database.models import DrivingSessionRecord, TelemetryReadingRecord
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError

_COLUMNS = (*TelemetrySample.sensor_fields, "timestamp", "fuel_rate_estimated", "extra")


class TelemetryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_batch(self, session_id: int, samples: Sequence[TelemetrySample]) -> int:
        """Insert samples with a single executemany. Closed sessions are read-only."""
        if not samples:
            return 0
        owner = self._session.get(DrivingSessionRecord, session_id)
        if owner is None:
            raise RecordNotFoundError(f"Driving session {session_id} does not exist.")
        if owner.ended_at is not None:
            raise DataValidationError("Cannot add telemetry to a session that has ended.")
        rows = [{"session_id": session_id, **{c: getattr(s, c) for c in _COLUMNS}} for s in samples]
        self._session.execute(insert(TelemetryReadingRecord), rows)
        return len(rows)

    def for_session(
        self,
        session_id: int,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[TelemetrySample]:
        stmt = (
            select(TelemetryReadingRecord)
            .where(TelemetryReadingRecord.session_id == session_id)
            .order_by(TelemetryReadingRecord.timestamp, TelemetryReadingRecord.id)
        )
        if start is not None:
            stmt = stmt.where(TelemetryReadingRecord.timestamp >= start)
        if end is not None:
            stmt = stmt.where(TelemetryReadingRecord.timestamp <= end)
        if limit is not None:
            stmt = stmt.limit(limit)
        return [
            TelemetrySample.model_validate({c: getattr(r, c) for c in _COLUMNS})
            for r in self._session.scalars(stmt)
        ]

    def count(self, session_id: int) -> int:
        stmt = select(func.count()).where(TelemetryReadingRecord.session_id == session_id)
        return int(self._session.scalar(stmt) or 0)

    def purge_sessions_before(self, cutoff: datetime) -> int:
        """Retention policy: delete finished sessions that started before ``cutoff``.
        Their telemetry is removed by the foreign-key cascade."""
        result = self._session.execute(
            delete(DrivingSessionRecord).where(
                DrivingSessionRecord.started_at < cutoff,
                DrivingSessionRecord.ended_at.is_not(None),
            )
        )
        self._session.expire_all()
        return int(result.rowcount)  # type: ignore[attr-defined]
