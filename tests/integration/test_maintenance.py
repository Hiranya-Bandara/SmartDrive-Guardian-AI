"""Maintenance records, schedules, reminder states, odometer freshness, costs and observations."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartdrive.config.constants import (
    DataSource,
    DiagnosticSource,
    DtcStatus,
    FaultCategory,
    MaintenanceCategory,
    MaintenanceStatus,
    Severity,
)
from smartdrive.database.connection import Database
from smartdrive.database.models import DiagnosticResultRecord, DiagnosticTroubleCodeRecord
from smartdrive.models.maintenance import (
    MaintenanceRecordInput,
    ScheduleInput,
    ScheduleState,
    ScheduleStatus,
    ScheduleView,
)
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.services.maintenance_service import (
    EXAMPLE_NOTE,
    MaintenanceService,
    Odometer,
    evaluate_schedule,
)
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.vehicle_service import VehicleService
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError

pytestmark = pytest.mark.integration

TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


def schedule(**overrides: object) -> ScheduleView:
    values: dict[str, object] = {
        "id": 1,
        "vehicle_id": 1,
        "category": "engine_oil",
        "task_name": "Engine oil",
        "interval_days": None,
        "interval_km": None,
        "last_done_date": None,
        "last_done_mileage_km": None,
        "reminder_days_before": 14,
        "reminder_km_before": 500.0,
        "interval_source": "user",
        "notes": "",
        "is_active": True,
    }
    values.update(overrides)
    return ScheduleView(**values)  # type: ignore[arg-type]


def evaluate(
    view: ScheduleView, *, done: date | None, km: float | None, odometer: Odometer
) -> ScheduleStatus:
    return evaluate_schedule(
        view,
        baseline_date=done,
        baseline_km=km,
        odometer=odometer,
        today=TODAY,
        odometer_stale_days=60,
    )


CURRENT_ODO = Odometer(50_000.0, NOW - timedelta(days=3))


class TestScheduleEvaluation:
    @pytest.mark.parametrize(
        ("days_ago", "expected"),
        [
            (100, ScheduleState.UP_TO_DATE),
            (170, ScheduleState.UPCOMING),  # 10 days left, reminder window 14
            (178, ScheduleState.DUE),  # 2 days left, inside the 7-day due window
            (190, ScheduleState.OVERDUE),
        ],
    )
    def test_date_based(self, days_ago: int, expected: ScheduleState) -> None:
        view = schedule(interval_days=180)
        status = evaluate(
            view, done=TODAY - timedelta(days=days_ago), km=None, odometer=Odometer(None, None)
        )
        assert status.state is expected
        assert status.due_date == TODAY - timedelta(days=days_ago) + timedelta(days=180)

    @pytest.mark.parametrize(
        ("last_km", "expected"),
        [
            (45_000.0, ScheduleState.UP_TO_DATE),  # due at 55 000, 5 000 km left
            (40_300.0, ScheduleState.UPCOMING),  # 300 km left, reminder 500
            (40_100.0, ScheduleState.DUE),  # 100 km left
            (39_000.0, ScheduleState.OVERDUE),
        ],
    )
    def test_mileage_based(self, last_km: float, expected: ScheduleState) -> None:
        view = schedule(interval_km=10_000.0)
        status = evaluate(view, done=None, km=last_km, odometer=CURRENT_ODO)
        assert status.state is expected
        assert status.due_km == last_km + 10_000

    def test_combined_uses_whichever_comes_first(self) -> None:
        view = schedule(interval_days=365, interval_km=10_000.0)
        # Plenty of time left, but the distance is overdue.
        status = evaluate(view, done=TODAY - timedelta(days=30), km=39_000.0, odometer=CURRENT_ODO)
        assert status.state is ScheduleState.OVERDUE
        assert status.days_remaining == 335

    def test_missing_or_stale_odometer_is_insufficient_not_guessed(self) -> None:
        view = schedule(interval_km=10_000.0)
        missing = evaluate(view, done=None, km=45_000.0, odometer=Odometer(None, None))
        assert missing.state is ScheduleState.INSUFFICIENT_MILEAGE
        stale = evaluate(
            view, done=None, km=45_000.0, odometer=Odometer(54_900.0, NOW - timedelta(days=400))
        )
        assert stale.state is ScheduleState.INSUFFICIENT_MILEAGE
        assert stale.km_remaining is None
        assert any("too old" in n for n in stale.notes)
        # With a date part, the date still decides, and the distance part is noted.
        combined = evaluate(
            schedule(interval_days=365, interval_km=10_000.0),
            done=TODAY - timedelta(days=10),
            km=45_000.0,
            odometer=Odometer(None, None),
        )
        assert combined.state is ScheduleState.UP_TO_DATE

    def test_never_done_and_inactive_and_example_intervals(self) -> None:
        assert (
            evaluate(schedule(interval_days=180), done=None, km=None, odometer=CURRENT_ODO).state
            is ScheduleState.NOT_SCHEDULED
        )
        paused = evaluate(
            schedule(interval_days=180, is_active=False),
            done=TODAY - timedelta(days=500),
            km=None,
            odometer=CURRENT_ODO,
        )
        assert paused.state is ScheduleState.NOT_SCHEDULED
        example = evaluate(
            schedule(interval_days=180, interval_source="example"),
            done=TODAY,
            km=None,
            odometer=CURRENT_ODO,
        )
        assert EXAMPLE_NOTE in example.notes

    def test_a_schedule_needs_an_interval(self) -> None:
        with pytest.raises(ValidationError):
            ScheduleInput(task_name="Nothing")


@pytest.fixture
def service(database: Database) -> MaintenanceService:
    return MaintenanceService(database)


@pytest.fixture
def vehicle_id(database: Database, vehicle_profile: VehicleProfile, tmp_path: Path) -> int:
    return VehicleService(database, tmp_path / "img").add(vehicle_profile).id


def record(**overrides: object) -> MaintenanceRecordInput:
    values: dict[str, object] = {
        "category": MaintenanceCategory.ENGINE_OIL,
        "title": "Engine oil and filter",
        "service_date": date(2026, 6, 1),
        "mileage_km": 45_000.0,
        "provider": "Garage",
        "cost": Decimal("18500.00"),
        "currency": "LKR",
    }
    values.update(overrides)
    return MaintenanceRecordInput(**values)  # type: ignore[arg-type]


class TestMaintenanceService:
    def test_record_lifecycle(self, service: MaintenanceService, vehicle_id: int) -> None:
        created = service.add_record(vehicle_id, record(notes="private note"))
        assert created.cost == Decimal("18500.00")
        updated = service.update_record(vehicle_id, created.id, record(title="Oil change"))
        assert updated.title == "Oil change"
        assert [r.id for r in service.records(vehicle_id, search="oil change")] == [created.id]
        assert service.records(vehicle_id, category="coolant") == []
        service.delete_record(vehicle_id, created.id)
        assert service.records(vehicle_id) == []
        with pytest.raises(RecordNotFoundError):
            service.delete_record(vehicle_id, created.id)

    def test_record_validation(self) -> None:
        with pytest.raises(ValidationError, match="currency"):
            record(currency=None)
        with pytest.raises(ValidationError, match="service date"):
            record(service_date=None)
        with pytest.raises(ValidationError):
            record(next_due_date=date(2026, 1, 1))
        with pytest.raises(ValidationError):
            record(currency="rupees")

    def test_records_belong_to_their_vehicle(
        self,
        service: MaintenanceService,
        database: Database,
        vehicle_id: int,
        vehicle_profile: VehicleProfile,
        tmp_path: Path,
    ) -> None:
        other = VehicleService(database, tmp_path / "img2").add(
            vehicle_profile.model_copy(update={"name": "Other", "vin": None})
        )
        created = service.add_record(vehicle_id, record())
        with pytest.raises(RecordNotFoundError):
            service.update_record(other.id, created.id, record())

    def test_completed_record_resets_its_schedule(
        self, service: MaintenanceService, vehicle_id: int
    ) -> None:
        service.record_odometer(vehicle_id, 50_000, when=NOW - timedelta(days=1))
        oil = service.add_schedule(
            vehicle_id,
            ScheduleInput(
                category=MaintenanceCategory.ENGINE_OIL,
                task_name="Engine oil",
                interval_km=10_000,
                last_done_mileage_km=38_000,
                last_done_date=date(2025, 1, 1),
            ),
        )
        (before,) = service.statuses(vehicle_id, today=TODAY)
        assert before.state is ScheduleState.OVERDUE
        service.add_record(vehicle_id, record(schedule_id=oil.id))
        (after,) = service.statuses(vehicle_id, today=TODAY)
        assert after.baseline_km == 45_000
        assert after.state is ScheduleState.UP_TO_DATE

    def test_odometer_is_the_users_dated_reading(
        self, service: MaintenanceService, vehicle_id: int
    ) -> None:
        assert service.odometer(vehicle_id).km is None  # garage mileage alone has no date
        service.record_odometer(vehicle_id, 51_234, when=NOW)
        odometer = service.odometer(vehicle_id)
        assert odometer.km == 51_234 and odometer.recorded_at == NOW
        assert odometer.is_current(TODAY, 60)
        assert not odometer.is_current(TODAY + timedelta(days=90), 60)
        with pytest.raises(DataValidationError):
            service.record_odometer(vehicle_id, -5)

    def test_costs_are_never_summed_across_currencies(
        self, service: MaintenanceService, vehicle_id: int
    ) -> None:
        service.add_record(vehicle_id, record(cost=Decimal("10000"), service_date=date(2025, 3, 1)))
        service.add_record(
            vehicle_id, record(cost=Decimal("2500.50"), service_date=date(2026, 3, 1))
        )
        service.add_record(
            vehicle_id,
            record(
                cost=Decimal("40"),
                currency="USD",
                category=MaintenanceCategory.BATTERY,
                service_date=date(2026, 4, 1),
            ),
        )
        service.add_record(
            vehicle_id, record(cost=Decimal("999"), status=MaintenanceStatus.PLANNED)
        )
        service.add_record(vehicle_id, record(cost=None, currency=None))
        summaries = {s.currency: s for s in service.cost_summary(vehicle_id)}
        assert set(summaries) == {"LKR", "USD"}
        lkr = summaries["LKR"]
        assert lkr.total == Decimal("12500.50")
        assert lkr.record_count == 2
        assert lkr.by_year == {"2025": Decimal("10000"), "2026": Decimal("2500.50")}
        assert lkr.by_month["2026-03"] == Decimal("2500.50")
        assert summaries["USD"].by_category == {"battery": Decimal("40")}

    def test_schedule_deletion_keeps_records(
        self, service: MaintenanceService, vehicle_id: int
    ) -> None:
        oil = service.add_schedule(vehicle_id, ScheduleInput(task_name="Oil", interval_days=365))
        created = service.add_record(vehicle_id, record(schedule_id=oil.id))
        service.delete_schedule(vehicle_id, oil.id)
        (kept,) = service.records(vehicle_id)
        assert kept.id == created.id and kept.schedule_id is None

    def test_observations_need_evidence(
        self, service: MaintenanceService, database: Database, vehicle_id: int
    ) -> None:
        observations, basis = service.observations(vehicle_id)
        assert observations == []
        assert "Considered 0 analyses" in basis
        telemetry = TelemetryService(database)
        sessions = [telemetry.start_session(vehicle_id, DataSource.SIMULATION).id for _ in range(2)]
        now = datetime.now(UTC)
        with database.session() as s:
            for index in range(4):
                s.add(
                    DiagnosticResultRecord(
                        vehicle_id=vehicle_id,
                        session_id=sessions[index % 2],
                        created_at=now - timedelta(days=index),
                        category=FaultCategory.COOLING,
                        severity=Severity.WARNING,
                        source=DiagnosticSource.RULE,
                        summary="Coolant high",
                    )
                )
            s.add(
                DiagnosticTroubleCodeRecord(
                    vehicle_id=vehicle_id,
                    code="P0217",
                    status=DtcStatus.STORED,
                    description="Engine over-temperature condition",
                    first_seen_at=now,
                    last_seen_at=now,
                    is_active=True,
                )
            )
        observations, _ = service.observations(vehicle_id)
        titles = [o.title for o in observations]
        assert "Repeated cooling warnings" in titles
        assert "Stored trouble codes are present" in titles
        repeated = next(o for o in observations if o.title == "Repeated cooling warnings")
        assert repeated.category is MaintenanceCategory.COOLANT
        assert "4 findings in 2 recorded trips" in repeated.evidence
        assert all(
            "fail" not in o.detail.lower() or "not" in o.detail.lower() for o in observations
        )
