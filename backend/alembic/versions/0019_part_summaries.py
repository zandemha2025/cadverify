"""materialized per-part catalog projection (Aramco GAP 2 — scale to millions)

Adds ``part_summaries``: ONE row per ``(org_id, mesh_hash)`` carrying the derived
makeability ``triage_bucket``, the recommended ``route_process``, the two
artifact-presence flags, the derived recency (``updated_at`` = max(analysis,
cost) created_at), and the full ``catalog_service.derive_row`` dict as
``row_json``. Maintained on write at the analysis + cost-decision persist funnels
so the whole-inventory triage COUNT is a SQL ``GROUP BY`` (O(buckets), scales to
millions) and the catalog grid is keyset-paginated — instead of scanning the 2000
newest raw rows and folding in Python.

Purely ADDITIVE: the legacy fold path (``catalog_service._fold_org_parts`` and
friends) is untouched and remains the byte-identity oracle. Nothing about any
served number changes; this table is a projection that is proven equal to the
legacy output on identical data.

Revision ID: 0019_part_summaries
Revises: 0018_gt_geometry
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0019_part_summaries"
down_revision = "0018_gt_geometry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "part_summaries",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mesh_hash", sa.Text, nullable=False),
        sa.Column("triage_bucket", sa.Text, nullable=False),
        sa.Column("route_process", sa.Text, nullable=True),
        sa.Column(
            "has_analysis", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column(
            "has_cost", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("row_json", JSONB, nullable=False),
        sa.UniqueConstraint(
            "org_id", "mesh_hash", name="uq_part_summaries_org_mesh"
        ),
    )

    # Triage rollup: GROUP BY triage_bucket within an org.
    op.create_index(
        "ix_part_summaries_org_bucket",
        "part_summaries",
        ["org_id", "triage_bucket"],
    )
    # Keyset pagination of the grid: (updated_at DESC, mesh_hash DESC).
    op.create_index(
        "ix_part_summaries_org_keyset",
        "part_summaries",
        ["org_id", sa.text("updated_at DESC"), sa.text("mesh_hash DESC")],
    )
    # by_process rollup: GROUP BY route_process within an org.
    op.create_index(
        "ix_part_summaries_org_route",
        "part_summaries",
        ["org_id", "route_process"],
    )


def downgrade() -> None:
    op.drop_index("ix_part_summaries_org_route", table_name="part_summaries")
    op.drop_index("ix_part_summaries_org_keyset", table_name="part_summaries")
    op.drop_index("ix_part_summaries_org_bucket", table_name="part_summaries")
    op.drop_table("part_summaries")
