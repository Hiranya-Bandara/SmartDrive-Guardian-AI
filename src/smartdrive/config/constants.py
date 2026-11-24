"""Application-wide constants and enumerations shared by every layer."""

from enum import StrEnum
from typing import Final

APP_ID: Final = "SmartDriveGuardianAI"
APP_AUTHOR: Final = "SmartDriveGuardianAI"
HOME_ENV_VAR: Final = "SMARTDRIVE_HOME"
DATABASE_FILENAME: Final = "smartdrive.db"
SETTINGS_FILENAME: Final = "settings.json"
LOG_FILENAME: Final = "smartdrive.log"
LOG_MAX_BYTES: Final = 5 * 1024 * 1024
LOG_BACKUP_COUNT: Final = 5

SAFETY_DISCLAIMER: Final = (
    "SmartDrive Guardian AI is an experimental diagnostic and maintenance assistant. "
    "It is not a certified vehicle safety system, autonomous driving system or "
    "replacement for a qualified mechanic."
)


class DataSource(StrEnum):
    """Origin of telemetry. Never mixed within one driving session."""

    SIMULATION = "simulation"
    LIVE = "live"
    REPLAY = "replay"


class Severity(StrEnum):
    INFORMATION = "information"
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class FuelType(StrEnum):
    PETROL = "petrol"
    DIESEL = "diesel"
    HYBRID = "hybrid"
    PLUG_IN_HYBRID = "plug_in_hybrid"
    ELECTRIC = "electric"
    LPG = "lpg"
    CNG = "cng"
    OTHER = "other"


class TransmissionType(StrEnum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    CVT = "cvt"
    DUAL_CLUTCH = "dual_clutch"
    OTHER = "other"


class DiagnosticSource(StrEnum):
    RULE = "rule"
    CLASSIFIER = "classifier"
    ANOMALY_DETECTOR = "anomaly_detector"
    DTC = "dtc"
    COMBINED = "combined"


class FaultCategory(StrEnum):
    COOLING = "cooling"
    LUBRICATION = "lubrication"
    TRANSMISSION = "transmission"
    FUEL = "fuel"
    ELECTRICAL = "electrical"
    SENSOR = "sensor"
    BRAKE = "brake"
    UNKNOWN_ANOMALY = "unknown_anomaly"
    NONE_DETECTED = "none_detected"


class DtcStatus(StrEnum):
    STORED = "stored"
    PENDING = "pending"
    PERMANENT = "permanent"


class MaintenanceStatus(StrEnum):
    PLANNED = "planned"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ThemePreference(StrEnum):
    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"


class UnitSystem(StrEnum):
    METRIC = "metric"
    IMPERIAL = "imperial"


class ExportFormat(StrEnum):
    PDF = "pdf"
    CSV = "csv"
