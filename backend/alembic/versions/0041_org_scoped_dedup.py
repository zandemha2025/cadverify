"""Scope analysis and cost-decision deduplication to organizations.

Revision ID: 0041_org_scoped_dedup
Revises: 0040_design_studio
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op

revision = "0041_org_scoped_dedup"
down_revision = "0040_design_studio"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")


def upgrade() -> None:
    _timeouts()

    # The prior keys accidentally treated one user's rows as globally unique
    # across every organization they belong to. org_id is already NOT NULL, so
    # replacing each constraint is a metadata/key change with no data backfill.
    op.drop_constraint("uq_analyses_dedup", "analyses", type_="unique")
    op.create_unique_constraint(
        "uq_analyses_dedup",
        "analyses",
        [
            "org_id",
            "user_id",
            "mesh_hash",
            "process_set_hash",
            "analysis_version",
        ],
    )

    op.drop_constraint(
        "uq_cost_decisions_dedup", "cost_decisions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_cost_decisions_dedup",
        "cost_decisions",
        ["org_id", "user_id", "mesh_hash", "params_hash"],
    )


def downgrade() -> None:
    _timeouts()

    op.drop_constraint("uq_analyses_dedup", "analyses", type_="unique")
    op.create_unique_constraint(
        "uq_analyses_dedup",
        "analyses",
        ["user_id", "mesh_hash", "process_set_hash", "analysis_version"],
    )

    op.drop_constraint(
        "uq_cost_decisions_dedup", "cost_decisions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_cost_decisions_dedup",
        "cost_decisions",
        ["user_id", "mesh_hash", "params_hash"],
    )
