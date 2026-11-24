from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from smartdrive.config.constants import DataSource, FuelType
from smartdrive.config.paths import AppPaths
from smartdrive.config.settings import AppSettings
from smartdrive.database.connection import Database
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.services.backup_service import BackupService
from smartdrive.services.telemetry_service import TelemetryService, estimate_distance_km
from smartdrive.services.vehicle_service import VehicleService
from smartdrive.utils.exceptions import DataValidationError
from tests.conftest import FIXED_START, make_samples

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture
def images_dir(tmp_path: Path) -> Path:
    return tmp_path / "images"


@pytest.fixture
def vehicles(database: Database, images_dir: Path) -> VehicleService:
    return VehicleService(database, images_dir)


@pytest.fixture
def telemetry(database: Database) -> TelemetryService:
    return TelemetryService(database)


class TestVehicleService:
    def test_crud_and_active_selection(
        self, vehicles: VehicleService, vehicle_profile: VehicleProfile
    ) -> None:
        car = vehicles.add(vehicle_profile)
        van = vehicles.add(
            vehicle_profile.model_copy(
                update={"name": "Van", "vin": None, "fuel_type": FuelType.DIESEL}
            )
        )
        assert [v.name for v in vehicles.list_vehicles(fuel_type=FuelType.DIESEL)] == ["Van"]
        vehicles.set_active(van.id)
        active = vehicles.get_active()
        assert active is not None and active.id == van.id
        updated = vehicles.update(car.id, vehicle_profile.model_copy(update={"mileage_km": 1.0}))
        assert updated.mileage_km == 1.0
        vehicles.delete(van.id)
        assert vehicles.get_active() is None
        assert vehicles.remove_identifiers(car.id).vin is None

    def test_image_import_copies_and_validates(
        self, vehicles: VehicleService, tmp_path: Path, images_dir: Path
    ) -> None:
        source = tmp_path / "car.PNG"
        source.write_bytes(PNG)
        name = vehicles.import_image(source)
        assert (images_dir / name).read_bytes() == PNG
        assert source.exists()
        jpeg = tmp_path / "photo.jpeg"
        jpeg.write_bytes(JPEG)
        assert vehicles.import_image(jpeg).endswith(".jpg")

    @pytest.mark.parametrize(
        ("filename", "content"),
        [("car.gif", PNG), ("fake.png", b"not an image at all"), ("empty.png", b"")],
    )
    def test_invalid_images_rejected(
        self, vehicles: VehicleService, tmp_path: Path, filename: str, content: bytes
    ) -> None:
        path = tmp_path / filename
        path.write_bytes(content)
        with pytest.raises(DataValidationError):
            vehicles.import_image(path)

    def test_replacing_and_deleting_images_cleans_up_files(
        self,
        vehicles: VehicleService,
        vehicle_profile: VehicleProfile,
        tmp_path: Path,
        images_dir: Path,
    ) -> None:
        source = tmp_path / "a.png"
        source.write_bytes(PNG)
        first = vehicles.import_image(source)
        car = vehicles.add(vehicle_profile.model_copy(update={"image_path": first}))
        assert vehicles.image_file(car) == (images_dir / first).resolve()
        second = vehicles.import_image(source)
        vehicles.update(car.id, vehicle_profile.model_copy(update={"image_path": second}))
        assert not (images_dir / first).exists()
        vehicles.delete(car.id)
        assert not (images_dir / second).exists()

    def test_image_resolution_cannot_escape_images_folder(
        self, vehicles: VehicleService, tmp_path: Path
    ) -> None:
        (tmp_path / "secret.png").write_bytes(PNG)
        assert vehicles.resolve_image("../secret.png") is None


class TestTelemetryService:
    def test_session_lifecycle_with_distance(
        self, vehicles: VehicleService, telemetry: TelemetryService, vehicle_profile: VehicleProfile
    ) -> None:
        car = vehicles.add(vehicle_profile)
        session = telemetry.start_session(
            car.id, DataSource.SIMULATION, scenario="urban", random_seed=5
        )
        samples = [
            TelemetrySample(timestamp=session.started_at + timedelta(seconds=i), speed_kph=36.0)
            for i in range(101)
        ]
        assert telemetry.append(session.id, samples) == 101
        ended = telemetry.end_session(session.id)
        assert ended.ended_at == samples[-1].timestamp
        assert ended.distance_km == pytest.approx(1.0)
        assert ended.distance_estimated
        (summary,) = telemetry.session_summaries(car.id)
        assert summary.sample_count == 101
        assert summary.session.scenario == "urban"

    def test_distance_estimation_does_not_bridge_gaps(self) -> None:
        start = FIXED_START
        samples = [
            TelemetrySample(timestamp=start, speed_kph=36.0),
            TelemetrySample(timestamp=start + timedelta(seconds=1), speed_kph=36.0),
            TelemetrySample(timestamp=start + timedelta(seconds=60), speed_kph=36.0),
            TelemetrySample(timestamp=start + timedelta(seconds=61), speed_kph=None),
        ]
        assert estimate_distance_km(samples) == pytest.approx(0.01)
        assert estimate_distance_km([TelemetrySample(timestamp=start)]) is None

    def test_orphaned_sessions_are_closed(
        self, vehicles: VehicleService, telemetry: TelemetryService, vehicle_profile: VehicleProfile
    ) -> None:
        car = vehicles.add(vehicle_profile)
        session = telemetry.start_session(car.id, DataSource.SIMULATION)
        telemetry.append(session.id, make_samples(5, start=session.started_at))
        empty = telemetry.start_session(car.id, DataSource.SIMULATION)
        assert telemetry.close_orphaned_sessions() == 2
        summaries = {s.session.id: s for s in telemetry.session_summaries(car.id)}
        assert summaries[session.id].session.ended_at is not None
        assert summaries[empty.id].session.ended_at == summaries[empty.id].session.started_at

    def test_recent_alerts_empty_without_diagnostic_engine(
        self, telemetry: TelemetryService
    ) -> None:
        assert telemetry.recent_alerts() == []


def test_backup_service_round_trip(
    database: Database, tmp_path: Path, vehicles: VehicleService, vehicle_profile: VehicleProfile
) -> None:
    paths = AppPaths.under(tmp_path / "home").ensure()
    service = BackupService(database, paths, AppSettings())
    backup = service.backup()
    assert backup.parent == paths.backup_dir
    vehicles.add(vehicle_profile)
    safety = service.restore(backup)
    assert vehicles.list_vehicles() == []
    assert safety.is_file()
    explicit = service.backup(tmp_path / "explicit.db")
    assert explicit.is_file()
