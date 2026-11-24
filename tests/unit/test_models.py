from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from smartdrive.config.constants import FuelType, TransmissionType
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.models.vehicle import VehicleProfile

BASE: dict[str, Any] = {
    "name": "Car",
    "manufacturer": "Honda",
    "model": "Fit",
    "year": 2015,
    "fuel_type": FuelType.PETROL,
    "transmission": TransmissionType.AUTOMATIC,
}


class TestVehicleProfile:
    def test_optional_identifiers_blank_become_none(self) -> None:
        profile = VehicleProfile(**BASE, vin="  ", registration_number="")
        assert profile.vin is None
        assert profile.registration_number is None

    def test_identifiers_normalised(self) -> None:
        profile = VehicleProfile(**BASE, vin="jhmgd38408s012345", registration_number="wp cab 1")
        assert profile.vin == "JHMGD38408S012345"
        assert profile.registration_number == "WP CAB 1"

    @pytest.mark.parametrize(
        "override",
        [
            {"name": ""},
            {"year": 1700},
            {"mileage_km": -1},
            {"engine_capacity_cc": 0},
            {"vin": "INVALIDVIN"},
            {"unexpected": True},
        ],
    )
    def test_invalid_input_rejected(self, override: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            VehicleProfile(**{**BASE, **override})

    def test_next_service_before_last_service_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VehicleProfile(
                **BASE, last_service_date=date(2026, 5, 1), next_service_date=date(2026, 1, 1)
            )

    def test_electric_vehicle_cannot_have_engine_capacity(self) -> None:
        with pytest.raises(ValidationError):
            VehicleProfile(**{**BASE, "fuel_type": FuelType.ELECTRIC, "engine_capacity_cc": 1000})


class TestTelemetrySample:
    def test_missing_sensors_stay_none(self) -> None:
        sample = TelemetrySample(timestamp=datetime.now(UTC), rpm=900)
        assert sample.coolant_temp_c is None
        assert sample.available_sensors() == ["rpm"]

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TelemetrySample(timestamp=datetime(2026, 1, 1))

    @pytest.mark.parametrize(
        "field_value", [("rpm", -1), ("fuel_level_pct", 101), ("coolant_temp_c", 300)]
    )
    def test_implausible_values_rejected(self, field_value: tuple[str, float]) -> None:
        field, value = field_value
        with pytest.raises(ValidationError):
            TelemetrySample.model_validate({"timestamp": datetime.now(UTC), field: value})

    def test_samples_are_immutable(self) -> None:
        sample = TelemetrySample(timestamp=datetime.now(UTC), rpm=900)
        with pytest.raises(ValidationError):
            sample.rpm = 1000  # type: ignore[misc]
