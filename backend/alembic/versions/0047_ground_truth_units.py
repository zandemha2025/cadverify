"""Preserve the source-unit interpretation of imported costs/quotes."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_ground_truth_units"
down_revision = "0046_trial_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")
    op.add_column("ground_truth_records", sa.Column("source_units", sa.Text, nullable=False, server_default="mm"))
    op.create_check_constraint("ck_ground_truth_source_units", "ground_truth_records", "source_units IN ('mm', 'inch')")


def downgrade() -> None:
    op.drop_constraint("ck_ground_truth_source_units", "ground_truth_records", type_="check")
    op.drop_column("ground_truth_records", "source_units")
