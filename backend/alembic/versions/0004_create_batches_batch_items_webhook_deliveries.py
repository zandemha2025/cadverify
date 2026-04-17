"""create batches, batch_items, webhook_deliveries tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    # ---- batches ----
    op.create_table(
        "batches",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
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
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("input_mode", sa.Text, nullable=False),
        sa.Column("manifest_json", JSONB, nullable=True),
        sa.Column("webhook_url", sa.Text, nullable=True),
        sa.Column("webhook_secret", sa.Text, nullable=True),
        sa.Column("total_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("concurrency_limit", sa.Integer, nullable=False, server_default="10"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_batches_user_created", "batches", ["user_id", "created_at"])

    # ---- batch_items ----
    op.create_table(
        "batch_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ulid", sa.Text, unique=True, nullable=False),
        sa.Column(
            "batch_id",
            sa.BigInteger,
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("process_types", sa.Text, nullable=True),
        sa.Column("rule_pack", sa.Text, nullable=True),
        sa.Column("priority", sa.Text, nullable=False, server_default="normal"),
        sa.Column(
            "analysis_id",
            sa.BigInteger,
            sa.ForeignKey("analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_batch_items_batch_status", "batch_items", ["batch_id", "status"]
    )
    op.create_index(
        "ix_batch_items_batch_created", "batch_items", ["batch_id", "created_at"]
    )

    # ---- webhook_deliveries ----
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "batch_id",
            sa.BigInteger,
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("response_code", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_retry",
        "webhook_deliveries",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_retry", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_batch_items_batch_created", table_name="batch_items")
    op.drop_index("ix_batch_items_batch_status", table_name="batch_items")
    op.drop_table("batch_items")
    op.drop_index("ix_batches_user_created", table_name="batches")
    op.drop_table("batches")
