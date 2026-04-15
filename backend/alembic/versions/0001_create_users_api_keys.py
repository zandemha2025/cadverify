"""create users + api_keys tables

Revision ID: 0001_create_users_api_keys
Revises:
Create Date: 2026-04-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_create_users_api_keys"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("email_lower", sa.Text, unique=True, nullable=False),
        sa.Column("google_sub", sa.Text, unique=True, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "disposable_flag",
            sa.Boolean,
            server_default="false",
            nullable=False,
        ),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False, server_default="Default"),
        sa.Column("prefix", sa.Text, nullable=False),
        sa.Column("hmac_index", sa.Text, unique=True, nullable=False),
        sa.Column("secret_hash", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index(
        "ix_api_keys_hmac_index", "api_keys", ["hmac_index"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_hmac_index", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("users")
