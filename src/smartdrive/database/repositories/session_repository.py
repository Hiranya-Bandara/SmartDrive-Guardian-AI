from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from smartdrive.config.constants import DataSource
from smartdrive.database.models import (
    DrivingSessionRecord,
    TelemetryReadingRecord,
    VehicleRecord,
)
from smartdrive.database.types import utc_now
from smartdrive.models.session import DrivingSession
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError


class DrivingSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start(
        self,
        vehicle_id: int,
        data_source: DataSource,
        *,
        scenario: str | None = None,
        random_seed: int | None = None,
        replay_of_session_id: int | None = None,
        started_at: datetime | None = None,
    ) -> DrivingSession:
        if self._session.get(VehicleRecord, vehicle_id) is None:
            raise RecordNotFoundError(f"Vehicle {vehicle_id} does not exist.")
        if (data_source is DataSource.REPLAY) != (replay_of_session_id is not None):
            raise DataValidationError(
                "Replay sessions must reference a recorded session, and only replay sessions may."
            )
        record = DrivingSessionRecord(
            vehicle_id=vehicle_id,
            data_source=data_source,
            scenario=scenario,
            random_seed=random_seed,
            replay_of_session_id=replay_of_session_id,
            started_at=started_at or utc_now(),
        )
        self._session.add(record)
        self._session.flush()
        return DrivingSession.model_validate(record)

    def end(
        self,
        session_id: int,
        *,
        ended_at: datetime | None = None,
        distance_km: float | None = None,
        distance_estimated: bool = True,
    ) -> DrivingSession:
        record = self._require(session_id)
        end_time = ended_at or utc_now()
        if end_time < record.started_at:
            raise DataValidationError("A session cannot end before it started.")
        record.ended_at = end_time
        record.distance_km = distance_km
        record.distance_estimated = distance_estimated
        self._session.flush()
        return DrivingSession.model_validate(record)

    def get(self, session_id: int) -> DrivingSession:
        return DrivingSession.model_validate(self._require(session_id))

    def list_for_vehicle(
        self, vehicle_id: int, *, data_source: DataSource | None = None
    ) -> list[DrivingSession]:
        stmt = (
            select(DrivingSessionRecord)
            .where(DrivingSessionRecord.vehicle_id == vehicle_id)
            .order_by(DrivingSessionRecord.started_at.desc())
        )
        if data_source is not None:
            stmt = stmt.where(DrivingSessionRecord.data_source == data_source)
        return [DrivingSession.model_validate(r) for r in self._session.scalars(stmt)]

    def close_orphaned(self) -> int:
        """End sessions left open by an unclean shutdown at their last recorded reading."""
        open_records = list(
            self._session.scalars(
                select(DrivingSessionRecord).where(DrivingSessionRecord.ended_at.is_(None))
            )
        )
        for record in open_records:
            last = self._session.scalar(
                select(func.max(TelemetryReadingRecord.timestamp)).where(
                    TelemetryReadingRecord.session_id == record.id
                )
            )
            record.ended_at = max(last, record.started_at) if last else record.started_at
        self._session.flush()
        return len(open_records)

    def _require(self, session_id: int) -> DrivingSessionRecord:
        record = self._session.get(DrivingSessionRecord, session_id)
        if record is None:
            raise RecordNotFoundError(f"Driving session {session_id} does not exist.")
        return record
