"""bom edges — org-scoped multi-level BOM/assembly hierarchy (context Slice 3)

The persisted parent->child product tree a part's environment and total roll up
(handle -> door assembly -> vehicle). Each edge carries ``qty_per_parent`` so the
product along the path to the root is the units of that part per one finished
vehicle; ``annual_volume = rolled_up_multiplier x vehicles_per_year``.

Two honest sources (``source``): ``'assembly_step'`` (derived from a real extracted
STEP assembly's tree — measured instance counts) and ``'bom_csv'`` (a
customer-declared parent/child/qty BOM). A part with NO edges has no tree and the
analysis falls back to the flat declared ``annual_volume`` (byte-identical).

Also adds the OPTIONAL BOM-rollup linkage to ``part_contexts``
(``bom_assembly_key``, ``bom_child_ref``, ``bom_roots_per_year``) — all nullable, so
a context with none set is byte-identical to the pre-Slice-3 shape and still reads
its flat declared volume.

Revision ID: 0037_bom_edges
Revises: 0036_part_signatures
Create Date: 2026-07-09

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037_bom_edges"
down_revision = "0036_part_signatures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.create_table(
        "bom_edges",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("assembly_key", sa.Text(), nullable=False),
        sa.Column("parent_ref", sa.Text(), nullable=True),
        sa.Column("child_ref", sa.Text(), nullable=False),
        sa.Column("child_name", sa.Text(), nullable=True),
        sa.Column(
            "qty_per_parent", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("depth", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "org_id",
            "assembly_key",
            "parent_ref",
            "child_ref",
            name="uq_bom_edges_org_key_parent_child",
        ),
    )
    op.create_index("ix_bom_edges_org_key", "bom_edges", ["org_id", "assembly_key"])
    op.create_index(
        "ix_bom_edges_org_key_child",
        "bom_edges",
        ["org_id", "assembly_key", "child_ref"],
    )

    # Optional BOM-rollup linkage on part_contexts (all nullable → byte-identical
    # when unset). Ties a part to a persisted tree + declares vehicles/year.
    op.add_column(
        "part_contexts", sa.Column("bom_assembly_key", sa.Text(), nullable=True)
    )
    op.add_column(
        "part_contexts", sa.Column("bom_child_ref", sa.Text(), nullable=True)
    )
    op.add_column(
        "part_contexts", sa.Column("bom_roots_per_year", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_column("part_contexts", "bom_roots_per_year")
    op.drop_column("part_contexts", "bom_child_ref")
    op.drop_column("part_contexts", "bom_assembly_key")
    op.drop_index("ix_bom_edges_org_key_child", table_name="bom_edges")
    op.drop_index("ix_bom_edges_org_key", table_name="bom_edges")
    op.drop_table("bom_edges")
