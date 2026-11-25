"""Trips: statistics, event timelines, history queries and deletion.

A trip is a recorded driving session (simulation or live). Statistics are computed from the
stored samples when recording stops. Distance is an *estimate* obtained by integrating vehicle
speed over time; intervals longer than ``MAX_GAP_FOR_DISTANCE_S`` or without a speed reading
are not bridged, and ``distance_coverage`` reports which share of the recorded time contributed.
No GPS position, route, fuel consumption or odometer value is derived.

Deleting a trip removes its telemetry, summary and events. Diagnostic history, alerts and
trouble-code records that referenced the trip are kept and lose only the link.

A condition that persists produces one timeline event; it produces a new one if it escalates
(for example from warning to critical) or returns after a gap of more than a minute.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import delete, func, select

from smartdrive.config.constants import (
    DataSource,
    DiagnosticSource,
    SessionStatus,
    Severity,
    TripEventType,
)
from smartdrive.core.telemetry_window import CORE_SENSORS
from smartdrive.database.connection import Database
from smartdrive.database.models import (
    DiagnosticAssessmentRecord,
    DiagnosticResultRecord,
    DrivingSessionRecord,
    DtcScanRecord,
    TelemetryReadingRecord,
    TripEventRecord,
    TripSummaryRecord,
    VehicleRecord,
)
from smartdrive.database.types import utc_now
from smartdrive.models.diagnostic import SEVERITY_RANK
from smartdrive.models.session import DrivingSession
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.services.telemetry_service import MAX_GAP_FOR_DISTANCE_S, TelemetryService
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError

logger = logging.getLogger(__name__)

FINDING_GAP: Final = timedelta(seconds=60)
EVENT_SEVERITIES: Final = (Severity.INFORMATION, Severity.WARNING, Severity.CRITICAL)


@dataclass(frozen=True, slots=True)
class TripStatistics:
    sample_count: int
    recorded_duration_s: float
    data_completeness: float
    avg_speed_kph: float | None
    max_speed_kph: float | None
    avg_rpm: float | None
    max_rpm: float | None
    min_coolant_c: float | None
    max_coolant_c: float | None
    distance_km: float | None
    distance_coverage: float | None


def compute_statistics(samples: Sequence[TelemetrySample]) -> TripStatistics:
    """Statistics over the readings that exist. Missing readings are skipped, never zero-filled."""
    ordered = sorted(samples, key=lambda s: s.timestamp)
    if not ordered:
        return TripStatistics(0, 0.0, 0.0, None, None, None, None, None, None, None, None)
    duration = (ordered[-1].timestamp - ordered[0].timestamp).total_seconds()
    speeds = [s.speed_kph for s in ordered if s.speed_kph is not None]
    rpms = [s.rpm for s in ordered if s.rpm is not None]
    coolant = [s.coolant_temp_c for s in ordered if s.coolant_temp_c is not None]
    completeness = statistics.fmean(
        sum(getattr(s, name) is not None for name in CORE_SENSORS) / len(CORE_SENSORS)
        for s in ordered
    )
    distance, covered = integrate_distance(ordered)
    return TripStatistics(
        sample_count=len(ordered),
        recorded_duration_s=round(duration, 1),
        data_completeness=round(completeness, 4),
        avg_speed_kph=_round(statistics.fmean(speeds)) if speeds else None,
        max_speed_kph=_round(max(speeds)) if speeds else None,
        avg_rpm=_round(statistics.fmean(rpms), 0) if rpms else None,
        max_rpm=_round(max(rpms), 0) if rpms else None,
        min_coolant_c=_round(min(coolant)) if coolant else None,
        max_coolant_c=_round(max(coolant)) if coolant else None,
        distance_km=None if distance is None else round(distance, 3),
        distance_coverage=None
        if distance is None or duration <= 0
        else round(min(1.0, covered / duration), 4),
    )


def integrate_distance(samples: Sequence[TelemetrySample]) -> tuple[float | None, float]:
    """Trapezoidal speed integration over consecutive readings no more than 5 s apart.

    Returns the distance in kilometres (``None`` without any usable interval) and the number of
    seconds that contributed. Irregular intervals are handled by using each actual interval.
    """
    distance = 0.0
    covered = 0.0
    previous: TelemetrySample | None = None
    for sample in sorted(samples, key=lambda s: s.timestamp):
        if sample.speed_kph is None:
            previous = None
            continue
        if previous is not None and previous.speed_kph is not None:
            dt = (sample.timestamp - previous.timestamp).total_seconds()
            if 0 < dt <= MAX_GAP_FOR_DISTANCE_S:
                distance += (previous.speed_kph + sample.speed_kph) / 2.0 * dt / 3600.0
                covered += dt
        previous = sample
    return (distance if covered > 0 else None), covered


def _round(value: float, digits: int = 1) -> float:
    return round(value, digits)


@dataclass(frozen=True, slots=True)
class TripListItem:
    session: DrivingSession
    vehicle_name: str
    sample_count: int
    summary: dict[str, Any] | None

    @property
    def duration_s(self) -> float | None:
        if self.session.ended_at is None:
            return None
        return (self.session.ended_at - self.session.started_at).total_seconds()

    @property
    def worst_severity(self) -> Severity:
        if self.summary is None:
            return Severity.UNKNOWN
        if self.summary["critical_count"]:
            return Severity.CRITICAL
        if self.summary["warning_count"]:
            return Severity.WARNING
        return Severity.NORMAL


@dataclass(frozen=True, slots=True)
class TripEvent:
    id: int
    occurred_at: datetime
    event_type: TripEventType
    severity: Severity
    title: str
    detail: str
    source: str | None


class TripService:
    def __init__(self, database: Database, telemetry: TelemetryService) -> None:
        self._db = database
        self._telemetry = telemetry

    # -- recording lifecycle ----------------------------------------------------------------------

    def add_event(
        self,
        session_id: int,
        event_type: TripEventType,
        title: str,
        *,
        severity: Severity = Severity.INFORMATION,
        detail: str = "",
        occurred_at: datetime | None = None,
        source: str | None = None,
    ) -> None:
        with self._db.session() as session:
            if session.get(DrivingSessionRecord, session_id) is None:
                return
            session.add(
                TripEventRecord(
                    session_id=session_id,
                    occurred_at=occurred_at or utc_now(),
                    event_type=event_type,
                    severity=severity,
                    title=title[:160],
                    detail=detail,
                    source=source,
                )
            )

    def finalize(self, session_id: int) -> dict[str, Any]:
        """Compute and store the trip summary and finding events. Safe to call more than once."""
        samples = self._telemetry.load_samples(session_id)
        stats = compute_statistics(samples)
        with self._db.session() as session:
            record = session.get(DrivingSessionRecord, session_id)
            if record is None:
                raise RecordNotFoundError(f"Trip {session_id} does not exist.")
            findings = list(
                session.scalars(
                    select(DiagnosticResultRecord)
                    .where(DiagnosticResultRecord.session_id == session_id)
                    .order_by(DiagnosticResultRecord.created_at)
                )
            )
            session.execute(
                delete(TripEventRecord).where(
                    TripEventRecord.session_id == session_id,
                    TripEventRecord.event_type.in_((TripEventType.FINDING, TripEventType.ANOMALY)),
                )
            )
            counts = {"events": 0, "warning": 0, "critical": 0, "anomaly": 0}
            last_seen: dict[str, tuple[datetime, int]] = {}
            for finding in findings:
                key = finding.finding_key or finding.summary
                rank = SEVERITY_RANK.get(finding.severity, 0)
                previous = last_seen.get(key)
                if (
                    previous is not None
                    and finding.created_at - previous[0] <= FINDING_GAP
                    and rank <= previous[1]
                ):
                    last_seen[key] = (finding.created_at, previous[1])
                    continue  # the same condition persisting, not a new event
                last_seen[key] = (finding.created_at, rank)
                anomaly = finding.source is DiagnosticSource.ANOMALY_DETECTOR
                counts["events"] += 1
                counts["anomaly"] += int(anomaly)
                counts["warning"] += int(finding.severity is Severity.WARNING)
                counts["critical"] += int(finding.severity is Severity.CRITICAL)
                session.add(
                    TripEventRecord(
                        session_id=session_id,
                        occurred_at=finding.created_at,
                        event_type=TripEventType.ANOMALY if anomaly else TripEventType.FINDING,
                        severity=finding.severity
                        if finding.severity in EVENT_SEVERITIES
                        else Severity.INFORMATION,
                        title=finding.summary[:160],
                        detail=str(finding.explanation.get("text", "")),
                        source=finding.source.value,
                        finding_key=finding.finding_key,
                    )
                )
            dtc_count = session.scalar(
                select(func.sum(DtcScanRecord.stored_count)).where(
                    DtcScanRecord.session_id == session_id
                )
            )
            versions: dict[str, Any] = {}
            for (value,) in session.execute(
                select(DiagnosticAssessmentRecord.model_versions)
                .where(DiagnosticAssessmentRecord.session_id == session_id)
                .distinct()
            ):
                for name, version in (value or {}).items():
                    if version:
                        versions.setdefault(name, version)
            summary = session.get(TripSummaryRecord, session_id) or TripSummaryRecord(
                session_id=session_id
            )
            summary.computed_at = utc_now()
            summary.sample_count = stats.sample_count
            summary.recorded_duration_s = stats.recorded_duration_s
            summary.data_completeness = stats.data_completeness
            summary.avg_speed_kph = stats.avg_speed_kph
            summary.max_speed_kph = stats.max_speed_kph
            summary.avg_rpm = stats.avg_rpm
            summary.max_rpm = stats.max_rpm
            summary.min_coolant_c = stats.min_coolant_c
            summary.max_coolant_c = stats.max_coolant_c
            summary.distance_km = stats.distance_km
            summary.distance_coverage = stats.distance_coverage
            summary.diagnostic_event_count = counts["events"]
            summary.warning_count = counts["warning"]
            summary.critical_count = counts["critical"]
            summary.anomaly_count = counts["anomaly"]
            summary.dtc_count = None if dtc_count is None else int(dtc_count)
            summary.model_versions = versions
            session.add(summary)
            if record.distance_km is None and stats.distance_km is not None:
                record.distance_km = stats.distance_km
            session.flush()
            return _summary_dict(summary)

    def finalize_missing(self) -> int:
        """Summarise ended trips that have no summary yet (for example after a crash)."""
        with self._db.session() as session:
            ids = list(
                session.scalars(
                    select(DrivingSessionRecord.id)
                    .outerjoin(
                        TripSummaryRecord,
                        TripSummaryRecord.session_id == DrivingSessionRecord.id,
                    )
                    .where(
                        DrivingSessionRecord.ended_at.is_not(None),
                        TripSummaryRecord.session_id.is_(None),
                    )
                )
            )
        for session_id in ids:
            self.finalize(session_id)
        return len(ids)

    # -- queries ---------------------------------------------------------------------------------

    def list_trips(
        self,
        *,
        vehicle_id: int | None = None,
        data_source: DataSource | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        min_severity: Severity | None = None,
        search: str = "",
        limit: int = 500,
    ) -> list[TripListItem]:
        stmt = (
            select(DrivingSessionRecord, VehicleRecord.name, TripSummaryRecord)
            .join(VehicleRecord, VehicleRecord.id == DrivingSessionRecord.vehicle_id)
            .outerjoin(TripSummaryRecord, TripSummaryRecord.session_id == DrivingSessionRecord.id)
            .where(DrivingSessionRecord.data_source != DataSource.REPLAY)
            .order_by(DrivingSessionRecord.started_at.desc())
            .limit(limit)
        )
        if vehicle_id is not None:
            stmt = stmt.where(DrivingSessionRecord.vehicle_id == vehicle_id)
        if data_source is not None:
            stmt = stmt.where(DrivingSessionRecord.data_source == data_source)
        if start is not None:
            stmt = stmt.where(DrivingSessionRecord.started_at >= start)
        if end is not None:
            stmt = stmt.where(DrivingSessionRecord.started_at <= end)
        if min_severity is Severity.CRITICAL:
            stmt = stmt.where(TripSummaryRecord.critical_count > 0)
        elif min_severity is Severity.WARNING:
            stmt = stmt.where(
                (TripSummaryRecord.warning_count > 0) | (TripSummaryRecord.critical_count > 0)
            )
        text = search.strip()
        if text:
            pattern = f"%{text}%"
            stmt = stmt.where(
                DrivingSessionRecord.name.ilike(pattern)
                | DrivingSessionRecord.scenario.ilike(pattern)
                | DrivingSessionRecord.notes.ilike(pattern)
                | VehicleRecord.name.ilike(pattern)
            )
        with self._db.session() as session:
            rows = list(session.execute(stmt))
            ids = [row[0].id for row in rows]
            counts = dict(
                session.execute(
                    select(TelemetryReadingRecord.session_id, func.count())
                    .where(TelemetryReadingRecord.session_id.in_(ids))
                    .group_by(TelemetryReadingRecord.session_id)
                ).all()
            )
            return [
                TripListItem(
                    session=DrivingSession.model_validate(record),
                    vehicle_name=name,
                    sample_count=int(counts.get(record.id, 0)),
                    summary=None if summary is None else _summary_dict(summary),
                )
                for record, name, summary in rows
            ]

    def get_trip(self, session_id: int) -> TripListItem:
        with self._db.session() as session:
            record = session.get(DrivingSessionRecord, session_id)
            if record is None:
                raise RecordNotFoundError(f"Trip {session_id} does not exist.")
            vehicle = session.get(VehicleRecord, record.vehicle_id)
            summary = session.get(TripSummaryRecord, session_id)
            count = session.scalar(
                select(func.count()).where(TelemetryReadingRecord.session_id == session_id)
            )
            return TripListItem(
                session=DrivingSession.model_validate(record),
                vehicle_name=vehicle.name if vehicle else "",
                sample_count=int(count or 0),
                summary=None if summary is None else _summary_dict(summary),
            )

    def events(self, session_id: int) -> list[TripEvent]:
        with self._db.session() as session:
            rows = session.scalars(
                select(TripEventRecord)
                .where(TripEventRecord.session_id == session_id)
                .order_by(TripEventRecord.occurred_at, TripEventRecord.id)
            )
            return [
                TripEvent(
                    r.id, r.occurred_at, r.event_type, r.severity, r.title, r.detail, r.source
                )
                for r in rows
            ]

    def health_history(self, session_id: int) -> list[tuple[datetime, int | None]]:
        with self._db.session() as session:
            rows = session.execute(
                select(
                    DiagnosticAssessmentRecord.created_at, DiagnosticAssessmentRecord.health_score
                )
                .where(DiagnosticAssessmentRecord.session_id == session_id)
                .order_by(DiagnosticAssessmentRecord.created_at)
            )
            return [(created, score) for created, score in rows]

    def mark_interrupted(self, session_id: int, reason: str) -> None:
        """Record that recording stopped because the data source failed, not by the user."""
        with self._db.session() as session:
            record = session.get(DrivingSessionRecord, session_id)
            if record is None:
                raise RecordNotFoundError(f"Trip {session_id} does not exist.")
            record.status = SessionStatus.INTERRUPTED
            session.add(
                TripEventRecord(
                    session_id=session_id,
                    occurred_at=record.ended_at or utc_now(),
                    event_type=TripEventType.RECORDING_INTERRUPTED,
                    severity=Severity.WARNING,
                    title="Recording interrupted",
                    detail=reason,
                    source="connection",
                )
            )

    def rename(self, session_id: int, name: str) -> None:
        with self._db.session() as session:
            record = session.get(DrivingSessionRecord, session_id)
            if record is None:
                raise RecordNotFoundError(f"Trip {session_id} does not exist.")
            record.name = name.strip()[:80] or None

    def delete_trip(self, session_id: int) -> None:
        with self._db.session() as session:
            record = session.get(DrivingSessionRecord, session_id)
            if record is None:
                raise RecordNotFoundError(f"Trip {session_id} does not exist.")
            if record.status is SessionStatus.RECORDING and record.ended_at is None:
                raise DataValidationError(
                    "Trip is still recording",
                    user_message="Stop recording before deleting this trip.",
                )
            session.delete(record)


def _summary_dict(summary: TripSummaryRecord) -> dict[str, Any]:
    return {
        "computed_at": summary.computed_at,
        "sample_count": summary.sample_count,
        "recorded_duration_s": summary.recorded_duration_s,
        "data_completeness": summary.data_completeness,
        "avg_speed_kph": summary.avg_speed_kph,
        "max_speed_kph": summary.max_speed_kph,
        "avg_rpm": summary.avg_rpm,
        "max_rpm": summary.max_rpm,
        "min_coolant_c": summary.min_coolant_c,
        "max_coolant_c": summary.max_coolant_c,
        "distance_km": summary.distance_km,
        "distance_coverage": summary.distance_coverage,
        "diagnostic_event_count": summary.diagnostic_event_count,
        "warning_count": summary.warning_count,
        "critical_count": summary.critical_count,
        "anomaly_count": summary.anomaly_count,
        "dtc_count": summary.dtc_count,
        "model_versions": dict(summary.model_versions or {}),
    }
