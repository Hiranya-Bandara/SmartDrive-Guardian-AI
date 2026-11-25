"""Validated user preferences persisted as JSON in the per-user configuration directory.

Preferences live outside the database so they are readable before the database is opened
(for example, the theme and logging level are needed at startup).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from smartdrive.config.constants import ThemePreference, UnitSystem
from smartdrive.utils.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

SETTINGS_SCHEMA_VERSION = 1


class _Section(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True, frozen=False)


class AppearanceSettings(_Section):
    theme: ThemePreference = ThemePreference.DARK
    sidebar_collapsed: bool = False
    animations_enabled: bool = True


class UnitSettings(_Section):
    system: UnitSystem = UnitSystem.METRIC


class MonitoringSettings(_Section):
    refresh_interval_ms: int = Field(default=1000, ge=100, le=10_000)
    chart_history_seconds: int = Field(default=300, ge=30, le=3600)
    stale_after_seconds: float = Field(default=5.0, ge=1.0, le=60.0)


class AlertSettings(_Section):
    desktop_notifications: bool = True
    notification_sounds: bool = False
    voice_notifications: bool = False
    cooldown_seconds: int = Field(default=60, ge=5, le=3600)


class ObdSettings(_Section):
    port: str | None = Field(default=None, max_length=64)
    baudrate: int | None = Field(default=None, ge=9600, le=2_000_000)
    connection_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    max_reconnect_attempts: int = Field(default=3, ge=0, le=10)


class DataRetentionSettings(_Section):
    telemetry_retention_days: int | None = Field(default=365, ge=1, le=3650)
    keep_backups: int = Field(default=5, ge=1, le=50)


class PrivacySettings(_Section):
    redact_identifiers_in_logs: bool = True


class DiagnosticThresholds(_Section):
    """Conservative simulation defaults. They are not manufacturer specifications and should be
    adjusted per vehicle by a qualified person."""

    coolant_warning_c: float = Field(default=105.0, ge=80, le=130)
    coolant_critical_c: float = Field(default=115.0, ge=85, le=140)
    coolant_rise_per_min: float = Field(default=1.5, ge=0.2, le=10)
    voltage_low_warning_v: float = Field(default=12.8, ge=11, le=14)
    voltage_low_critical_v: float = Field(default=12.0, ge=10, le=13.5)
    voltage_high_warning_v: float = Field(default=15.0, ge=14.5, le=16.5)
    oil_pressure_warning_kpa: float = Field(default=100.0, ge=40, le=300)
    oil_pressure_critical_kpa: float = Field(default=60.0, ge=20, le=250)
    rpm_jitter_warning: float = Field(default=110.0, ge=30, le=1000)
    fuel_level_drop_pct: float = Field(default=5.0, ge=1, le=50)

    @model_validator(mode="after")
    def _ordered(self) -> DiagnosticThresholds:
        if self.coolant_critical_c <= self.coolant_warning_c:
            raise ValueError("Critical coolant temperature must exceed the warning level.")
        if self.voltage_low_critical_v >= self.voltage_low_warning_v:
            raise ValueError("Critical low voltage must be below the warning level.")
        if self.oil_pressure_critical_kpa >= self.oil_pressure_warning_kpa:
            raise ValueError("Critical oil pressure must be below the warning level.")
        return self


class DiagnosticSettings(_Section):
    enabled: bool = True
    machine_learning_enabled: bool = True
    inference_interval_s: float = Field(default=2.0, ge=1.0, le=10.0)
    anomaly_sensitivity: Literal["low", "standard", "high"] = "standard"
    anomaly_persistence_windows: int = Field(default=3, ge=1, le=20)
    history_interval_s: float = Field(default=10.0, ge=2.0, le=300.0)
    thresholds: DiagnosticThresholds = Field(default_factory=DiagnosticThresholds)


class LoggingSettings(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class AppSettings(_Section):
    schema_version: int = SETTINGS_SCHEMA_VERSION
    appearance: AppearanceSettings = Field(default_factory=AppearanceSettings)
    units: UnitSettings = Field(default_factory=UnitSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    alerts: AlertSettings = Field(default_factory=AlertSettings)
    obd: ObdSettings = Field(default_factory=ObdSettings)
    retention: DataRetentionSettings = Field(default_factory=DataRetentionSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    diagnostics: DiagnosticSettings = Field(default_factory=DiagnosticSettings)


class SettingsStore:
    """Loads and atomically saves :class:`AppSettings`.

    A corrupt or invalid file never prevents startup: it is moved aside with a timestamped
    name and safe defaults are used instead.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppSettings:
        if not self._path.exists():
            return AppSettings()
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("settings root must be a JSON object")
            return AppSettings.model_validate(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValidationError) as exc:
            quarantined = self._quarantine()
            logger.warning(
                "Settings file was unreadable; defaults restored",
                extra={"error": type(exc).__name__, "quarantined_as": str(quarantined)},
            )
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        payload = settings.model_dump_json(indent=2)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=self._path.parent, prefix=".settings-", suffix=".tmp"
            )
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                tmp_path.replace(self._path)
            finally:
                tmp_path.unlink(missing_ok=True)
        except OSError as exc:
            raise ConfigurationError(
                f"Could not write settings to {self._path}: {exc}",
                user_message="Your preferences could not be saved.",
            ) from exc

    def reset(self) -> AppSettings:
        defaults = AppSettings()
        self.save(defaults)
        return defaults

    def _quarantine(self) -> Path | None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self._path.with_name(f"{self._path.stem}.corrupt-{stamp}{self._path.suffix}")
        try:
            self._path.replace(target)
        except OSError:
            return None
        return target
