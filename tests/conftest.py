from __future__ import annotations

import os

# Qt must run headless in tests; set before any QApplication exists. Override to watch locally.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from smartdrive.config.constants import HOME_ENV_VAR, FuelType, TransmissionType
from smartdrive.database.connection import Database
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.utils.logger import shutdown_logging

FIXED_START = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Never let a test touch the real per-user data folder."""
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path / "smartdrive-home"))
    yield
    shutdown_logging()


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(tmp_path / "test.db")
    db.upgrade()
    yield db
    db.dispose()


@pytest.fixture
def vehicle_profile() -> VehicleProfile:
    return VehicleProfile(
        name="Daily Driver",
        manufacturer="Toyota",
        model="Axio",
        year=2016,
        fuel_type=FuelType.HYBRID,
        transmission=TransmissionType.CVT,
        engine_capacity_cc=1500,
        mileage_km=82_000,
        vin="JTDBR32E720123456",
        registration_number="cab-1234",
    )


def make_samples(count: int, *, start: datetime = FIXED_START) -> list[TelemetrySample]:
    return [
        TelemetrySample(
            timestamp=start + timedelta(seconds=i),
            coolant_temp_c=70 + (i % 20),
            rpm=800 + (i % 50) * 40,
            speed_kph=float(i % 120),
            fuel_level_pct=60.0,
            oil_pressure_kpa=None,
        )
        for i in range(count)
    ]
