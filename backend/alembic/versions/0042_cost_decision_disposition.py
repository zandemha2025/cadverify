"""Persist the user's four-way sourcing disposition on cost decisions.

Revision ID: 0042_cost_disposition
Revises: 0041_org_scoped_dedup
Create Date: 2026-07-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_cost_disposition"
down_revision = "0041_org_scoped_dedup"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")


def upgrade() -> None:
    _timeouts()
    op.add_column(
        "cost_decisions",
        sa.Column("user_disposition", sa.Text(), nullable=True),
    )
    op.add_column(
        "cost_decisions",
        sa.Column("disposition_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "cost_decisions",
        sa.Column(
            "disposition_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "cost_decisions",
        sa.Column(
            "disposition_updated_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_cost_decisions_disposition",
        "cost_decisions",
        "user_disposition IS NULL OR user_disposition IN "
        "('inhouse', 'outside', 'acquire', 'redesign')",
    )


def downgrade() -> None:
    _timeouts()
    op.drop_constraint(
        "ck_cost_decisions_disposition",
        "cost_decisions",
        type_="check",
    )
    op.drop_column("cost_decisions", "disposition_updated_by_user_id")
    op.drop_column("cost_decisions", "disposition_updated_at")
    op.drop_column("cost_decisions", "disposition_note")
    op.drop_column("cost_decisions", "user_disposition")
