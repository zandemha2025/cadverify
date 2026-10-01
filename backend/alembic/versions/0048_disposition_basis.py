"""Bind a human sourcing outcome to its computed process/material/quantity."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0048_disposition_basis"
down_revision = "0047_ground_truth_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")
    op.add_column("cost_decisions", sa.Column("disposition_basis", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("cost_decisions", "disposition_basis")
