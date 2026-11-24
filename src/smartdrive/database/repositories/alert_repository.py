from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from smartdrive.database.models import AlertRecord
from smartdrive.models.alert import Alert


class AlertRepository:
    """Read access for the dashboard. Alert creation arrives with the diagnostic engine."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_recent(self, *, vehicle_id: int | None = None, limit: int = 10) -> list[Alert]:
        stmt = select(AlertRecord).order_by(AlertRecord.last_occurrence_at.desc()).limit(limit)
        if vehicle_id is not None:
            stmt = stmt.where(AlertRecord.vehicle_id == vehicle_id)
        return [Alert.model_validate(r) for r in self._session.scalars(stmt)]
