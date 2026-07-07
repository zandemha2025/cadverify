"""offline integration run ledger

Revision ID: 0030_integration_runs
Revises: 0029_notifications_inbox
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_integration_runs"
down_revision = "0029_notifications_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")

    op.create_table(
        "integration_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ulid", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False, server_default="dry_run"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_valid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_invalid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("errors_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("ulid", name="uq_integration_runs_ulid"),
    )
    op.create_index(
        "ix_integration_runs_org_created",
        "integration_runs",
        ["org_id", "created_at"],
    )
    op.create_index(
        "ix_integration_runs_org_connector",
        "integration_runs",
        ["org_id", "connector_id"],
    )
    op.create_index(
        "ix_integration_runs_org_status",
        "integration_runs",
        ["org_id", "status"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_integration_runs_org_status", table_name="integration_runs")
    op.drop_index("ix_integration_runs_org_connector", table_name="integration_runs")
    op.drop_index("ix_integration_runs_org_created", table_name="integration_runs")
    op.drop_table("integration_runs")
