"""Driving-session recording and telemetry history for the presentation layer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from smartdrive.config.constants import DataSource
from smartdrive.database.connection import Database
from smartdrive.database.repositories import (
    AlertRepository,
    DrivingSessionRepository,
    TelemetryRepository,
)
from smartdrive.models.alert import Alert
from smartdrive.models.session import DrivingSession
from smartdrive.models.telemetry import TelemetrySample

MAX_GAP_FOR_DISTANCE_S: Final = 5.0
DEFAULT_HISTORY_LIMIT: Final = 20_000


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session: DrivingSession
    sample_count: int

    @property
    def duration_s(self) -> float | None:
        if self.session.ended_at is None:
            return None
        return (self.session.ended_at - self.session.started_at).total_seconds()


def estimate_distance_km(samples: Sequence[TelemetrySample]) -> float | None:
    """Trapezoidal integration of vehicle speed; gaps longer than 5 s are not bridged."""
    distance = 0.0
    used = False
    previous: TelemetrySample | None = None
    for sample in samples:
        if sample.speed_kph is None:
            previous = None
            continue
        if previous is not None and previous.speed_kph is not None:
            dt = (sample.timestamp - previous.timestamp).total_seconds()
            if 0 < dt <= MAX_GAP_FOR_DISTANCE_S:
                distance += (previous.speed_kph + sample.speed_kph) / 2.0 * dt / 3600.0
                used = True
        previous = sample
    return distance if used else None


class TelemetryService:
    def __init__(self, database: Database) -> None:
        self._db = database

    def start_session(
        self,
        vehicle_id: int,
        data_source: DataSource,
        *,
        scenario: str | None = None,
        random_seed: int | None = None,
    ) -> DrivingSession:
        with self._db.session() as session:
            return DrivingSessionRepository(session).start(
                vehicle_id, data_source, scenario=scenario, random_seed=random_seed
            )

    def append(self, session_id: int, samples: Sequence[TelemetrySample]) -> int:
        with self._db.session() as session:
            return TelemetryRepository(session).add_batch(session_id, samples)

    def end_session(self, session_id: int) -> DrivingSession:
        samples = self.load_samples(session_id)
        ended_at = samples[-1].timestamp if samples else None
        with self._db.session() as session:
            repo = DrivingSessionRepository(session)
            started = repo.get(session_id).started_at
            return repo.end(
                session_id,
                ended_at=max(ended_at, started) if ended_at else started,
                distance_km=estimate_distance_km(samples),
                distance_estimated=True,
            )

    def close_orphaned_sessions(self) -> int:
        with self._db.session() as session:
            return DrivingSessionRepository(session).close_orphaned()

    def session_summaries(self, vehicle_id: int, *, limit: int = 100) -> list[SessionSummary]:
        with self._db.session() as session:
            sessions = DrivingSessionRepository(session).list_for_vehicle(vehicle_id)[:limit]
            counts = TelemetryRepository(session).counts_by_session([s.id for s in sessions])
        return [SessionSummary(s, counts[s.id]) for s in sessions]

    def load_samples(
        self, session_id: int, *, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> list[TelemetrySample]:
        with self._db.session() as session:
            return TelemetryRepository(session).for_session(session_id, limit=limit)

    def recent_alerts(self, *, vehicle_id: int | None = None, limit: int = 5) -> list[Alert]:
        with self._db.session() as session:
            return AlertRepository(session).list_recent(vehicle_id=vehicle_id, limit=limit)
