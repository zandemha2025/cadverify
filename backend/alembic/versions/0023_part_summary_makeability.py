"""makeability projection on part_summaries (Phase D — triage at scale)

Extends the materialized ``part_summaries`` projection (Aramco GAP 2) with the
machine-inventory MAKEABILITY lens so the whole-inventory in-house breakdown and
the capability-investment ranking are SQL aggregates, not per-part engine reruns.

Adds (all NULL/‐defaulted so existing rows need no backfill and the legacy
columns/behaviour are byte-identical):

  * ``makeability_verdict`` TEXT NULL — the §0 lattice verdict last computed for
    this part (makeable_in_house | makeable_with_secondary_op |
    makeable_not_on_owned | makeable_outsource_only | environment_excluded |
    not_makeable | unknown). NULL when the part was costed with NO declared
    inventory/environment (the Phase-C verification block is absent) — honestly
    "not evaluated", never a fabricated verdict.
  * ``in_house_makeable`` BOOLEAN NULL — True iff verdict ∈ {makeable_in_house,
    makeable_with_secondary_op}; NULL when unknown/unevaluated.
  * ``makeability_bucket`` TEXT NOT NULL default 'unknown' — the D3 triage bucket
    (makeable_in_house | makeable_outside | needs_capability | not_makeable |
    unknown | geometry_invalid), the single GROUP-BY key for the scaled rollup.
  * ``makeability_stale`` BOOLEAN NOT NULL default false — set true (in bulk) when
    the org's machine inventory changes so a verdict computed against the OLD
    inventory is never served as fresh; cleared when the part is re-costed.
  * ``unlock_process`` / ``unlock_gate`` / ``unlock_single`` / ``unlock_need_num``
    / ``unlock_need_label`` — the denormalized single primary acquisition that
    would unlock a currently-blocked part (D4 capability-investment ranking):
    which process to acquire/upgrade, the binding gate, whether ONE acquisition
    suffices, and the numeric/categorical requirement — all derived from the REAL
    stored FitFailure gap data.
  * ``makeability_gap`` JSONB NULL — the full per-part gap detail (kind, process,
    gate, single, and the FitFailure list {gate,axis,need,have,human}) powering
    the D4 drill-down; no fabricated fields.

Indexes (org-leading, per the D3/D4 access patterns):
  * ``ix_part_summaries_org_mkbucket`` (org_id, makeability_bucket, updated_at
    DESC, mesh_hash DESC) — the rollup GROUP BY + per-bucket keyset drill-down.
  * ``ix_part_summaries_org_unlock`` (org_id, unlock_process, unlock_gate) — the
    capability-investment GROUP BY + per-acquisition drill-down.

Purely ADDITIVE and reversible. Absent inventory the whole makeability lens reads
'unknown' and every legacy column/read is byte-identical.

Revision ID: 0023_ps_makeability
Revises: 0022_part_context_env
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0023_ps_makeability"
down_revision = "0022_part_context_env"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.add_column(
        "part_summaries",
        sa.Column("makeability_verdict", sa.Text, nullable=True),
    )
    op.add_column(
        "part_summaries",
        sa.Column("in_house_makeable", sa.Boolean, nullable=True),
    )
    op.add_column(
        "part_summaries",
        sa.Column(
            "makeability_bucket",
            sa.Text,
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "part_summaries",
        sa.Column(
            "makeability_stale",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "part_summaries",
        sa.Column("unlock_process", sa.Text, nullable=True),
    )
    op.add_column(
        "part_summaries",
        sa.Column("unlock_gate", sa.Text, nullable=True),
    )
    op.add_column(
        "part_summaries",
        sa.Column("unlock_single", sa.Boolean, nullable=True),
    )
    op.add_column(
        "part_summaries",
        sa.Column("unlock_need_num", sa.Float, nullable=True),
    )
    op.add_column(
        "part_summaries",
        sa.Column("unlock_need_label", sa.Text, nullable=True),
    )
    op.add_column(
        "part_summaries",
        sa.Column("makeability_gap", JSONB, nullable=True),
    )

    # D3 scaled rollup: GROUP BY (org_id, makeability_bucket) + per-bucket keyset
    # drill-down on (updated_at DESC, mesh_hash DESC).
    op.create_index(
        "ix_part_summaries_org_mkbucket",
        "part_summaries",
        [
            "org_id",
            "makeability_bucket",
            sa.text("updated_at DESC"),
            sa.text("mesh_hash DESC"),
        ],
    )
    # D4 capability-investment: GROUP BY (org_id, unlock_process, unlock_gate) +
    # per-acquisition drill-down narrowing.
    op.create_index(
        "ix_part_summaries_org_unlock",
        "part_summaries",
        ["org_id", "unlock_process", "unlock_gate"],
    )


def downgrade() -> None:
    op.drop_index("ix_part_summaries_org_unlock", table_name="part_summaries")
    op.drop_index("ix_part_summaries_org_mkbucket", table_name="part_summaries")
    op.drop_column("part_summaries", "makeability_gap")
    op.drop_column("part_summaries", "unlock_need_label")
    op.drop_column("part_summaries", "unlock_need_num")
    op.drop_column("part_summaries", "unlock_single")
    op.drop_column("part_summaries", "unlock_gate")
    op.drop_column("part_summaries", "unlock_process")
    op.drop_column("part_summaries", "makeability_stale")
    op.drop_column("part_summaries", "makeability_bucket")
    op.drop_column("part_summaries", "in_house_makeable")
    op.drop_column("part_summaries", "makeability_verdict")
