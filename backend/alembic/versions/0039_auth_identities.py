"""Bind federated logins to immutable provider identities.

Revision ID: 0039_auth_identities
Revises: 0038_pilot_receipts
Create Date: 2026-07-12

Email addresses and OIDC preferred usernames are mutable and can be reassigned.
This table makes ``(provider, issuer, subject)`` the authentication identity;
email remains display/contact metadata and is never sufficient to rebind an
existing account.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_auth_identities"
down_revision = "0038_pilot_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email_at_link", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_login_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('oidc', 'saml')", name="ck_auth_identities_provider"
        ),
        sa.UniqueConstraint(
            "provider",
            "issuer",
            "subject",
            name="uq_auth_identity_provider_issuer_subject",
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "issuer",
            name="uq_auth_identity_user_provider_issuer",
        ),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")
    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")
