"""SQLAlchemy ORM schema. Alembic migrations are the source of truth for the deployed schema;
``tests/integration/test_migrations.py`` asserts that both stay identical."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from smartdrive.config.constants import (
    DataSource,
    DiagnosticSource,
    DtcStatus,
    ExportFormat,
    FaultCategory,
    FuelType,
    MaintenanceStatus,
    NotificationSeverity,
    SessionStatus,
    Severity,
    TransmissionType,
    TripEventType,
)
from smartdrive.database.types import UtcDateTime, utc_now
from smartdrive.models.diagnostic import DiagnosticStatus

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store enum *values* as strings with a CHECK constraint (portable, readable)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class VehicleRecord(TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("year >= 1886", name="year_range"),
        CheckConstraint("mileage_km >= 0", name="mileage_non_negative"),
        CheckConstraint(
            "engine_capacity_cc IS NULL OR engine_capacity_cc > 0", name="engine_capacity_positive"
        ),
        Index("ix_vehicles_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    manufacturer: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(60))
    year: Mapped[int] = mapped_column(Integer)
    fuel_type: Mapped[FuelType] = mapped_column(_enum(FuelType, "fuel_type"))
    transmission: Mapped[TransmissionType] = mapped_column(_enum(TransmissionType, "transmission"))
    engine_capacity_cc: Mapped[int | None] = mapped_column(Integer)
    mileage_km: Mapped[float] = mapped_column(Float, default=0.0)
    mileage_updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    registration_number: Mapped[str | None] = mapped_column(String(16))
    vin: Mapped[str | None] = mapped_column(String(17), unique=True)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    last_service_date: Mapped[date | None] = mapped_column(Date)
    next_service_date: Mapped[date | None] = mapped_column(Date)
    image_path: Mapped[str | None] = mapped_column(String(1024))
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    sessions: Mapped[list[DrivingSessionRecord]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan", passive_deletes=True
    )


class DrivingSessionRecord(Base):
    __tablename__ = "driving_sessions"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ended_after_start"),
        CheckConstraint("distance_km IS NULL OR distance_km >= 0", name="distance_non_negative"),
        Index("ix_driving_sessions_vehicle_started", "vehicle_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    data_source: Mapped[DataSource] = mapped_column(_enum(DataSource, "data_source"))
    scenario: Mapped[str | None] = mapped_column(String(64))
    random_seed: Mapped[int | None] = mapped_column(Integer)
    replay_of_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("driving_sessions.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(UtcDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    distance_km: Mapped[float | None] = mapped_column(Float)
    distance_estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    name: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[SessionStatus] = mapped_column(
        _enum(SessionStatus, "session_status"), default=SessionStatus.RECORDING
    )

    vehicle: Mapped[VehicleRecord] = relationship(back_populates="sessions")


class TelemetryReadingRecord(Base):
    __tablename__ = "telemetry_readings"
    __table_args__ = (Index("ix_telemetry_session_time", "session_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("driving_sessions.id", ondelete="CASCADE"))
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime())
    coolant_temp_c: Mapped[float | None] = mapped_column(Float)
    rpm: Mapped[float | None] = mapped_column(Float)
    speed_kph: Mapped[float | None] = mapped_column(Float)
    fuel_level_pct: Mapped[float | None] = mapped_column(Float)
    engine_load_pct: Mapped[float | None] = mapped_column(Float)
    throttle_pct: Mapped[float | None] = mapped_column(Float)
    intake_air_temp_c: Mapped[float | None] = mapped_column(Float)
    control_module_voltage_v: Mapped[float | None] = mapped_column(Float)
    oil_temp_c: Mapped[float | None] = mapped_column(Float)
    oil_pressure_kpa: Mapped[float | None] = mapped_column(Float)
    fuel_rate_lph: Mapped[float | None] = mapped_column(Float)
    fuel_rate_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DiagnosticAssessmentRecord(Base):
    """One hybrid-engine analysis: health-score history, model outputs and data quality."""

    __tablename__ = "diagnostic_assessments"
    __table_args__ = (
        CheckConstraint(
            "health_score IS NULL OR (health_score >= 0 AND health_score <= 100)",
            name="health_score_range",
        ),
        CheckConstraint(
            "data_completeness >= 0 AND data_completeness <= 1", name="completeness_range"
        ),
        Index("ix_diagnostic_assessments_vehicle_created", "vehicle_id", "created_at"),
        Index("ix_diagnostic_assessments_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("driving_sessions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    data_source: Mapped[DataSource] = mapped_column(_enum(DataSource, "assessment_data_source"))
    status: Mapped[DiagnosticStatus] = mapped_column(_enum(DiagnosticStatus, "diagnostic_status"))
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "assessment_severity"))
    health_score: Mapped[int | None] = mapped_column(Integer)
    data_completeness: Mapped[float] = mapped_column(Float)
    classifier_status: Mapped[str] = mapped_column(String(32))
    anomaly_status: Mapped[str] = mapped_column(String(32))
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    is_anomalous: Mapped[bool] = mapped_column(Boolean, default=False)
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    inference_ms: Mapped[float] = mapped_column(Float, default=0.0)


class DiagnosticResultRecord(Base):
    __tablename__ = "diagnostic_results"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        Index("ix_diagnostic_results_vehicle_created", "vehicle_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("driving_sessions.id", ondelete="SET NULL")
    )
    assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("diagnostic_assessments.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    data_source: Mapped[DataSource | None] = mapped_column(_enum(DataSource, "finding_data_source"))
    finding_key: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[DiagnosticSource] = mapped_column(_enum(DiagnosticSource, "diagnostic_source"))
    category: Mapped[FaultCategory] = mapped_column(_enum(FaultCategory, "fault_category"))
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "diagnostic_severity"))
    confidence: Mapped[float | None] = mapped_column(Float)
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(255))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    data_quality: Mapped[float | None] = mapped_column(Float)


class DiagnosticTroubleCodeRecord(Base):
    __tablename__ = "diagnostic_trouble_codes"
    __table_args__ = (
        UniqueConstraint("vehicle_id", "code", "status", name="uq_dtc_vehicle_code_status"),
        CheckConstraint("length(code) = 5", name="code_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("driving_sessions.id", ondelete="SET NULL")
    )
    code: Mapped[str] = mapped_column(String(5))
    description: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[DtcStatus] = mapped_column(_enum(DtcStatus, "dtc_status"))
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    last_scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("dtc_scans.id", ondelete="SET NULL")
    )
    detection_count: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description_source: Mapped[str] = mapped_column(String(120), default="")


class AlertRecord(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("occurrence_count >= 1", name="occurrence_positive"),
        Index("ix_alerts_dedup_key", "dedup_key"),
        Index("ix_alerts_severity_created", "severity", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("driving_sessions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    last_occurrence_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "alert_severity"))
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text, default="")
    data_source: Mapped[DataSource | None] = mapped_column(_enum(DataSource, "alert_data_source"))
    source: Mapped[DiagnosticSource | None] = mapped_column(
        _enum(DiagnosticSource, "alert_diagnostic_source")
    )
    dedup_key: Mapped[str] = mapped_column(String(160))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MaintenanceScheduleRecord(TimestampMixin, Base):
    __tablename__ = "maintenance_schedules"
    __table_args__ = (
        CheckConstraint(
            "interval_km IS NOT NULL OR interval_days IS NOT NULL", name="has_interval"
        ),
        CheckConstraint("interval_km IS NULL OR interval_km > 0", name="interval_km_positive"),
        CheckConstraint(
            "interval_days IS NULL OR interval_days > 0", name="interval_days_positive"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    task_name: Mapped[str] = mapped_column(String(120))
    interval_km: Mapped[float | None] = mapped_column(Float)
    interval_days: Mapped[int | None] = mapped_column(Integer)
    last_done_date: Mapped[date | None] = mapped_column(Date)
    last_done_mileage_km: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    category: Mapped[str] = mapped_column(String(40), default="custom")
    reminder_days_before: Mapped[int] = mapped_column(Integer, default=14)
    reminder_km_before: Mapped[float] = mapped_column(Float, default=500.0)
    interval_source: Mapped[str] = mapped_column(String(16), default="user")
    notes: Mapped[str] = mapped_column(Text, default="")


class MaintenanceRecord(TimestampMixin, Base):
    __tablename__ = "maintenance_records"
    __table_args__ = (
        CheckConstraint("cost IS NULL OR cost >= 0", name="cost_non_negative"),
        CheckConstraint("mileage_km IS NULL OR mileage_km >= 0", name="mileage_non_negative"),
        Index("ix_maintenance_records_vehicle_date", "vehicle_id", "service_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("maintenance_schedules.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[MaintenanceStatus] = mapped_column(
        _enum(MaintenanceStatus, "maintenance_status")
    )
    service_date: Mapped[date | None] = mapped_column(Date)
    mileage_km: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    provider: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    category: Mapped[str] = mapped_column(String(40), default="general_inspection")
    next_due_date: Mapped[date | None] = mapped_column(Date)
    next_due_km: Mapped[float | None] = mapped_column(Float)


class AppSettingRecord(Base):
    """Database-scoped key/value state (user preferences live in settings.json)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now, onupdate=utc_now)


class ModelMetadataRecord(Base):
    __tablename__ = "model_metadata"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_model_metadata_name_version"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    model_type: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    trained_at: Mapped[datetime] = mapped_column(UtcDateTime())
    trained_on_synthetic_data: Mapped[bool] = mapped_column(Boolean)
    dataset_description: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class ExportHistoryRecord(Base):
    __tablename__ = "export_history"
    __table_args__ = (Index("ix_export_history_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    report_type: Mapped[str] = mapped_column(String(64))
    export_format: Mapped[ExportFormat] = mapped_column(_enum(ExportFormat, "export_format"))
    file_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    report_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="success")
    file_path: Mapped[str | None] = mapped_column(String(1024))
    file_size: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, default="")


class ObdConnectionRecord(Base):
    """One adapter connection, with what the vehicle reported it supports."""

    __tablename__ = "obd_connections"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ended_after_start"),
        Index("ix_obd_connections_vehicle_started", "vehicle_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    port: Mapped[str] = mapped_column(String(64))
    connection_method: Mapped[str] = mapped_column(String(48))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    baudrate: Mapped[int | None] = mapped_column(Integer)
    adapter_version: Mapped[str] = mapped_column(String(64), default="")
    adapter_description: Mapped[str | None] = mapped_column(String(120))
    ecu_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    protocol: Mapped[str | None] = mapped_column(String(64))
    supported_pids: Mapped[list[int]] = mapped_column(JSON, default=list)
    missing_sensors: Mapped[list[str]] = mapped_column(JSON, default=list)
    samples_received: Mapped[int] = mapped_column(Integer, default=0)
    end_reason: Mapped[str | None] = mapped_column(String(200))


class DtcScanRecord(Base):
    """One read-only trouble-code scan. Codes are upserted into ``diagnostic_trouble_codes``."""

    __tablename__ = "dtc_scans"
    __table_args__ = (Index("ix_dtc_scans_vehicle_scanned", "vehicle_id", "scanned_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("obd_connections.id", ondelete="SET NULL")
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("driving_sessions.id", ondelete="SET NULL")
    )
    scanned_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    data_source: Mapped[DataSource] = mapped_column(_enum(DataSource, "scan_data_source"))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    protocol: Mapped[str | None] = mapped_column(String(64))
    mil_on: Mapped[bool | None] = mapped_column(Boolean)
    reported_count: Mapped[int | None] = mapped_column(Integer)
    stored_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)
    permanent_count: Mapped[int | None] = mapped_column(Integer)
    codes: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    freeze_frame: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)


class TripSummaryRecord(Base):
    """Statistics computed when a recorded session ends. Estimated values are flagged."""

    __tablename__ = "trip_summaries"
    __table_args__ = (
        CheckConstraint(
            "data_completeness >= 0 AND data_completeness <= 1", name="completeness_range"
        ),
        CheckConstraint("distance_km IS NULL OR distance_km >= 0", name="distance_non_negative"),
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("driving_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    recorded_duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    data_completeness: Mapped[float] = mapped_column(Float, default=0.0)
    avg_speed_kph: Mapped[float | None] = mapped_column(Float)
    max_speed_kph: Mapped[float | None] = mapped_column(Float)
    avg_rpm: Mapped[float | None] = mapped_column(Float)
    max_rpm: Mapped[float | None] = mapped_column(Float)
    min_coolant_c: Mapped[float | None] = mapped_column(Float)
    max_coolant_c: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    distance_coverage: Mapped[float | None] = mapped_column(Float)
    diagnostic_event_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0)
    dtc_count: Mapped[int | None] = mapped_column(Integer)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TripEventRecord(Base):
    __tablename__ = "trip_events"
    __table_args__ = (Index("ix_trip_events_session_time", "session_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("driving_sessions.id", ondelete="CASCADE"))
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime())
    event_type: Mapped[TripEventType] = mapped_column(_enum(TripEventType, "trip_event_type"))
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "trip_event_severity"))
    title: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str | None] = mapped_column(String(32))
    finding_key: Mapped[str | None] = mapped_column(String(80))


class NotificationRecord(Base):
    """Application notification shown in the Alert Centre (and optionally on the desktop)."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("occurrence_count >= 1", name="occurrence_positive"),
        Index("ix_notifications_dedup_key", "dedup_key"),
        Index("ix_notifications_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    last_occurrence_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    severity: Mapped[NotificationSeverity] = mapped_column(
        _enum(NotificationSeverity, "notification_severity")
    )
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text, default="")
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    dedup_key: Mapped[str] = mapped_column(String(160))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    acknowledged_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class VehicleThresholdRecord(Base):
    """User-entered rule thresholds for one vehicle, overriding the generic defaults."""

    __tablename__ = "vehicle_thresholds"

    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), primary_key=True
    )
    values: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    source_note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now, onupdate=utc_now)
