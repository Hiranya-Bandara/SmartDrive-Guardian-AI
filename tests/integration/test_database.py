from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from smartdrive.config.constants import DataSource, FuelType, MaintenanceStatus, TransmissionType
from smartdrive.database.connection import Database
from smartdrive.database.models import (
    DrivingSessionRecord,
    MaintenanceRecord,
    MaintenanceScheduleRecord,
    VehicleRecord,
)
from smartdrive.utils.exceptions import DatabaseError

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "alembic_version",
    "alerts",
    "app_settings",
    "diagnostic_results",
    "diagnostic_trouble_codes",
    "driving_sessions",
    "export_history",
    "maintenance_records",
    "maintenance_schedules",
    "model_metadata",
    "telemetry_readings",
    "vehicles",
}


def _vehicle(**overrides: object) -> VehicleRecord:
    values: dict[str, object] = {
        "name": "Test",
        "manufacturer": "Make",
        "model": "Model",
        "year": 2020,
        "fuel_type": FuelType.PETROL,
        "transmission": TransmissionType.MANUAL,
    }
    values.update(overrides)
    return VehicleRecord(**values)


def test_upgrade_creates_every_table(database: Database) -> None:
    assert set(inspect(database.engine).get_table_names()) == EXPECTED_TABLES
    assert database.current_revision() == database.head_revision()


def test_pragmas_enable_foreign_keys_and_wal(database: Database) -> None:
    with database.engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_foreign_keys_are_enforced(database: Database) -> None:
    with pytest.raises(DatabaseError), database.session() as session:
        session.add(
            DrivingSessionRecord(
                vehicle_id=999, data_source=DataSource.SIMULATION, started_at=datetime.now(UTC)
            )
        )


@pytest.mark.parametrize(
    "overrides", [{"year": 1500}, {"mileage_km": -10.0}, {"engine_capacity_cc": 0}]
)
def test_check_constraints_are_enforced(database: Database, overrides: dict[str, object]) -> None:
    with pytest.raises(DatabaseError), database.session() as session:
        session.add(_vehicle(**overrides))


def test_enum_columns_reject_unknown_values(database: Database) -> None:
    with (
        pytest.raises(IntegrityError, match="ck_vehicles_fuel_type"),
        database.engine.begin() as conn,
    ):
        conn.execute(
            text(
                "INSERT INTO vehicles (name, manufacturer, model, year, fuel_type, transmission,"
                " mileage_km, notes, is_active, created_at, updated_at) VALUES"
                " ('x','x','x',2020,'steam','manual',0,'',0,'2026-01-01','2026-01-01')"
            )
        )


def test_maintenance_schedule_requires_an_interval(database: Database) -> None:
    with database.session() as session:
        vehicle = _vehicle()
        session.add(vehicle)
        session.flush()
        vehicle_id = vehicle.id
    with pytest.raises(DatabaseError), database.session() as session:
        session.add(MaintenanceScheduleRecord(vehicle_id=vehicle_id, task_name="Oil change"))


def test_deleting_schedule_keeps_history_records(database: Database) -> None:
    with database.session() as session:
        vehicle = _vehicle()
        session.add(vehicle)
        session.flush()
        schedule = MaintenanceScheduleRecord(
            vehicle_id=vehicle.id, task_name="Oil change", interval_km=5000
        )
        session.add(schedule)
        session.flush()
        session.add(
            MaintenanceRecord(
                vehicle_id=vehicle.id,
                schedule_id=schedule.id,
                title="Oil change",
                status=MaintenanceStatus.COMPLETED,
            )
        )
        session.flush()
        session.delete(schedule)
    with database.session() as session:
        record = session.scalars(select(MaintenanceRecord)).one()
        assert record.schedule_id is None


def test_datetimes_round_trip_as_aware_utc(database: Database) -> None:
    colombo = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 3, 1, 9, 30, tzinfo=colombo)
    with database.session() as session:
        vehicle = _vehicle()
        session.add(vehicle)
        session.flush()
        session.add(
            DrivingSessionRecord(
                vehicle_id=vehicle.id, data_source=DataSource.LIVE, started_at=local
            )
        )
    with database.session() as session:
        stored = session.scalars(select(DrivingSessionRecord)).one().started_at
    assert stored.tzinfo is UTC
    assert stored == local


def test_naive_datetimes_are_refused(database: Database) -> None:
    with pytest.raises(DatabaseError, match="Naive"), database.session() as session:
        session.add(_vehicle(created_at=datetime(2026, 1, 1)))
        session.flush()
