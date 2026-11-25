"""Notification and alert views for the Alert Centre."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from smartdrive.config.constants import (
    DataSource,
    DiagnosticSource,
    NotificationCategory,
    NotificationSeverity,
    Severity,
)


class Notification(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    created_at: datetime
    last_occurrence_at: datetime
    severity: NotificationSeverity
    category: str
    title: str
    message: str
    vehicle_id: int | None
    alert_id: int | None
    dedup_key: str
    occurrence_count: int
    read_at: datetime | None
    acknowledged_at: datetime | None

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    @property
    def category_enum(self) -> NotificationCategory | None:
        try:
            return NotificationCategory(self.category)
        except ValueError:
            return None


class DiagnosticAlert(BaseModel):
    """A diagnostic condition alert. Acknowledging it does not resolve the condition."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    vehicle_id: int | None
    session_id: int | None
    created_at: datetime
    last_occurrence_at: datetime
    severity: Severity
    category: str
    title: str
    message: str
    data_source: DataSource | None
    source: DiagnosticSource | None
    dedup_key: str
    occurrence_count: int
    acknowledged_at: datetime | None
    read_at: datetime | None
    resolved_at: datetime | None
    evidence: dict[str, Any]

    @property
    def condition_active(self) -> bool:
        return self.resolved_at is None

    @property
    def state_text(self) -> str:
        condition = "Condition resolved" if self.resolved_at else "Condition still active"
        acknowledgement = "acknowledged" if self.acknowledged_at else "not acknowledged"
        return f"{condition} · {acknowledgement}"
