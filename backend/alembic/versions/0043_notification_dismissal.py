"""Add per-user notification dismissal state.

Revision ID: 0043_notification_dismiss
Revises: 0042_cost_disposition
Create Date: 2026-07-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_notification_dismiss"
down_revision = "0042_cost_disposition"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")


def upgrade() -> None:
    _timeouts()
    op.add_column(
        "notification_reads",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notification_reads_user_dismissed",
        "notification_reads",
        ["user_id", "dismissed_at"],
        unique=False,
    )


def downgrade() -> None:
    _timeouts()
    op.drop_index(
        "ix_notification_reads_user_dismissed",
        table_name="notification_reads",
    )
    op.drop_column("notification_reads", "dismissed_at")
