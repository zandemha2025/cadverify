"""org_invites table + users.is_active / users.deactivated_at (org membership beat)

The membership-LIFECYCLE layer on top of the existing tenancy ISOLATION (0009):

  * ``org_invites`` — a single-use, hashed, expiring invitation to join an org.
    ``token_hash`` stores a SHA-256 of the raw token (the raw token is emailed /
    returned to the admin ONCE and never persisted, so a DB leak cannot be
    replayed into a membership). Single-use + expiry are enforced by the accept
    path (``accepted_at``/``revoked_at`` NULL + ``expires_at`` in the future).
  * ``users.is_active`` BOOLEAN NOT NULL default true — the account-level
    deactivation flag (§39). Every existing row backfills to true via the
    server_default, so the platform is byte-identical until an admin flips it.
  * ``users.deactivated_at`` TIMESTAMP NULL — when the account was deactivated
    (audit/forensics; NULL for active accounts).

Purely additive and reversible: no backfill needed, and with no invites issued
and every user active the whole platform behaves exactly as before 0024.

Revision ID: 0024_org_invites_deact
Revises: 0023_ps_makeability
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_org_invites_deact"
down_revision = "0023_ps_makeability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")

    # ── account-level deactivation flag (§39) ──────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "deactivated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    # ── org invitation (single-use, hashed token, expiring) ────────────────
    op.create_table(
        "org_invites",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="member"),
        # SHA-256 hex of the raw token — the raw token is NEVER stored.
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column(
            "expires_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column(
            "created_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "accepted_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "accepted_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "revoked_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_org_invites_role",
        "org_invites",
        "role IN ('admin', 'member', 'viewer')",
    )
    # token_hash is the accept-path lookup key — unique so a hash collision can
    # never resolve two invites.
    op.create_index(
        "ix_org_invites_token_hash", "org_invites", ["token_hash"], unique=True
    )
    # List pending/revoked invites for an org; filter by email for dedup.
    op.create_index("ix_org_invites_org", "org_invites", ["org_id"])
    op.create_index(
        "ix_org_invites_org_email", "org_invites", ["org_id", "email"]
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_org_invites_org_email", table_name="org_invites")
    op.drop_index("ix_org_invites_org", table_name="org_invites")
    op.drop_index("ix_org_invites_token_hash", table_name="org_invites")
    op.drop_table("org_invites")
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "is_active")
