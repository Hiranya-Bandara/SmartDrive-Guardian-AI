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
    Severity,
    TransmissionType,
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
