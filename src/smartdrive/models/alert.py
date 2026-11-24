from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from smartdrive.config.constants import DataSource, Severity


class Alert(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    vehicle_id: int | None
    created_at: datetime
    last_occurrence_at: datetime
    severity: Severity
    category: str
    title: str
    message: str
    data_source: DataSource | None
    occurrence_count: int
    acknowledged_at: datetime | None
