"""users session version for server-side session revocation

Revision ID: 0028_user_session_version
Revises: 0027_cost_decision_governance
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_user_session_version"
down_revision = "0027_cost_decision_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.add_column(
        "users",
        sa.Column(
            "session_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_column("users", "session_version")
