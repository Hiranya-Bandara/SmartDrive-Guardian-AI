"""Validated vehicle profile models exchanged between services, repositories and the UI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from smartdrive.config.constants import FuelType, TransmissionType
from smartdrive.utils.exceptions import DataValidationError
from smartdrive.utils.validators import (
    normalize_registration,
    normalize_vin,
    validate_model_year,
)


class VehicleProfile(BaseModel):
    """User-editable vehicle information. Identifiers are optional and removable."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    manufacturer: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    year: int
    fuel_type: FuelType
    transmission: TransmissionType
    engine_capacity_cc: int | None = Field(default=None, gt=0, le=20_000)
    mileage_km: float = Field(default=0.0, ge=0, le=5_000_000)
    registration_number: str | None = None
    vin: str | None = None
    purchase_date: date | None = None
    last_service_date: date | None = None
    next_service_date: date | None = None
    image_path: str | None = Field(default=None, max_length=1024)
    notes: str = Field(default="", max_length=4000)

    @field_validator("year")
    @classmethod
    def _check_year(cls, value: int) -> int:
        try:
            return validate_model_year(value)
        except DataValidationError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("vin")
    @classmethod
    def _check_vin(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return normalize_vin(value)
        except DataValidationError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("registration_number")
    @classmethod
    def _check_registration(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return normalize_registration(value)
        except DataValidationError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def _check_dates(self) -> Self:
        if (
            self.last_service_date
            and self.next_service_date
            and self.next_service_date < self.last_service_date
        ):
            raise ValueError("Next service date cannot be earlier than the last service date.")
        if self.fuel_type is FuelType.ELECTRIC and self.engine_capacity_cc is not None:
            raise ValueError("Electric vehicles do not have an engine capacity.")
        return self


class Vehicle(VehicleProfile):
    """A persisted vehicle."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: int
    is_active: bool = False
    created_at: datetime
    updated_at: datetime
