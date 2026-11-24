from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from smartdrive.config.constants import DataSource, FuelType
from smartdrive.database.connection import Database
from smartdrive.database.models import TelemetryReadingRecord
from smartdrive.database.repositories import (
    DrivingSessionRepository,
    TelemetryRepository,
    VehicleRepository,
)
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError
from tests.conftest import FIXED_START, make_samples

pytestmark = pytest.mark.integration


class TestVehicleRepository:
    def test_add_get_update(self, database: Database, vehicle_profile: VehicleProfile) -> None:
        with database.session() as session:
            repo = VehicleRepository(session)
            created = repo.add(vehicle_profile)
            assert created.id > 0
            assert created.created_at.tzinfo is not None
            updated = repo.update(
                created.id, vehicle_profile.model_copy(update={"mileage_km": 90_000})
            )
        assert updated.mileage_km == 90_000
        with database.session() as session:
            assert VehicleRepository(session).get(created.id).mileage_km == 90_000

    def test_search_and_filter(self, database: Database, vehicle_profile: VehicleProfile) -> None:
        with database.session() as session:
            repo = VehicleRepository(session)
            repo.add(vehicle_profile)
            repo.add(
                vehicle_profile.model_copy(
                    update={
                        "name": "Work Van",
                        "manufacturer": "Nissan",
                        "vin": None,
                        "fuel_type": FuelType.DIESEL,
                    }
                )
            )
            assert [v.name for v in repo.list_vehicles(search="nissan")] == ["Work Van"]
            assert [v.name for v in repo.list_vehicles(fuel_type=FuelType.HYBRID)] == [
                "Daily Driver"
            ]
            assert len(repo.list_vehicles(search="  ")) == 2

    def test_duplicate_vin_is_a_validation_error(
        self, database: Database, vehicle_profile: VehicleProfile
    ) -> None:
        with database.session() as session:
            VehicleRepository(session).add(vehicle_profile)
        with pytest.raises(DataValidationError, match="VIN"), database.session() as session:
            VehicleRepository(session).add(vehicle_profile.model_copy(update={"name": "Copy"}))

    def test_only_one_active_vehicle(
        self, database: Database, vehicle_profile: VehicleProfile
    ) -> None:
        with database.session() as session:
            repo = VehicleRepository(session)
            first = repo.add(vehicle_profile)
            second = repo.add(vehicle_profile.model_copy(update={"name": "Second", "vin": None}))
            repo.set_active(first.id)
            repo.set_active(second.id)
            active = repo.get_active()
        assert active is not None
        assert active.id == second.id

    def test_remove_identifiers(self, database: Database, vehicle_profile: VehicleProfile) -> None:
        with database.session() as session:
            repo = VehicleRepository(session)
            vehicle = repo.remove_identifiers(repo.add(vehicle_profile).id)
        assert vehicle.vin is None
        assert vehicle.registration_number is None

    def test_delete_cascades_to_sessions_and_telemetry(
        self, database: Database, vehicle_profile: VehicleProfile
    ) -> None:
        with database.session() as session:
            vehicle = VehicleRepository(session).add(vehicle_profile)
            trip = DrivingSessionRepository(session).start(
                vehicle.id, DataSource.SIMULATION, started_at=FIXED_START
            )
            TelemetryRepository(session).add_batch(trip.id, make_samples(10))
        with database.session() as session:
            VehicleRepository(session).delete(vehicle.id)
        with database.session() as session:
            assert session.scalar(select(func.count(TelemetryReadingRecord.id))) == 0
            with pytest.raises(RecordNotFoundError):
                VehicleRepository(session).get(vehicle.id)

    def test_delete_missing_vehicle_raises(self, database: Database) -> None:
        with pytest.raises(RecordNotFoundError), database.session() as session:
            VehicleRepository(session).delete(12345)


class TestSessionsAndTelemetry:
    @pytest.fixture
    def vehicle_id(self, database: Database, vehicle_profile: VehicleProfile) -> int:
        with database.session() as session:
            return VehicleRepository(session).add(vehicle_profile).id

    def test_batch_insert_and_ordered_read_back(self, database: Database, vehicle_id: int) -> None:
        samples = make_samples(5_000)
        with database.session() as session:
            trip = DrivingSessionRepository(session).start(
                vehicle_id,
                DataSource.SIMULATION,
                scenario="urban",
                random_seed=42,
                started_at=FIXED_START,
            )
            assert TelemetryRepository(session).add_batch(trip.id, samples) == 5_000
        with database.session() as session:
            repo = TelemetryRepository(session)
            assert repo.count(trip.id) == 5_000
            window = repo.for_session(trip.id, start=FIXED_START + timedelta(seconds=10), limit=3)
        assert [s.timestamp for s in window] == [s.timestamp for s in samples[10:13]]
        assert window[0] == samples[10]
        assert window[0].oil_pressure_kpa is None

    def test_closed_session_rejects_new_telemetry(
        self, database: Database, vehicle_id: int
    ) -> None:
        with database.session() as session:
            sessions = DrivingSessionRepository(session)
            trip = sessions.start(vehicle_id, DataSource.LIVE, started_at=FIXED_START)
            sessions.end(trip.id, ended_at=FIXED_START + timedelta(minutes=5))
            with pytest.raises(DataValidationError):
                TelemetryRepository(session).add_batch(trip.id, make_samples(1))

    def test_session_cannot_end_before_start(self, database: Database, vehicle_id: int) -> None:
        with database.session() as session:
            sessions = DrivingSessionRepository(session)
            trip = sessions.start(vehicle_id, DataSource.LIVE, started_at=FIXED_START)
            with pytest.raises(DataValidationError):
                sessions.end(trip.id, ended_at=FIXED_START - timedelta(seconds=1))

    def test_replay_sessions_must_reference_a_recording(
        self, database: Database, vehicle_id: int
    ) -> None:
        with database.session() as session:
            sessions = DrivingSessionRepository(session)
            with pytest.raises(DataValidationError):
                sessions.start(vehicle_id, DataSource.REPLAY)
            recorded = sessions.start(vehicle_id, DataSource.LIVE, started_at=FIXED_START)
            with pytest.raises(DataValidationError):
                sessions.start(vehicle_id, DataSource.LIVE, replay_of_session_id=recorded.id)
            replay = sessions.start(vehicle_id, DataSource.REPLAY, replay_of_session_id=recorded.id)
            assert sessions.list_for_vehicle(vehicle_id, data_source=DataSource.REPLAY) == [replay]

    def test_retention_purges_only_old_finished_sessions(
        self, database: Database, vehicle_id: int
    ) -> None:
        with database.session() as session:
            sessions = DrivingSessionRepository(session)
            old = sessions.start(vehicle_id, DataSource.LIVE, started_at=FIXED_START)
            TelemetryRepository(session).add_batch(old.id, make_samples(3))
            sessions.end(old.id, ended_at=FIXED_START + timedelta(minutes=1))
            sessions.start(vehicle_id, DataSource.LIVE, started_at=FIXED_START)  # still open
            recent = sessions.start(
                vehicle_id, DataSource.LIVE, started_at=FIXED_START + timedelta(days=30)
            )
            sessions.end(recent.id, ended_at=FIXED_START + timedelta(days=30, minutes=1))
        with database.session() as session:
            removed = TelemetryRepository(session).purge_sessions_before(
                FIXED_START + timedelta(days=1)
            )
            remaining = DrivingSessionRepository(session).list_for_vehicle(vehicle_id)
            telemetry = session.scalar(select(func.count(TelemetryReadingRecord.id)))
        assert removed == 1
        assert len(remaining) == 2
        assert telemetry == 0
