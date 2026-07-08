"""governance change-request workflow over the governed libraries (W4)

The org-scoped record that gates "change request -> review -> publish" over the
versioned rate-card and shop-profile libraries: a member PROPOSES a draft
version for review; an org admin APPROVES it (which publishes the draft via the
library's existing ``publish_version`` path) or REJECTS it (draft stays a draft).

  * ``change_requests`` — (org_id, status) indexed; ``asset_type``
    (rate_card|shop_profile) + ``target_version_id`` identify the DRAFT being
    proposed (NOT a cross-table FK — asset_type dispatches which library owns
    the id); ``status`` proposed/approved/rejected; ``proposed_by`` /
    ``reviewed_by`` FK users SET NULL; ``created_at`` / ``decided_at`` the
    timeline.

Purely additive — one new table; no existing table or row is touched.

Revision ID: 0016_change_requests
Revises: 0015_shop_profiles
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's ``alembic_version.
version_num`` column is ``varchar(32)`` — a longer id fails the version UPDATE
and rolls back the whole upgrade. ``0016_change_requests`` is 20 chars.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_change_requests"
down_revision = "0015_shop_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "change_requests",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, nullable=False),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.Text, nullable=False),
        sa.Column("target_version_id", sa.BigInteger, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="proposed"),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "proposed_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by",
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
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_unique_constraint(
        "uq_change_requests_ulid", "change_requests", ["ulid"]
    )
    op.create_index(
        "ix_change_requests_org_status",
        "change_requests",
        ["org_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_change_requests_org_status", table_name="change_requests")
    op.drop_constraint(
        "uq_change_requests_ulid", "change_requests", type_="unique"
    )
    op.drop_table("change_requests")
