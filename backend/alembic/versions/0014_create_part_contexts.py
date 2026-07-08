"""declared part-context — user-declared program/assembly/volume (W3.5 rung-1)

Gives every catalog part an optional, USER-DECLARED business context so the
portfolio roll-up can state an honest ``$/year`` instead of only a per-unit
price. Purely additive — one new table; no existing table or row is touched, so
the catalog / portfolio outputs are byte-identical until an org declares a
context for a part.

  * ``part_contexts`` — one row per (org_id, mesh_hash) (unique); ``program`` /
    ``parent_assembly`` / ``units_per_parent`` / ``annual_volume`` all nullable,
    DECLARED by a user (provenance ``user``, never inferred). An index on
    (org_id, program) supports the portfolio's per-program grouping.

Revision ID: 0014_create_part_contexts
Revises: 0013_create_rate_card_versions
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_create_part_contexts"
down_revision = "0013_create_rate_card_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "part_contexts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, nullable=False),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mesh_hash", sa.Text, nullable=False),
        sa.Column("program", sa.Text, nullable=True),
        sa.Column("parent_assembly", sa.Text, nullable=True),
        sa.Column("units_per_parent", sa.Integer, nullable=True),
        sa.Column("annual_volume", sa.Integer, nullable=True),
        sa.Column(
            "created_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_unique_constraint(
        "uq_part_contexts_org_mesh", "part_contexts", ["org_id", "mesh_hash"]
    )
    op.create_unique_constraint(
        "uq_part_contexts_ulid", "part_contexts", ["ulid"]
    )
    op.create_index(
        "ix_part_contexts_org_program", "part_contexts", ["org_id", "program"]
    )


def downgrade() -> None:
    op.drop_index("ix_part_contexts_org_program", table_name="part_contexts")
    op.drop_constraint(
        "uq_part_contexts_ulid", "part_contexts", type_="unique"
    )
    op.drop_constraint(
        "uq_part_contexts_org_mesh", "part_contexts", type_="unique"
    )
    op.drop_table("part_contexts")
