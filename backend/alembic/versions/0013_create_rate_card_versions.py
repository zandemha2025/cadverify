"""governed rate-card asset — versioned, effective-dated (W4 libraries slice 1)

Replaces the hardcoded ``RATE_CARD_V0`` dict (no API, long-horizon-plan §W4)
with a DB-backed, org-scoped, versioned, effective-dated rate table an org admin
can draft and PUBLISH. Purely additive — one new table; no existing table or row
is touched, so the default cost path (hardcoded ``RATE_CARD_V0``) is byte-identical
until an org publishes a card AND the ``RATE_LIBRARY_ENABLED`` flag is on.

  * ``rate_card_versions`` — (org_id, version) unique; ``status`` draft/published/
    archived; ``payload`` JSONB full rate table; ``effective_from``/``effective_to``
    the non-overlapping timeline (publishing closes the prior open version).

Revision ID: 0013_create_rate_card_versions
Revises: 0012_batch_cost
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_create_rate_card_versions"
down_revision = "0012_batch_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "rate_card_versions",
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
        "uq_rate_card_versions_org_version",
        "rate_card_versions",
        ["org_id", "version"],
    )
    op.create_unique_constraint(
        "uq_rate_card_versions_ulid", "rate_card_versions", ["ulid"]
    )
    op.create_index(
        "ix_rate_card_versions_org_status",
        "rate_card_versions",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_rate_card_versions_org_effective",
        "rate_card_versions",
        ["org_id", "effective_from"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rate_card_versions_org_effective", table_name="rate_card_versions"
    )
    op.drop_index(
        "ix_rate_card_versions_org_status", table_name="rate_card_versions"
    )
    op.drop_constraint(
        "uq_rate_card_versions_ulid", "rate_card_versions", type_="unique"
    )
    op.drop_constraint(
        "uq_rate_card_versions_org_version",
        "rate_card_versions",
        type_="unique",
    )
    op.drop_table("rate_card_versions")
