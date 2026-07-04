"""governed shop-profile asset — versioned, effective-dated, per-slug (W4 libraries slice 2)

The DB-backed successor to the read-only ``backend/data/shop_profiles/*.json``
flat files: an org-scoped, versioned, effective-dated shop-calibration asset an
org admin can draft and PUBLISH per SLUG. Purely additive — one new table; no
existing table or row is touched, so the default cost path (the flat-file
``resolve_shop`` allowlist) is byte-identical until an org publishes a shop
version for a slug AND the ``SHOP_LIBRARY_ENABLED`` flag is on.

  * ``shop_profile_versions`` — (org_id, version) unique; ``slug`` the shop
    identifier the cost API references; ``status`` draft/published/archived;
    ``payload`` JSONB shop-overrides dict; ``effective_from``/``effective_to`` the
    non-overlapping per-(org, slug) timeline (publishing closes that slug's prior
    open version).

Revision ID: 0015_shop_profiles
Revises: 0014_create_part_contexts
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's ``alembic_version.
version_num`` column is ``varchar(32)`` — a longer id (e.g. the descriptive
``0015_create_shop_profile_versions``, 33 chars) fails the version UPDATE and
rolls back the whole upgrade.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_shop_profiles"
down_revision = "0014_create_part_contexts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "shop_profile_versions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, nullable=False),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("slug", sa.Text, nullable=False),
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
        "uq_shop_profile_versions_org_version",
        "shop_profile_versions",
        ["org_id", "version"],
    )
    op.create_unique_constraint(
        "uq_shop_profile_versions_ulid", "shop_profile_versions", ["ulid"]
    )
    op.create_index(
        "ix_shop_profile_versions_org_status",
        "shop_profile_versions",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_shop_profile_versions_org_slug",
        "shop_profile_versions",
        ["org_id", "slug"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shop_profile_versions_org_slug", table_name="shop_profile_versions"
    )
    op.drop_index(
        "ix_shop_profile_versions_org_status", table_name="shop_profile_versions"
    )
    op.drop_constraint(
        "uq_shop_profile_versions_ulid", "shop_profile_versions", type_="unique"
    )
    op.drop_constraint(
        "uq_shop_profile_versions_org_version",
        "shop_profile_versions",
        type_="unique",
    )
    op.drop_table("shop_profile_versions")
