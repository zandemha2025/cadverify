"""create analyses, jobs, usage_events tables

Revision ID: 0002_create_analyses_jobs_usage_events
Revises: 0001_create_users_api_keys
Create Date: 2026-04-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_create_analyses_jobs_usage_events"
down_revision = "0001_create_users_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safety: cap migration statement duration
    op.execute("SET statement_timeout = '5000'")

    # ---- analyses ----
    op.create_table(
        "analyses",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, unique=True, nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_key_id",
            sa.BigInteger,
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mesh_hash", sa.Text, nullable=False),
        sa.Column("process_set_hash", sa.Text, nullable=False),
        sa.Column("analysis_version", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("file_type", sa.Text, nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=False),
        sa.Column("result_json", JSONB, nullable=False),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column("face_count", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Float, nullable=False),
        sa.Column(
            "is_public", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("share_short_id", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Indexes on analyses
    op.create_index(
        "ix_analyses_user_created",
        "analyses",
        ["user_id", sa.text("created_at DESC")],
    )
    op.execute(
        "ALTER TABLE analyses ADD CONSTRAINT uq_analyses_dedup "
        "UNIQUE (user_id, mesh_hash, process_set_hash, analysis_version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_analyses_share ON analyses (share_short_id) "
        "WHERE share_short_id IS NOT NULL"
    )

    # ---- jobs ----
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, unique=True, nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "analysis_id",
            sa.BigInteger,
            sa.ForeignKey("analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("job_type", sa.Text, nullable=False),
        sa.Column(
            "status", sa.Text, nullable=False, server_default="queued"
        ),
        sa.Column("params_json", JSONB, nullable=True),
        sa.Column("result_json", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # ---- usage_events ----
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_key_id",
            sa.BigInteger,
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column(
            "analysis_id",
            sa.BigInteger,
            sa.ForeignKey("analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mesh_hash", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("face_count", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Indexes on usage_events
    op.create_index(
        "ix_usage_events_user_created",
        "usage_events",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_usage_events_apikey_created",
        "usage_events",
        ["api_key_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    # Drop indexes first, then tables in reverse FK order
    op.drop_index("ix_usage_events_apikey_created", table_name="usage_events")
    op.drop_index("ix_usage_events_user_created", table_name="usage_events")
    op.drop_table("usage_events")

    op.drop_table("jobs")

    op.execute("DROP INDEX IF EXISTS ix_analyses_share")
    op.execute(
        "ALTER TABLE analyses DROP CONSTRAINT IF EXISTS uq_analyses_dedup"
    )
    op.drop_index("ix_analyses_user_created", table_name="analyses")
    op.drop_table("analyses")
