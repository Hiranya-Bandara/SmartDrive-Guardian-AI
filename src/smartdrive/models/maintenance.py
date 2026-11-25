"""Maintenance records, schedules and their computed status."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from smartdrive.config.constants import MaintenanceCategory, MaintenanceStatus

CURRENCY_PATTERN = r"^[A-Z]{3}$"


class MaintenanceRecordInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: MaintenanceCategory = MaintenanceCategory.GENERAL_INSPECTION
    title: str = Field(min_length=1, max_length=160)
    status: MaintenanceStatus = MaintenanceStatus.COMPLETED
    service_date: date | None = None
    mileage_km: float | None = Field(default=None, ge=0, le=5_000_000)
    provider: str | None = Field(default=None, max_length=120)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, pattern=CURRENCY_PATTERN)
    notes: str = Field(default="", max_length=4000)
    next_due_date: date | None = None
    next_due_km: float | None = Field(default=None, ge=0, le=5_000_000)
    schedule_id: int | None = None

    @field_validator("provider")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _consistent(self) -> MaintenanceRecordInput:
        if self.cost is not None and self.currency is None:
            raise ValueError("Choose the currency of the cost.")
        if self.status is MaintenanceStatus.COMPLETED and self.service_date is None:
            raise ValueError("A completed service needs its service date.")
        if self.next_due_date and self.service_date and self.next_due_date <= self.service_date:
            raise ValueError("The next service date must be after the service date.")
        if (
            self.next_due_km is not None
            and self.mileage_km is not None
            and self.next_due_km <= self.mileage_km
        ):
            raise ValueError("The next service odometer reading must be above this reading.")
        return self


class MaintenanceRecordView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    vehicle_id: int
    schedule_id: int | None
    category: str
    title: str
    status: MaintenanceStatus
    service_date: date | None
    mileage_km: float | None
    cost: Decimal | None
    currency: str | None
    provider: str | None
    notes: str
    next_due_date: date | None
    next_due_km: float | None
    created_at: datetime


class ScheduleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: MaintenanceCategory = MaintenanceCategory.CUSTOM
    task_name: str = Field(min_length=1, max_length=120)
    interval_days: int | None = Field(default=None, ge=1, le=3650)
    interval_km: float | None = Field(default=None, gt=0, le=500_000)
    last_done_date: date | None = None
    last_done_mileage_km: float | None = Field(default=None, ge=0, le=5_000_000)
    reminder_days_before: int = Field(default=14, ge=0, le=365)
    reminder_km_before: float = Field(default=500.0, ge=0, le=50_000)
    interval_source: str = Field(default="user", pattern=r"^(user|example)$")
    notes: str = Field(default="", max_length=2000)
    is_active: bool = True

    @model_validator(mode="after")
    def _has_interval(self) -> ScheduleInput:
        if self.interval_days is None and self.interval_km is None:
            raise ValueError("Enter a time interval, a distance interval, or both.")
        return self


class ScheduleView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    vehicle_id: int
    category: str
    task_name: str
    interval_days: int | None
    interval_km: float | None
    last_done_date: date | None
    last_done_mileage_km: float | None
    reminder_days_before: int
    reminder_km_before: float
    interval_source: str
    notes: str
    is_active: bool


class ScheduleState(StrEnum):
    NOT_SCHEDULED = "not_scheduled"
    UP_TO_DATE = "up_to_date"
    UPCOMING = "upcoming"
    DUE = "due"
    OVERDUE = "overdue"
    INSUFFICIENT_MILEAGE = "insufficient_mileage"

    @property
    def label(self) -> str:
        return {
            "not_scheduled": "Not scheduled",
            "up_to_date": "Up to date",
            "upcoming": "Upcoming",
            "due": "Due",
            "overdue": "Overdue",
            "insufficient_mileage": "Insufficient mileage information",
        }[self.value]

    @property
    def rank(self) -> int:
        return {
            "not_scheduled": 0,
            "insufficient_mileage": 1,
            "up_to_date": 1,
            "upcoming": 2,
            "due": 3,
            "overdue": 4,
        }[self.value]


class ScheduleStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    schedule: ScheduleView
    state: ScheduleState
    due_date: date | None
    due_km: float | None
    days_remaining: int | None
    km_remaining: float | None
    baseline_date: date | None
    baseline_km: float | None
    notes: tuple[str, ...] = ()
