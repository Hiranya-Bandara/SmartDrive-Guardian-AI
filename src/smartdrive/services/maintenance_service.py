"""Maintenance records, user-defined schedules, reminders, costs and cautious observations.

Schedules are entered by the user. SmartDrive ships no manufacturer intervals; the optional
``EXAMPLE_INTERVALS`` are generic examples, always labelled as such, to be replaced with the
vehicle's own recommendations.

Mileage-based reminders use the odometer reading the user last recorded and when it was
recorded. A reading older than ``odometer_stale_days`` is not treated as current: the distance
part of a schedule then reports insufficient mileage information instead of a guess.

Costs are summed per currency; amounts in different currencies are never added together.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from smartdrive.config.constants import (
    DiagnosticSource,
    DtcStatus,
    MaintenanceCategory,
    MaintenanceStatus,
    Severity,
)
from smartdrive.database.connection import Database
from smartdrive.database.models import (
    DiagnosticAssessmentRecord,
    DiagnosticResultRecord,
    DiagnosticTroubleCodeRecord,
    MaintenanceRecord,
    MaintenanceScheduleRecord,
    VehicleRecord,
)
from smartdrive.database.types import utc_now
from smartdrive.models.maintenance import (
    MaintenanceRecordInput,
    MaintenanceRecordView,
    ScheduleInput,
    ScheduleState,
    ScheduleStatus,
    ScheduleView,
)
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError

logger = logging.getLogger(__name__)

DUE_WINDOW_DAYS: Final = 7
DUE_WINDOW_KM: Final = 250.0

EXAMPLE_INTERVALS: Final[dict[MaintenanceCategory, tuple[int | None, float | None]]] = {
    # (days, km) — illustrative examples only, NOT manufacturer recommendations.
    MaintenanceCategory.ENGINE_OIL: (365, 10_000.0),
    MaintenanceCategory.OIL_FILTER: (365, 10_000.0),
    MaintenanceCategory.AIR_FILTER: (730, 20_000.0),
    MaintenanceCategory.CABIN_AIR_FILTER: (365, 15_000.0),
    MaintenanceCategory.BRAKE_INSPECTION: (365, 20_000.0),
    MaintenanceCategory.BRAKE_FLUID: (730, None),
    MaintenanceCategory.COOLANT: (1825, 100_000.0),
    MaintenanceCategory.BATTERY: (365, None),
    MaintenanceCategory.TYRE_INSPECTION: (90, 5_000.0),
    MaintenanceCategory.TYRE_ROTATION: (None, 10_000.0),
    MaintenanceCategory.TRANSMISSION: (None, 60_000.0),
    MaintenanceCategory.SPARK_PLUGS: (None, 40_000.0),
    MaintenanceCategory.GENERAL_INSPECTION: (365, 15_000.0),
}
EXAMPLE_NOTE: Final = (
    "Example interval only — not a manufacturer-approved schedule. Replace it with the "
    "recommendation in the vehicle's service documentation."
)


@dataclass(frozen=True, slots=True)
class Odometer:
    km: float | None
    recorded_at: datetime | None

    def is_current(self, today: date, stale_days: int) -> bool:
        if self.km is None or self.recorded_at is None:
            return False
        return (today - self.recorded_at.date()).days <= stale_days


def evaluate_schedule(
    schedule: ScheduleView,
    *,
    baseline_date: date | None,
    baseline_km: float | None,
    odometer: Odometer,
    today: date,
    odometer_stale_days: int,
) -> ScheduleStatus:
    """Status of one schedule: the worse of its date and distance parts ("whichever first")."""
    notes: list[str] = []
    if schedule.interval_source == "example":
        notes.append(EXAMPLE_NOTE)
    if not schedule.is_active:
        return ScheduleStatus(
            schedule=schedule,
            state=ScheduleState.NOT_SCHEDULED,
            due_date=None,
            due_km=None,
            days_remaining=None,
            km_remaining=None,
            baseline_date=baseline_date,
            baseline_km=baseline_km,
            notes=(*notes, "Schedule is paused."),
        )
    states: list[ScheduleState] = []
    due_date = days_remaining = None
    if schedule.interval_days is not None:
        if baseline_date is None:
            notes.append("No completed service date recorded for this schedule.")
        else:
            due_date = baseline_date + timedelta(days=schedule.interval_days)
            days_remaining = (due_date - today).days
            states.append(_state(days_remaining, DUE_WINDOW_DAYS, schedule.reminder_days_before))
    due_km = km_remaining = None
    if schedule.interval_km is not None:
        if baseline_km is None:
            notes.append("No odometer reading recorded for the last service.")
        else:
            due_km = baseline_km + schedule.interval_km
        if (
            due_km is not None
            and odometer.km is not None
            and odometer.is_current(today, odometer_stale_days)
        ):
            km_remaining = round(due_km - odometer.km, 1)
            states.append(_state(km_remaining, DUE_WINDOW_KM, schedule.reminder_km_before))
        else:
            if due_km is not None and (odometer.km is None or odometer.recorded_at is None):
                notes.append("No current odometer reading is available.")
            elif due_km is not None and odometer.recorded_at is not None:
                notes.append(
                    f"The last odometer reading ({odometer.km:,.0f} km, "
                    f"{odometer.recorded_at.date().isoformat()}) is too old to judge the "
                    "distance interval."
                )
            states.append(ScheduleState.INSUFFICIENT_MILEAGE)
    decided = [st for st in states if st is not ScheduleState.INSUFFICIENT_MILEAGE]
    state: ScheduleState
    if decided:
        state = max(decided, key=lambda st: st.rank)
    elif states and schedule.interval_days is None:
        state = ScheduleState.INSUFFICIENT_MILEAGE
    else:
        state = ScheduleState.NOT_SCHEDULED
    return ScheduleStatus(
        schedule=schedule,
        state=state,
        due_date=due_date,
        due_km=due_km,
        days_remaining=days_remaining,
        km_remaining=km_remaining,
        baseline_date=baseline_date,
        baseline_km=baseline_km,
        notes=tuple(notes),
    )


def _state(remaining: float, due_window: float, reminder_window: float) -> ScheduleState:
    if remaining < 0:
        return ScheduleState.OVERDUE
    if remaining <= due_window:
        return ScheduleState.DUE
    if remaining <= max(reminder_window, due_window):
        return ScheduleState.UPCOMING
    return ScheduleState.UP_TO_DATE


@dataclass(frozen=True, slots=True)
class CostSummary:
    currency: str
    total: Decimal
    by_month: dict[str, Decimal]
    by_year: dict[str, Decimal]
    by_category: dict[str, Decimal]
    record_count: int


@dataclass(frozen=True, slots=True)
class Observation:
    title: str
    detail: str
    evidence: str
    category: MaintenanceCategory | None = None


class MaintenanceService:
    def __init__(self, database: Database) -> None:
        self._db = database

    # -- records --------------------------------------------------------------------------------

    def add_record(self, vehicle_id: int, data: MaintenanceRecordInput) -> MaintenanceRecordView:
        with self._db.session() as session:
            vehicle = self._vehicle(session, vehicle_id)
            if data.schedule_id is not None:
                self._schedule(session, vehicle_id, data.schedule_id)
            record = MaintenanceRecord(vehicle_id=vehicle_id, **self._values(data))
            session.add(record)
            session.flush()
            self._after_change(session, vehicle, record)
            return MaintenanceRecordView.model_validate(record)

    def update_record(
        self, vehicle_id: int, record_id: int, data: MaintenanceRecordInput
    ) -> MaintenanceRecordView:
        with self._db.session() as session:
            vehicle = self._vehicle(session, vehicle_id)
            record = self._record(session, vehicle_id, record_id)
            if data.schedule_id is not None:
                self._schedule(session, vehicle_id, data.schedule_id)
            for key, value in self._values(data).items():
                setattr(record, key, value)
            session.flush()
            self._after_change(session, vehicle, record)
            return MaintenanceRecordView.model_validate(record)

    def delete_record(self, vehicle_id: int, record_id: int) -> None:
        with self._db.session() as session:
            session.delete(self._record(session, vehicle_id, record_id))

    def records(
        self,
        vehicle_id: int,
        *,
        category: str | None = None,
        status: MaintenanceStatus | None = None,
        search: str = "",
        start: date | None = None,
        end: date | None = None,
    ) -> list[MaintenanceRecordView]:
        stmt = (
            select(MaintenanceRecord)
            .where(MaintenanceRecord.vehicle_id == vehicle_id)
            .order_by(MaintenanceRecord.service_date.desc(), MaintenanceRecord.id.desc())
        )
        if category:
            stmt = stmt.where(MaintenanceRecord.category == category)
        if status is not None:
            stmt = stmt.where(MaintenanceRecord.status == status)
        if start is not None:
            stmt = stmt.where(MaintenanceRecord.service_date >= start)
        if end is not None:
            stmt = stmt.where(MaintenanceRecord.service_date <= end)
        text = search.strip()
        if text:
            pattern = f"%{text}%"
            stmt = stmt.where(
                MaintenanceRecord.title.ilike(pattern)
                | MaintenanceRecord.provider.ilike(pattern)
                | MaintenanceRecord.notes.ilike(pattern)
            )
        with self._db.session() as session:
            return [MaintenanceRecordView.model_validate(r) for r in session.scalars(stmt)]

    @staticmethod
    def _values(data: MaintenanceRecordInput) -> dict[str, object]:
        completed = data.status is MaintenanceStatus.COMPLETED
        return {
            "category": data.category.value,
            "title": data.title,
            "status": data.status,
            "service_date": data.service_date,
            "mileage_km": data.mileage_km,
            "provider": data.provider,
            "cost": data.cost,
            "currency": data.currency,
            "notes": data.notes,
            "next_due_date": data.next_due_date,
            "next_due_km": data.next_due_km,
            "schedule_id": data.schedule_id,
            "completed_at": utc_now() if completed else None,
        }

    def _after_change(
        self, session: Session, vehicle: VehicleRecord, record: MaintenanceRecord
    ) -> None:
        if record.status is not MaintenanceStatus.COMPLETED:
            return
        if record.mileage_km is not None and record.service_date is not None:
            recorded = datetime.combine(record.service_date, datetime.min.time(), tzinfo=UTC)
            newer = vehicle.mileage_updated_at is None or recorded >= vehicle.mileage_updated_at
            if newer and record.mileage_km >= (vehicle.mileage_km or 0):
                vehicle.mileage_km = record.mileage_km
                vehicle.mileage_updated_at = recorded

    # -- odometer -------------------------------------------------------------------------------

    def record_odometer(self, vehicle_id: int, km: float, *, when: datetime | None = None) -> None:
        if not 0 <= km <= 5_000_000:
            raise DataValidationError(
                f"Odometer {km} out of range", user_message="Enter a valid odometer reading."
            )
        with self._db.session() as session:
            vehicle = self._vehicle(session, vehicle_id)
            vehicle.mileage_km = km
            vehicle.mileage_updated_at = when or utc_now()

    def odometer(self, vehicle_id: int) -> Odometer:
        with self._db.session() as session:
            vehicle = self._vehicle(session, vehicle_id)
            recorded = vehicle.mileage_updated_at
            km = vehicle.mileage_km if recorded is not None else None
            return Odometer(km, recorded)

    # -- schedules ------------------------------------------------------------------------------

    def add_schedule(self, vehicle_id: int, data: ScheduleInput) -> ScheduleView:
        with self._db.session() as session:
            self._vehicle(session, vehicle_id)
            record = MaintenanceScheduleRecord(vehicle_id=vehicle_id, **self._schedule_values(data))
            session.add(record)
            session.flush()
            return ScheduleView.model_validate(record)

    def update_schedule(
        self, vehicle_id: int, schedule_id: int, data: ScheduleInput
    ) -> ScheduleView:
        with self._db.session() as session:
            record = self._schedule(session, vehicle_id, schedule_id)
            for key, value in self._schedule_values(data).items():
                setattr(record, key, value)
            session.flush()
            return ScheduleView.model_validate(record)

    def delete_schedule(self, vehicle_id: int, schedule_id: int) -> None:
        """Delete a schedule. Its completed records are kept and simply lose the link."""
        with self._db.session() as session:
            session.delete(self._schedule(session, vehicle_id, schedule_id))

    def schedules(self, vehicle_id: int) -> list[ScheduleView]:
        stmt = (
            select(MaintenanceScheduleRecord)
            .where(MaintenanceScheduleRecord.vehicle_id == vehicle_id)
            .order_by(MaintenanceScheduleRecord.task_name)
        )
        with self._db.session() as session:
            return [ScheduleView.model_validate(r) for r in session.scalars(stmt)]

    @staticmethod
    def _schedule_values(data: ScheduleInput) -> dict[str, object]:
        return {
            "category": data.category.value,
            "task_name": data.task_name,
            "interval_days": data.interval_days,
            "interval_km": data.interval_km,
            "last_done_date": data.last_done_date,
            "last_done_mileage_km": data.last_done_mileage_km,
            "reminder_days_before": data.reminder_days_before,
            "reminder_km_before": data.reminder_km_before,
            "interval_source": data.interval_source,
            "notes": data.notes,
            "is_active": data.is_active,
        }

    def statuses(
        self, vehicle_id: int, *, today: date | None = None, odometer_stale_days: int = 60
    ) -> list[ScheduleStatus]:
        today = today or date.today()
        odometer = self.odometer(vehicle_id)
        results: list[ScheduleStatus] = []
        with self._db.session() as session:
            schedules = list(
                session.scalars(
                    select(MaintenanceScheduleRecord).where(
                        MaintenanceScheduleRecord.vehicle_id == vehicle_id
                    )
                )
            )
            completed = list(
                session.scalars(
                    select(MaintenanceRecord)
                    .where(
                        MaintenanceRecord.vehicle_id == vehicle_id,
                        MaintenanceRecord.status == MaintenanceStatus.COMPLETED,
                    )
                    .order_by(MaintenanceRecord.service_date.desc())
                )
            )
            for record in schedules:
                view = ScheduleView.model_validate(record)
                linked = [
                    r
                    for r in completed
                    if r.schedule_id == record.id
                    or (r.schedule_id is None and r.category == record.category != "custom")
                ]
                baseline_date = record.last_done_date
                baseline_km = record.last_done_mileage_km
                for r in linked:  # newest first
                    if r.service_date and (
                        baseline_date is None or r.service_date >= baseline_date
                    ):
                        baseline_date = r.service_date
                        if r.mileage_km is not None:
                            baseline_km = r.mileage_km
                        break
                results.append(
                    evaluate_schedule(
                        view,
                        baseline_date=baseline_date,
                        baseline_km=baseline_km,
                        odometer=odometer,
                        today=today,
                        odometer_stale_days=odometer_stale_days,
                    )
                )
        results.sort(key=lambda s: (-s.state.rank, s.schedule.task_name))
        return results

    # -- costs ----------------------------------------------------------------------------------

    def cost_summary(self, vehicle_id: int) -> list[CostSummary]:
        totals: dict[str, Decimal] = defaultdict(Decimal)
        months: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        years: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        categories: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        counts: dict[str, int] = defaultdict(int)
        for record in self.records(vehicle_id, status=MaintenanceStatus.COMPLETED):
            if record.cost is None or record.currency is None:
                continue
            currency = record.currency
            totals[currency] += record.cost
            counts[currency] += 1
            if record.service_date is not None:
                months[currency][record.service_date.strftime("%Y-%m")] += record.cost
                years[currency][str(record.service_date.year)] += record.cost
            categories[currency][record.category] += record.cost
        return [
            CostSummary(
                currency=currency,
                total=totals[currency],
                by_month=dict(sorted(months[currency].items())),
                by_year=dict(sorted(years[currency].items())),
                by_category=dict(sorted(categories[currency].items(), key=lambda kv: -kv[1])),
                record_count=counts[currency],
            )
            for currency in sorted(totals)
        ]

    # -- observations ---------------------------------------------------------------------------

    def observations(self, vehicle_id: int, *, days: int = 30) -> tuple[list[Observation], str]:
        """Cautious, evidence-backed prompts for inspection planning.

        Returns the observations and a sentence describing the evidence considered. No
        remaining-life or failure-date prediction is made.
        """
        since = utc_now() - timedelta(days=days)
        observations: list[Observation] = []
        with self._db.session() as session:
            assessments = list(
                session.execute(
                    select(
                        DiagnosticAssessmentRecord.created_at,
                        DiagnosticAssessmentRecord.health_score,
                    )
                    .where(
                        DiagnosticAssessmentRecord.vehicle_id == vehicle_id,
                        DiagnosticAssessmentRecord.created_at >= since,
                    )
                    .order_by(DiagnosticAssessmentRecord.created_at)
                )
            )
            findings = list(
                session.scalars(
                    select(DiagnosticResultRecord).where(
                        DiagnosticResultRecord.vehicle_id == vehicle_id,
                        DiagnosticResultRecord.created_at >= since,
                        DiagnosticResultRecord.severity.in_((Severity.WARNING, Severity.CRITICAL)),
                    )
                )
            )
            anomalies = sum(1 for f in findings if f.source is DiagnosticSource.ANOMALY_DETECTOR)
            codes = list(
                session.scalars(
                    select(DiagnosticTroubleCodeRecord).where(
                        DiagnosticTroubleCodeRecord.vehicle_id == vehicle_id,
                        DiagnosticTroubleCodeRecord.is_active.is_(True),
                        DiagnosticTroubleCodeRecord.status == DtcStatus.STORED,
                    )
                )
            )
        by_category: dict[str, list[DiagnosticResultRecord]] = defaultdict(list)
        for finding in findings:
            if finding.source is DiagnosticSource.RULE:
                by_category[finding.category.value].append(finding)
        for category, items in sorted(by_category.items()):
            sessions = {f.session_id for f in items if f.session_id is not None}
            if len(items) >= 3 and len(sessions) >= 2:
                observations.append(
                    Observation(
                        title=f"Repeated {category} warnings",
                        detail=(
                            "Rule-based warnings in this area recurred across several drives. "
                            "Consider asking a technician to inspect it at the next service."
                        ),
                        evidence=f"{len(items)} findings in {len(sessions)} recorded trips, "
                        f"last {days} days.",
                        category=_category_for(category),
                    )
                )
        if anomalies >= 5:
            observations.append(
                Observation(
                    title="Repeated unusual telemetry",
                    detail=(
                        "The experimental anomaly detector flagged unusual patterns repeatedly. "
                        "This is not a fault diagnosis; it may be worth mentioning at the next "
                        "inspection."
                    ),
                    evidence=f"{anomalies} anomaly findings in the last {days} days.",
                )
            )
        scores = [score for _, score in assessments if score is not None]
        if len(scores) >= 20:
            half = len(scores) // 2
            early = sum(scores[:half]) / half
            late = sum(scores[half:]) / (len(scores) - half)
            if early - late >= 10:
                observations.append(
                    Observation(
                        title="Experimental health score has declined",
                        detail=(
                            "The experimental score is lower than earlier in the period. It is "
                            "derived from simulated-data models and rules, so treat it only as a "
                            "prompt to review recent findings."
                        ),
                        evidence=f"Average {early:.0f} → {late:.0f} over {len(scores)} analyses.",
                    )
                )
        if codes:
            observations.append(
                Observation(
                    title="Stored trouble codes are present",
                    detail=(
                        "The vehicle reported stored trouble codes. Have them diagnosed; a code "
                        "alone does not identify a failed part."
                    ),
                    evidence=", ".join(sorted({c.code for c in codes})),
                    category=MaintenanceCategory.GENERAL_INSPECTION,
                )
            )
        evidence = (
            f"Considered {len(assessments)} analyses, {len(findings)} warning or critical "
            f"findings and {len(codes)} stored codes from the last {days} days."
        )
        return observations, evidence

    # -- helpers --------------------------------------------------------------------------------

    @staticmethod
    def _vehicle(session: Session, vehicle_id: int) -> VehicleRecord:
        record = session.get(VehicleRecord, vehicle_id)
        if record is None:
            raise RecordNotFoundError(f"Vehicle {vehicle_id} does not exist.")
        return record

    @staticmethod
    def _record(session: Session, vehicle_id: int, record_id: int) -> MaintenanceRecord:
        record = session.get(MaintenanceRecord, record_id)
        if record is None or record.vehicle_id != vehicle_id:
            raise RecordNotFoundError(f"Maintenance record {record_id} does not exist.")
        return record

    @staticmethod
    def _schedule(session: Session, vehicle_id: int, schedule_id: int) -> MaintenanceScheduleRecord:
        record = session.get(MaintenanceScheduleRecord, schedule_id)
        if record is None or record.vehicle_id != vehicle_id:
            raise RecordNotFoundError(f"Maintenance schedule {schedule_id} does not exist.")
        return record


_CATEGORY_HINTS: Final = {
    "cooling": MaintenanceCategory.COOLANT,
    "electrical": MaintenanceCategory.BATTERY,
    "lubrication": MaintenanceCategory.ENGINE_OIL,
}


def _category_for(fault_category: str) -> MaintenanceCategory | None:
    return _CATEGORY_HINTS.get(fault_category)
