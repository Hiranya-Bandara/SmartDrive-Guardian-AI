"""Initial schema: vehicles, sessions, telemetry, diagnostics, DTCs, alerts,
maintenance, settings, model metadata and export history.

Revision ID: 0001
Revises:
Create Date: 2026-11-24 14:08:33.500896

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )
    op.create_table(
        "model_metadata",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("model_type", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("trained_at", sa.DateTime(), nullable=False),
        sa.Column("trained_on_synthetic_data", sa.Boolean(), nullable=False),
        sa.Column("dataset_description", sa.Text(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("length(sha256) = 64", name=op.f("ck_model_metadata_sha256_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_metadata")),
        sa.UniqueConstraint("name", "version", name="uq_model_metadata_name_version"),
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("manufacturer", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "fuel_type",
            sa.Enum(
                "petrol",
                "diesel",
                "hybrid",
                "plug_in_hybrid",
                "electric",
                "lpg",
                "cng",
                "other",
                name="fuel_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "transmission",
            sa.Enum(
                "manual",
                "automatic",
                "cvt",
                "dual_clutch",
                "other",
                name="transmission",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("engine_capacity_cc", sa.Integer(), nullable=True),
        sa.Column("mileage_km", sa.Float(), nullable=False),
        sa.Column("registration_number", sa.String(length=16), nullable=True),
        sa.Column("vin", sa.String(length=17), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("last_service_date", sa.Date(), nullable=True),
        sa.Column("next_service_date", sa.Date(), nullable=True),
        sa.Column("image_path", sa.String(length=1024), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "engine_capacity_cc IS NULL OR engine_capacity_cc > 0",
            name=op.f("ck_vehicles_engine_capacity_positive"),
        ),
        sa.CheckConstraint("mileage_km >= 0", name=op.f("ck_vehicles_mileage_non_negative")),
        sa.CheckConstraint("year >= 1886", name=op.f("ck_vehicles_year_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicles")),
        sa.UniqueConstraint("vin", name=op.f("uq_vehicles_vin")),
    )
    with op.batch_alter_table("vehicles", schema=None) as batch_op:
        batch_op.create_index("ix_vehicles_name", ["name"], unique=False)

    op.create_table(
        "driving_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column(
            "data_source",
            sa.Enum(
                "simulation",
                "live",
                "replay",
                name="data_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("scenario", sa.String(length=64), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("replay_of_session_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("distance_estimated", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "distance_km IS NULL OR distance_km >= 0",
            name=op.f("ck_driving_sessions_distance_non_negative"),
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name=op.f("ck_driving_sessions_ended_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["replay_of_session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_driving_sessions_replay_of_session_id_driving_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_driving_sessions_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_driving_sessions")),
    )
    with op.batch_alter_table("driving_sessions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_driving_sessions_vehicle_started", ["vehicle_id", "started_at"], unique=False
        )

    op.create_table(
        "export_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("report_type", sa.String(length=64), nullable=False),
        sa.Column(
            "export_format",
            sa.Enum(
                "pdf",
                "csv",
                name="export_format",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_export_history_vehicle_id_vehicles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_history")),
    )
    with op.batch_alter_table("export_history", schema=None) as batch_op:
        batch_op.create_index("ix_export_history_created", ["created_at"], unique=False)

    op.create_table(
        "maintenance_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.String(length=120), nullable=False),
        sa.Column("interval_km", sa.Float(), nullable=True),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("last_done_date", sa.Date(), nullable=True),
        sa.Column("last_done_mileage_km", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "interval_days IS NULL OR interval_days > 0",
            name=op.f("ck_maintenance_schedules_interval_days_positive"),
        ),
        sa.CheckConstraint(
            "interval_km IS NOT NULL OR interval_days IS NOT NULL",
            name=op.f("ck_maintenance_schedules_has_interval"),
        ),
        sa.CheckConstraint(
            "interval_km IS NULL OR interval_km > 0",
            name=op.f("ck_maintenance_schedules_interval_km_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_maintenance_schedules_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_schedules")),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_occurrence_at", sa.DateTime(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "information",
                "normal",
                "warning",
                "critical",
                "unknown",
                name="alert_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "data_source",
            sa.Enum(
                "simulation",
                "live",
                "replay",
                name="alert_data_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("dedup_key", sa.String(length=160), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("occurrence_count >= 1", name=op.f("ck_alerts_occurrence_positive")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_alerts_session_id_driving_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_alerts_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.create_index("ix_alerts_dedup_key", ["dedup_key"], unique=False)
        batch_op.create_index(
            "ix_alerts_severity_created", ["severity", "created_at"], unique=False
        )

    op.create_table(
        "diagnostic_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "rule",
                "classifier",
                "anomaly_detector",
                "dtc",
                "combined",
                name="diagnostic_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "cooling",
                "lubrication",
                "transmission",
                "fuel",
                "electrical",
                "sensor",
                "brake",
                "unknown_anomaly",
                "none_detected",
                name="fault_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "information",
                "normal",
                "warning",
                "critical",
                "unknown",
                name="diagnostic_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("anomaly_score", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("data_quality", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_diagnostic_results_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_diagnostic_results_session_id_driving_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_diagnostic_results_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnostic_results")),
    )
    with op.batch_alter_table("diagnostic_results", schema=None) as batch_op:
        batch_op.create_index(
            "ix_diagnostic_results_vehicle_created", ["vehicle_id", "created_at"], unique=False
        )

    op.create_table(
        "diagnostic_trouble_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=5), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "stored",
                "pending",
                "permanent",
                name="dtc_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(code) = 5", name=op.f("ck_diagnostic_trouble_codes_code_length")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_diagnostic_trouble_codes_session_id_driving_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_diagnostic_trouble_codes_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnostic_trouble_codes")),
        sa.UniqueConstraint("vehicle_id", "code", "status", name="uq_dtc_vehicle_code_status"),
    )
    op.create_table(
        "maintenance_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "completed",
                "cancelled",
                name="maintenance_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("service_date", sa.Date(), nullable=True),
        sa.Column("mileage_km", sa.Float(), nullable=True),
        sa.Column("cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("provider", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "cost IS NULL OR cost >= 0", name=op.f("ck_maintenance_records_cost_non_negative")
        ),
        sa.CheckConstraint(
            "mileage_km IS NULL OR mileage_km >= 0",
            name=op.f("ck_maintenance_records_mileage_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["maintenance_schedules.id"],
            name=op.f("fk_maintenance_records_schedule_id_maintenance_schedules"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_maintenance_records_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_records")),
    )
    with op.batch_alter_table("maintenance_records", schema=None) as batch_op:
        batch_op.create_index(
            "ix_maintenance_records_vehicle_date", ["vehicle_id", "service_date"], unique=False
        )

    op.create_table(
        "telemetry_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("coolant_temp_c", sa.Float(), nullable=True),
        sa.Column("rpm", sa.Float(), nullable=True),
        sa.Column("speed_kph", sa.Float(), nullable=True),
        sa.Column("fuel_level_pct", sa.Float(), nullable=True),
        sa.Column("engine_load_pct", sa.Float(), nullable=True),
        sa.Column("throttle_pct", sa.Float(), nullable=True),
        sa.Column("intake_air_temp_c", sa.Float(), nullable=True),
        sa.Column("control_module_voltage_v", sa.Float(), nullable=True),
        sa.Column("oil_temp_c", sa.Float(), nullable=True),
        sa.Column("oil_pressure_kpa", sa.Float(), nullable=True),
        sa.Column("fuel_rate_lph", sa.Float(), nullable=True),
        sa.Column("fuel_rate_estimated", sa.Boolean(), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_telemetry_readings_session_id_driving_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_readings")),
    )
    with op.batch_alter_table("telemetry_readings", schema=None) as batch_op:
        batch_op.create_index(
            "ix_telemetry_session_time", ["session_id", "timestamp"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("telemetry_readings", schema=None) as batch_op:
        batch_op.drop_index("ix_telemetry_session_time")

    op.drop_table("telemetry_readings")
    with op.batch_alter_table("maintenance_records", schema=None) as batch_op:
        batch_op.drop_index("ix_maintenance_records_vehicle_date")

    op.drop_table("maintenance_records")
    op.drop_table("diagnostic_trouble_codes")
    with op.batch_alter_table("diagnostic_results", schema=None) as batch_op:
        batch_op.drop_index("ix_diagnostic_results_vehicle_created")

    op.drop_table("diagnostic_results")
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_index("ix_alerts_severity_created")
        batch_op.drop_index("ix_alerts_dedup_key")

    op.drop_table("alerts")
    op.drop_table("maintenance_schedules")
    with op.batch_alter_table("export_history", schema=None) as batch_op:
        batch_op.drop_index("ix_export_history_created")

    op.drop_table("export_history")
    with op.batch_alter_table("driving_sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_driving_sessions_vehicle_started")

    op.drop_table("driving_sessions")
    with op.batch_alter_table("vehicles", schema=None) as batch_op:
        batch_op.drop_index("ix_vehicles_name")

    op.drop_table("vehicles")
    op.drop_table("model_metadata")
    op.drop_table("app_settings")
