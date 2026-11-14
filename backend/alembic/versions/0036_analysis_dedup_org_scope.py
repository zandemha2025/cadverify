"""scope analysis and cost-decision deduplication to the active organization

Revision ID: 0036_analysis_dedup_org_scope
Revises: 0035_connector_credentials
Create Date: 2026-09-02
"""
from __future__ import annotations

from alembic import op

revision = "0036_analysis_dedup_org_scope"
down_revision = "0035_connector_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_constraint("uq_analyses_dedup", "analyses", type_="unique")
    op.create_unique_constraint(
        "uq_analyses_dedup",
        "analyses",
        ["org_id", "user_id", "mesh_hash", "process_set_hash", "analysis_version"],
    )
    op.drop_constraint("uq_cost_decisions_dedup", "cost_decisions", type_="unique")
    op.create_unique_constraint(
        "uq_cost_decisions_dedup",
        "cost_decisions",
        ["org_id", "user_id", "mesh_hash", "params_hash"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_constraint("uq_cost_decisions_dedup", "cost_decisions", type_="unique")
    op.create_unique_constraint(
        "uq_cost_decisions_dedup",
        "cost_decisions",
        ["user_id", "mesh_hash", "params_hash"],
    )
    op.drop_constraint("uq_analyses_dedup", "analyses", type_="unique")
    op.create_unique_constraint(
        "uq_analyses_dedup",
        "analyses",
        ["user_id", "mesh_hash", "process_set_hash", "analysis_version"],
    )
