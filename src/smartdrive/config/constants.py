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


class NotificationSeverity(StrEnum):
    """Application notification level. Deliberately separate from diagnostic ``Severity``."""

    INFORMATION = "information"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"


class NotificationCategory(StrEnum):
    DIAGNOSTIC = "diagnostic"
    CONNECTION = "connection"
    TELEMETRY = "telemetry"
    MODEL = "model"
    MAINTENANCE = "maintenance"
    TRIP = "trip"
    REPORT = "report"
    APPLICATION = "application"


class SessionStatus(StrEnum):
    RECORDING = "recording"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


class TripEventType(StrEnum):
    FINDING = "finding"
    ANOMALY = "anomaly"
    TROUBLE_CODES = "trouble_codes"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_RESTORED = "connection_restored"
    RECORDING_INTERRUPTED = "recording_interrupted"


class MaintenanceCategory(StrEnum):
    ENGINE_OIL = "engine_oil"
    OIL_FILTER = "oil_filter"
    AIR_FILTER = "air_filter"
    CABIN_AIR_FILTER = "cabin_air_filter"
    BRAKE_INSPECTION = "brake_inspection"
    BRAKE_FLUID = "brake_fluid"
    COOLANT = "coolant"
    BATTERY = "battery"
    TYRE_INSPECTION = "tyre_inspection"
    TYRE_ROTATION = "tyre_rotation"
    TRANSMISSION = "transmission"
    SPARK_PLUGS = "spark_plugs"
    GENERAL_INSPECTION = "general_inspection"
    CUSTOM = "custom"

    @property
    def label(self) -> str:
        return _MAINTENANCE_LABELS[self]


_MAINTENANCE_LABELS: Final = {
    MaintenanceCategory.ENGINE_OIL: "Engine oil replacement",
    MaintenanceCategory.OIL_FILTER: "Oil filter replacement",
    MaintenanceCategory.AIR_FILTER: "Air filter replacement",
    MaintenanceCategory.CABIN_AIR_FILTER: "Cabin air filter replacement",
    MaintenanceCategory.BRAKE_INSPECTION: "Brake inspection",
    MaintenanceCategory.BRAKE_FLUID: "Brake fluid service",
    MaintenanceCategory.COOLANT: "Coolant service",
    MaintenanceCategory.BATTERY: "Battery inspection",
    MaintenanceCategory.TYRE_INSPECTION: "Tyre inspection",
    MaintenanceCategory.TYRE_ROTATION: "Tyre rotation",
    MaintenanceCategory.TRANSMISSION: "Transmission service",
    MaintenanceCategory.SPARK_PLUGS: "Spark plug replacement",
    MaintenanceCategory.GENERAL_INSPECTION: "General inspection",
    MaintenanceCategory.CUSTOM: "Custom maintenance activity",
}


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
