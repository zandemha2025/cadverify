"""governed materials-library asset — versioned, effective-dated, org-scoped (W4 libraries slice 3)

The DB-backed successor to the empty ``RATE_CARD_V0["material_prices"]`` default:
an org-scoped, versioned, effective-dated materials catalog an org admin can
draft and PUBLISH. Purely additive — one new table; no existing table or row is
touched, so the default cost path is byte-identical until an org publishes a
material version AND the ``MATERIAL_LIBRARY_ENABLED`` flag is on.

  * ``material_library_versions`` — (org_id, version) unique; ``status``
    draft/published/archived; ``payload`` JSONB materials-catalog dict
    (``material_prices`` + optional ``materials`` defs); ``effective_from``/
    ``effective_to`` the non-overlapping per-org timeline (publishing closes the
    org's prior open version).

Revision ID: 0017_materials
Revises: 0016_change_requests
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)`` — a longer id fails the
version UPDATE and rolls back the whole upgrade.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_materials"
down_revision = "0016_change_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "material_library_versions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, nullable=False),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("change_note", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "effective_from", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("effective_to", sa.TIMESTAMP(timezone=True), nullable=True),
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
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_unique_constraint(
        "uq_material_library_versions_org_version",
        "material_library_versions",
        ["org_id", "version"],
    )
    op.create_unique_constraint(
        "uq_material_library_versions_ulid",
        "material_library_versions",
        ["ulid"],
    )
    op.create_index(
        "ix_material_library_versions_org_status",
        "material_library_versions",
        ["org_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_material_library_versions_org_status",
        table_name="material_library_versions",
    )
    op.drop_constraint(
        "uq_material_library_versions_ulid",
        "material_library_versions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_material_library_versions_org_version",
        "material_library_versions",
        type_="unique",
    )
    op.drop_table("material_library_versions")
