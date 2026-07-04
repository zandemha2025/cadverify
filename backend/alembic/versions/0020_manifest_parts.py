"""declared parts-manifest registry (Aramco GAP 3 — structured bulk onboarding)

Adds ``manifest_parts``: ONE row per ``(org_id, part_id)`` carrying a customer's
USER-DECLARED inventory line — the part number plus demand/program/material
metadata exported from SAP/Excel, usually WITHOUT geometry. This is a THIRD kind
of part identity: not a ``mesh_hash``-keyed catalog part and not a
``ground_truth_records`` cost datum, but a declared inventory line keyed by the
customer's own ``part_id``. It lets a pilot org see its inventory ORGANIZED
immediately and get an honest "how much has geometry we can assess" coverage
number.

Purely ADDITIVE and honestly SEPARATE: a declared row never creates an analysis /
cost decision / part summary and never alters the catalog or triage numbers
(those stay geometry-derived). Coverage's geometry match is a best-effort
normalized-stem convention against uploaded analyses in the same org.

Revision ID: 0020_manifest_parts
Revises: 0019_part_summaries
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "0020_manifest_parts"
down_revision = "0019_part_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "manifest_parts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, nullable=False),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("part_id", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("material_class", sa.Text, nullable=True),
        sa.Column("program", sa.Text, nullable=True),
        sa.Column("parent_assembly", sa.Text, nullable=True),
        sa.Column("units_per_parent", sa.Integer, nullable=True),
        sa.Column("annual_volume", sa.Integer, nullable=True),
        sa.Column("quantity", sa.Integer, nullable=True),
        sa.Column("region", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "org_id", "part_id", name="uq_manifest_parts_org_part"
        ),
    )

    # ULID is the opaque public id — unique across the table.
    op.create_index(
        "ix_manifest_parts_ulid", "manifest_parts", ["ulid"], unique=True
    )
    # by_program rollup: GROUP BY program within an org.
    op.create_index(
        "ix_manifest_parts_org_program", "manifest_parts", ["org_id", "program"]
    )


def downgrade() -> None:
    op.drop_index("ix_manifest_parts_org_program", table_name="manifest_parts")
    op.drop_index("ix_manifest_parts_ulid", table_name="manifest_parts")
    op.drop_table("manifest_parts")
