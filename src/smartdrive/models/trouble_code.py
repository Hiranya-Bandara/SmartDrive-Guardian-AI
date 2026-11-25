"""Trouble-code and adapter-connection history models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from smartdrive.config.constants import DataSource, DtcStatus


class TroubleCode(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    vehicle_id: int
    code: str
    status: DtcStatus
    description: str
    description_source: str
    first_seen_at: datetime
    last_seen_at: datetime
    detection_count: int
    is_active: bool
    last_scan_id: int | None

    @property
    def category_letter(self) -> str:
        return self.code[0]


class DtcScan(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    vehicle_id: int
    connection_id: int | None
    session_id: int | None
    scanned_at: datetime
    data_source: DataSource
    is_mock: bool
    protocol: str | None
    mil_on: bool | None
    reported_count: int | None
    stored_count: int
    pending_count: int
    permanent_count: int | None
    codes: list[dict[str, str]]
    freeze_frame: dict[str, Any] | None
    notes: list[str]


class ObdConnection(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    vehicle_id: int | None
    started_at: datetime
    ended_at: datetime | None
    port: str
    connection_method: str
    is_mock: bool
    baudrate: int | None
    adapter_version: str
    adapter_description: str | None
    ecu_connected: bool
    protocol: str | None
    supported_pids: list[int]
    missing_sensors: list[str]
    samples_received: int
    end_reason: str | None
