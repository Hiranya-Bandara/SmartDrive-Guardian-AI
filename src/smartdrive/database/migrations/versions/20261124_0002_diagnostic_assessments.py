"""Diagnostic assessments (health-score and prediction history); link findings and alerts
to assessments, operating mode and diagnostic source. Additive: existing rows are kept.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24 16:28:52.623543

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "data_source",
            sa.Enum(
                "simulation",
                "live",
                "replay",
                name="assessment_data_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "insufficient_data",
                "stale",
                "no_abnormality",
                "information",
                "warning",
                "critical",
                name="diagnostic_status",
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
                name="assessment_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("health_score", sa.Integer(), nullable=True),
        sa.Column("data_completeness", sa.Float(), nullable=False),
        sa.Column("classifier_status", sa.String(length=32), nullable=False),
        sa.Column("anomaly_status", sa.String(length=32), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=True),
        sa.Column("is_anomalous", sa.Boolean(), nullable=False),
        sa.Column("probabilities", sa.JSON(), nullable=False),
        sa.Column("model_versions", sa.JSON(), nullable=False),
        sa.Column("inference_ms", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "data_completeness >= 0 AND data_completeness <= 1",
            name=op.f("ck_diagnostic_assessments_completeness_range"),
        ),
        sa.CheckConstraint(
            "health_score IS NULL OR (health_score >= 0 AND health_score <= 100)",
            name=op.f("ck_diagnostic_assessments_health_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["driving_sessions.id"],
            name=op.f("fk_diagnostic_assessments_session_id_driving_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_diagnostic_assessments_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnostic_assessments")),
    )
    with op.batch_alter_table("diagnostic_assessments", schema=None) as batch_op:
        batch_op.create_index("ix_diagnostic_assessments_session", ["session_id"], unique=False)
        batch_op.create_index(
            "ix_diagnostic_assessments_vehicle_created", ["vehicle_id", "created_at"], unique=False
        )

    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "source",
                sa.Enum(
                    "rule",
                    "classifier",
                    "anomaly_detector",
                    "dtc",
                    "combined",
                    name="alert_diagnostic_source",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
                nullable=True,
            )
        )

    with op.batch_alter_table("diagnostic_results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assessment_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "data_source",
                sa.Enum(
                    "simulation",
                    "live",
                    "replay",
                    name="finding_data_source",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("finding_key", sa.String(length=80), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_diagnostic_results_assessment_id"), ["assessment_id"], unique=False
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_diagnostic_results_assessment_id_diagnostic_assessments"),
            "diagnostic_assessments",
            ["assessment_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("diagnostic_results", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_diagnostic_results_assessment_id_diagnostic_assessments"),
            type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_diagnostic_results_assessment_id"))
        # SQLite batch mode keeps an enum's CHECK constraint unless it is dropped explicitly.
        batch_op.drop_constraint(
            batch_op.f("ck_diagnostic_results_finding_data_source"), type_="check"
        )
        batch_op.drop_column("finding_key")
        batch_op.drop_column("data_source")
        batch_op.drop_column("assessment_id")

    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_alerts_alert_diagnostic_source"), type_="check")
        batch_op.drop_column("source")

    with op.batch_alter_table("diagnostic_assessments", schema=None) as batch_op:
        batch_op.drop_index("ix_diagnostic_assessments_vehicle_created")
        batch_op.drop_index("ix_diagnostic_assessments_session")

    op.drop_table("diagnostic_assessments")
