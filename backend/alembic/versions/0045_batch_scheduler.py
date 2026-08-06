"""Bound batch scheduling and persist item retry leases.

Revision ID: 0045_batch_scheduler
Revises: 0044_direct_uploads
Create Date: 2026-07-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_batch_scheduler"
down_revision = "0044_direct_uploads"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")


def upgrade() -> None:
    _timeouts()
    # Normalize legacy rows before installing the invariant. Existing API paths
    # intended these values, but older schemas did not enforce them.
    op.execute(
        "UPDATE batches SET concurrency_limit = 10 "
        "WHERE concurrency_limit < 1 OR concurrency_limit > 12"
    )
    op.execute(
        "UPDATE batch_items SET priority = 'normal' "
        "WHERE priority NOT IN ('high', 'normal', 'low')"
    )
    op.add_column(
        "batch_items",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "batch_items",
        sa.Column("lease_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_batches_concurrency_limit",
        "batches",
        "concurrency_limit >= 1 AND concurrency_limit <= 12",
    )
    op.create_check_constraint(
        "ck_batch_items_priority",
        "batch_items",
        "priority IN ('high', 'normal', 'low')",
    )
    op.create_check_constraint(
        "ck_batch_items_attempt_count",
        "batch_items",
        "attempt_count >= 0 AND attempt_count <= 3",
    )


def downgrade() -> None:
    _timeouts()
    op.drop_constraint(
        "ck_batch_items_attempt_count", "batch_items", type_="check"
    )
    op.drop_constraint("ck_batch_items_priority", "batch_items", type_="check")
    op.drop_constraint(
        "ck_batches_concurrency_limit", "batches", type_="check"
    )
    op.drop_column("batch_items", "lease_started_at")
    op.drop_column("batch_items", "attempt_count")
