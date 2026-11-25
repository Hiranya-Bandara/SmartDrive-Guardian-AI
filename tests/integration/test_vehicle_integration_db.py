"""Migration 0003 on existing data, cascades, transaction rollback and backup of new tables."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select

from smartdrive.app import backup_before_upgrade
from smartdrive.config.constants import (
    DataSource,
    NotificationCategory,
    NotificationSeverity,
    SessionStatus,
)
from smartdrive.config.settings import DiagnosticThresholds
from smartdrive.database.connection import Database
from smartdrive.database.models import (
    DiagnosticTroubleCodeRecord,
    DrivingSessionRecord,
    DtcScanRecord,
    MaintenanceRecord,
    MaintenanceScheduleRecord,
    NotificationRecord,
    ObdConnectionRecord,
    TelemetryReadingRecord,
    TripEventRecord,
    TripSummaryRecord,
    VehicleRecord,
    VehicleThresholdRecord,
)
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.obd.mock import MOCK_PORT, PROFILES, MockElm327Transport
from smartdrive.obd.session import ConnectionParameters, ObdSession
from smartdrive.services.notification_service import NotificationService
from smartdrive.services.obd_service import ObdHistoryService
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.threshold_service import ThresholdService
from smartdrive.services.trip_service import TripService
from smartdrive.services.vehicle_service import VehicleService
from smartdrive.utils.exceptions import DatabaseError

pytestmark = pytest.mark.integration

PHASE4_TABLES = {
    "obd_connections",
    "dtc_scans",
    "trip_events",
    "trip_summaries",
    "notifications",
    "vehicle_thresholds",
}


def test_upgrade_from_phase_3_preserves_records(tmp_path: Path) -> None:
    db = Database(tmp_path / "phase3.db")
    db.upgrade("0002")
    with closing(sqlite3.connect(db.path)) as conn:
        conn.execute(
            "INSERT INTO vehicles (name, manufacturer, model, year, fuel_type, transmission,"
            " mileage_km, notes, is_active, created_at, updated_at) VALUES"
            " ('Old car','Make','Model',2015,'petrol','manual',61000,'',1,"
            "'2026-01-01 00:00:00','2026-01-01 00:00:00')"
        )
        conn.execute(
            "INSERT INTO driving_sessions (vehicle_id, data_source, started_at, ended_at,"
            " distance_estimated, notes) VALUES"
            " (1,'simulation','2026-01-02 08:00:00','2026-01-02 08:30:00',1,'')"
        )
        # Children of rebuilt tables: a table rebuild with foreign keys on would cascade-delete
        # these (regression test for a data-loss bug found during Phase 4 development).
        conn.executemany(
            "INSERT INTO telemetry_readings (session_id, timestamp, rpm, fuel_rate_estimated,"
            " extra) VALUES (1, ?, 900, 0, '{}')",
            [(f"2026-01-02 08:00:{s:02d}",) for s in range(30)],
        )
        conn.execute(
            "INSERT INTO diagnostic_trouble_codes (vehicle_id, session_id, code, description,"
            " status, first_seen_at, last_seen_at) VALUES (1, 1, 'P0217', 'Over-temperature',"
            " 'stored', '2026-01-02 08:00:00', '2026-01-02 08:00:00')"
        )
        conn.execute(
            "INSERT INTO maintenance_records (vehicle_id, title, status, notes, created_at,"
            " updated_at) VALUES (1,'Old service','completed','', '2026-01-03 00:00:00',"
            " '2026-01-03 00:00:00')"
        )
        conn.execute(
            "INSERT INTO maintenance_schedules (vehicle_id, task_name, interval_days, is_active,"
            " created_at, updated_at) VALUES (1,'Oil',365,1,'2026-01-03 00:00:00',"
            " '2026-01-03 00:00:00')"
        )
        conn.commit()
    assert not PHASE4_TABLES & set(inspect(db.engine).get_table_names())
    db.upgrade()
    assert db.current_revision() == db.head_revision()
    assert set(inspect(db.engine).get_table_names()) >= PHASE4_TABLES
    with db.session() as s:
        (vehicle,) = s.scalars(select(VehicleRecord))
        (trip,) = s.scalars(select(DrivingSessionRecord))
        (record,) = s.scalars(select(MaintenanceRecord))
        (schedule,) = s.scalars(select(MaintenanceScheduleRecord))
        assert vehicle.mileage_km == 61000 and vehicle.mileage_updated_at is None
        assert trip.status is SessionStatus.COMPLETED and trip.name is None
        assert record.title == "Old service" and record.category
        assert schedule.task_name == "Oil" and schedule.interval_source == "user"
        assert s.scalar(select(func.count()).select_from(TelemetryReadingRecord)) == 30
        (code,) = s.scalars(select(DiagnosticTroubleCodeRecord))
        assert code.code == "P0217" and code.is_active
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    db.downgrade("0002")
    with closing(sqlite3.connect(db.path)) as conn:
        assert conn.execute("SELECT count(*) FROM vehicles").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM driving_sessions").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM telemetry_readings").fetchone() == (30,)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not PHASE4_TABLES & tables
    db.dispose()


@pytest.fixture
def populated(database: Database, vehicle_profile: VehicleProfile, tmp_path: Path) -> int:
    vehicle = VehicleService(database, tmp_path / "img").add(vehicle_profile)
    telemetry = TelemetryService(database)
    session = telemetry.start_session(vehicle.id, DataSource.SIMULATION)
    telemetry.append(
        session.id, [TelemetrySample(timestamp=datetime(2026, 1, 1, tzinfo=UTC), rpm=900.0)]
    )
    telemetry.end_session(session.id)
    trips = TripService(database, telemetry)
    trips.finalize(session.id)
    trips.mark_interrupted(session.id, "test")
    obd = ObdHistoryService(database)
    transport = MockElm327Transport(PROFILES["stored_codes"]())
    obd_session = ObdSession(
        ConnectionParameters(port=MOCK_PORT), transport_factory=lambda _p, _b: transport
    )
    report = obd_session.connect()
    connection_id = obd.record_connection(
        report, vehicle_id=vehicle.id, connection_method="Mock (no hardware)"
    )
    obd.record_scan(
        vehicle.id,
        obd_session.scan_trouble_codes(),
        data_source=DataSource.SIMULATION,
        is_mock=True,
        connection_id=connection_id,
        session_id=session.id,
    )
    obd_session.close()
    NotificationService(database).notify(
        NotificationSeverity.INFORMATION,
        NotificationCategory.TRIP,
        "Trip recorded",
        vehicle_id=vehicle.id,
    )
    ThresholdService(database).save(
        vehicle.id,
        {"coolant_warning_c": 100.0},
        source_note="Owner's manual",
        base=DiagnosticThresholds(),
    )
    return vehicle.id


def count(database: Database, model: type) -> int:
    with database.session() as s:
        return int(s.scalar(select(func.count()).select_from(model)) or 0)


def test_deleting_a_vehicle_removes_only_its_records(database: Database, populated: int) -> None:
    owned = (
        DrivingSessionRecord,
        TelemetryReadingRecord,
        TripSummaryRecord,
        TripEventRecord,
        DtcScanRecord,
        DiagnosticTroubleCodeRecord,
        VehicleThresholdRecord,
    )
    assert all(count(database, model) > 0 for model in owned)
    assert count(database, ObdConnectionRecord) == 1
    VehicleService(database, Path("unused")).delete(populated)
    assert all(count(database, model) == 0 for model in owned)
    # History that is not owned by the vehicle survives with the link cleared.
    with database.session() as s:
        (connection,) = s.scalars(select(ObdConnectionRecord))
        assert connection.vehicle_id is None
        notification = s.scalars(select(NotificationRecord)).one_or_none()
        assert notification is None or notification.vehicle_id is None


def test_failed_transaction_leaves_no_partial_changes(database: Database, populated: int) -> None:
    before = count(database, NotificationRecord)
    with pytest.raises(DatabaseError), database.session() as s:
        s.add(
            NotificationRecord(
                severity=NotificationSeverity.INFORMATION,
                category="trip",
                title="Valid",
                message="",
                dedup_key="ok",
                occurrence_count=1,
            )
        )
        s.flush()
        s.add(DtcScanRecord(vehicle_id=populated))  # missing required columns
    assert count(database, NotificationRecord) == before


def test_backup_and_restore_cover_phase_4_tables(
    database: Database, populated: int, tmp_path: Path
) -> None:
    backup = database.backup(tmp_path / "backup.db")
    with database.session() as s:
        s.execute(TripEventRecord.__table__.delete())
        s.execute(NotificationRecord.__table__.delete())
    assert count(database, TripEventRecord) == 0
    database.restore(backup, safety_backup_dir=tmp_path / "safety")
    assert count(database, TripEventRecord) > 0
    assert count(database, NotificationRecord) == 1
    assert count(database, DtcScanRecord) == 1


def test_existing_database_is_backed_up_before_an_upgrade(tmp_path: Path) -> None:
    db = Database(tmp_path / "old.db")
    db.upgrade("0002")
    backup = backup_before_upgrade(db, tmp_path / "backups")
    assert backup is not None and backup.name.startswith("smartdrive-pre-upgrade-0002-")
    restored = Database(backup)
    assert restored.current_revision() == "0002"
    restored.dispose()
    db.upgrade()
    assert backup_before_upgrade(db, tmp_path / "backups") is None  # already current
    fresh = Database(tmp_path / "new.db")
    assert backup_before_upgrade(fresh, tmp_path / "backups") is None  # nothing to protect
    db.dispose()
    fresh.dispose()
