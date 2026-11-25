"""Vehicle integration: OBD-II connections, trouble-code scans, trip summaries and events,
notifications, per-vehicle rule thresholds; extend sessions, codes, alerts, maintenance and
export history. Additive: every existing row is kept (new NOT NULL columns have defaults).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "obd_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("port", sa.String(length=64), nullable=False),
        sa.Column("connection_method", sa.String(length=48), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("baudrate", sa.Integer(), nullable=True),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("adapter_description", sa.String(length=120), nullable=True),
        sa.Column("ecu_connected", sa.Boolean(), nullable=False),
        sa.Column("protocol", sa.String(length=64), nullable=True),
        sa.Column("supported_pids", sa.JSON(), nullable=False),
        sa.Column("missing_sensors", sa.JSON(), nullable=False),
        sa.Column("samples_received", sa.Integer(), nullable=False),
        sa.Column("end_reason", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name=op.f("ck_obd_connections_ended_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_obd_connections_vehicle_id_vehicles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_obd_connections")),
    )
    with op.batch_alter_table("obd_connections", schema=None) as batch_op:
        batch_op.create_index(
            "ix_obd_connections_vehicle_started", ["vehicle_id", "started_at"], unique=False
        )

    op.create_table(
        "vehicle_thresholds",
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_vehicle_thresholds_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("vehicle_id", name=op.f("pk_vehicle_thresholds")),
    )
    op.create_table(
        "dtc_scans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(), nullable=False),
        sa.Column(
            "data_source",
            sa.Enum(
                "simulation",
                "live",
                "replay",
                name="scan_data_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("protocol", sa.String(length=64), nullable=True),
        sa.Column("mil_on", sa.Boolean(), nullable=True),
        sa.Column("reported_count", sa.Integer(), nullable=True),
        sa.Column("stored_count", sa.Integer(), nullable=False),
        sa.Column("pending_count", sa.Integer(), nullable=False),
        sa.Column("permanent_count", sa.Integer(), nullable=True),
        sa.Column("codes", sa.JSON(), nullable=False),
        sa.Column("freeze_frame", sa.JSON(), nullable=True),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["obd_connections.id"],
            name=op.f("fk_dtc_scans_connection_id_obd_connections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_dtc_scans_session_id_driving_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_dtc_scans_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dtc_scans")),
    )
    with op.batch_alter_table("dtc_scans", schema=None) as batch_op:
        batch_op.create_index(
            "ix_dtc_scans_vehicle_scanned", ["vehicle_id", "scanned_at"], unique=False
        )

    op.create_table(
        "trip_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "finding",
                "anomaly",
                "trouble_codes",
                "connection_lost",
                "connection_restored",
                "recording_interrupted",
                name="trip_event_type",
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
                name="trip_event_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("finding_key", sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_trip_events_session_id_driving_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_events")),
    )
    with op.batch_alter_table("trip_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_trip_events_session_time", ["session_id", "occurred_at"], unique=False
        )

    op.create_table(
        "trip_summaries",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("recorded_duration_s", sa.Float(), nullable=False),
        sa.Column("data_completeness", sa.Float(), nullable=False),
        sa.Column("avg_speed_kph", sa.Float(), nullable=True),
        sa.Column("max_speed_kph", sa.Float(), nullable=True),
        sa.Column("avg_rpm", sa.Float(), nullable=True),
        sa.Column("max_rpm", sa.Float(), nullable=True),
        sa.Column("min_coolant_c", sa.Float(), nullable=True),
        sa.Column("max_coolant_c", sa.Float(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("distance_coverage", sa.Float(), nullable=True),
        sa.Column("diagnostic_event_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("critical_count", sa.Integer(), nullable=False),
        sa.Column("anomaly_count", sa.Integer(), nullable=False),
        sa.Column("dtc_count", sa.Integer(), nullable=True),
        sa.Column("model_versions", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "data_completeness >= 0 AND data_completeness <= 1",
            name=op.f("ck_trip_summaries_completeness_range"),
        ),
        sa.CheckConstraint(
            "distance_km IS NULL OR distance_km >= 0",
            name=op.f("ck_trip_summaries_distance_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_trip_summaries_session_id_driving_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_trip_summaries")),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_occurrence_at", sa.DateTime(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "information",
                "success",
                "warning",
                "critical",
                name="notification_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("alert_id", sa.Integer(), nullable=True),
        sa.Column("dedup_key", sa.String(length=160), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "occurrence_count >= 1", name=op.f("ck_notifications_occurrence_positive")
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name=op.f("fk_notifications_alert_id_alerts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_notifications_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index("ix_notifications_created", ["created_at"], unique=False)
        batch_op.create_index("ix_notifications_dedup_key", ["dedup_key"], unique=False)

    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("read_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"))

    with op.batch_alter_table("diagnostic_trouble_codes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_scan_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("detection_count", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column(
                "description_source", sa.String(length=120), nullable=False, server_default=""
            )
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_diagnostic_trouble_codes_last_scan_id_dtc_scans"),
            "dtc_scans",
            ["last_scan_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("driving_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "status",
                sa.Enum(
                    "recording",
                    "completed",
                    "interrupted",
                    name="session_status",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
                nullable=False,
                server_default="completed",
            )
        )

    op.execute("UPDATE driving_sessions SET status = 'recording' WHERE ended_at IS NULL")

    with op.batch_alter_table("export_history", schema=None) as batch_op:
        batch_op.add_column(sa.Column("report_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(length=16), nullable=False, server_default="success")
        )
        batch_op.add_column(sa.Column("file_path", sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column("file_size", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("message", sa.Text(), nullable=False, server_default=""))

    with op.batch_alter_table("maintenance_records", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "category",
                sa.String(length=40),
                nullable=False,
                server_default="general_inspection",
            )
        )
        batch_op.add_column(sa.Column("next_due_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("next_due_km", sa.Float(), nullable=True))

    with op.batch_alter_table("maintenance_schedules", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("category", sa.String(length=40), nullable=False, server_default="custom")
        )
        batch_op.add_column(
            sa.Column("reminder_days_before", sa.Integer(), nullable=False, server_default="14")
        )
        batch_op.add_column(
            sa.Column("reminder_km_before", sa.Float(), nullable=False, server_default="500")
        )
        batch_op.add_column(
            sa.Column(
                "interval_source", sa.String(length=16), nullable=False, server_default="user"
            )
        )
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=False, server_default=""))

    with op.batch_alter_table("vehicles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mileage_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vehicles", schema=None) as batch_op:
        batch_op.drop_column("mileage_updated_at")

    with op.batch_alter_table("maintenance_schedules", schema=None) as batch_op:
        batch_op.drop_column("notes")
        batch_op.drop_column("interval_source")
        batch_op.drop_column("reminder_km_before")
        batch_op.drop_column("reminder_days_before")
        batch_op.drop_column("category")

    with op.batch_alter_table("maintenance_records", schema=None) as batch_op:
        batch_op.drop_column("next_due_km")
        batch_op.drop_column("next_due_date")
        batch_op.drop_column("category")

    with op.batch_alter_table("export_history", schema=None) as batch_op:
        batch_op.drop_column("message")
        batch_op.drop_column("file_size")
        batch_op.drop_column("file_path")
        batch_op.drop_column("status")
        batch_op.drop_column("report_id")

    with op.batch_alter_table("driving_sessions", schema=None) as batch_op:
        # SQLite batch mode keeps an enum's CHECK constraint unless it is dropped explicitly.
        batch_op.drop_constraint(batch_op.f("ck_driving_sessions_session_status"), type_="check")
        batch_op.drop_column("status")
        batch_op.drop_column("name")

    with op.batch_alter_table("diagnostic_trouble_codes", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_diagnostic_trouble_codes_last_scan_id_dtc_scans"), type_="foreignkey"
        )
        batch_op.drop_column("description_source")
        batch_op.drop_column("is_active")
        batch_op.drop_column("detection_count")
        batch_op.drop_column("last_scan_id")

    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_column("evidence")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("read_at")

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("ix_notifications_dedup_key")
        batch_op.drop_index("ix_notifications_created")

    op.drop_table("notifications")
    op.drop_table("trip_summaries")
    with op.batch_alter_table("trip_events", schema=None) as batch_op:
        batch_op.drop_index("ix_trip_events_session_time")

    op.drop_table("trip_events")
    with op.batch_alter_table("dtc_scans", schema=None) as batch_op:
        batch_op.drop_index("ix_dtc_scans_vehicle_scanned")

    op.drop_table("dtc_scans")
    op.drop_table("vehicle_thresholds")
    with op.batch_alter_table("obd_connections", schema=None) as batch_op:
        batch_op.drop_index("ix_obd_connections_vehicle_started")

    op.drop_table("obd_connections")
