"""Driving session model. A session carries exactly one data source so simulated, live and
replayed telemetry can never be mixed."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from smartdrive.config.constants import DataSource


class DrivingSession(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    vehicle_id: int
    data_source: DataSource
    scenario: str | None
    random_seed: int | None
    replay_of_session_id: int | None
    started_at: datetime
    ended_at: datetime | None
    distance_km: float | None
    distance_estimated: bool
    notes: str

    @property
    def is_open(self) -> bool:
        return self.ended_at is None
