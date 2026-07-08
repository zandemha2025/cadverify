"""cost_decisions governance signoff and staleness metadata

Revision ID: 0027_cost_decision_governance
Revises: 0026_gt_actuals_metadata
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_cost_decision_governance"
down_revision = "0026_gt_actuals_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")

    op.add_column(
        "cost_decisions",
        sa.Column(
            "approval_status",
            sa.Text(),
            nullable=False,
            server_default="unreviewed",
        ),
    )
    op.add_column(
        "cost_decisions",
        sa.Column("approved_by_user_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "cost_decisions",
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column("cost_decisions", sa.Column("approval_note", sa.Text(), nullable=True))
    op.add_column(
        "cost_decisions",
        sa.Column("stale_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column("cost_decisions", sa.Column("stale_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_cost_decisions_approved_by_user",
        "cost_decisions",
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cost_decisions_org_stale",
        "cost_decisions",
        ["org_id", "stale_at"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_cost_decisions_org_stale", table_name="cost_decisions")
    op.execute(
        "ALTER TABLE cost_decisions DROP CONSTRAINT IF EXISTS "
        "fk_cost_decisions_approved_by_user"
    )
    op.drop_column("cost_decisions", "stale_reason")
    op.drop_column("cost_decisions", "stale_at")
    op.drop_column("cost_decisions", "approval_note")
    op.drop_column("cost_decisions", "approved_at")
    op.drop_column("cost_decisions", "approved_by_user_id")
    op.drop_column("cost_decisions", "approval_status")
