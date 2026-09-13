"""Trial plans: users.plan column; owner account (id 1) is pilot/unlimited.

Revision ID: 0046_trial_plan
Revises: 0045_batch_scheduler
Create Date: 2026-09-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_trial_plan"
down_revision = "0045_batch_scheduler"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")


def upgrade() -> None:
    _timeouts()
    op.add_column(
        "users",
        sa.Column("plan", sa.Text(), server_default="trial", nullable=False),
    )
    # Owner/demo account: pilot plan, never trial-gated (demo day depends on it).
    op.execute("UPDATE users SET plan = 'pilot' WHERE id = 1")


def downgrade() -> None:
    _timeouts()
    op.drop_column("users", "plan")
