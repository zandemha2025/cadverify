"""connector credentials

Revision ID: 0035_connector_credentials
Revises: 0034_scim_identities
Create Date: 2026-07-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035_connector_credentials"
down_revision = "0034_scim_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.create_table(
        "connector_credential_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ulid", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("auth_type", sa.Text(), nullable=False),
        sa.Column("encrypted_secret_json", sa.Text(), nullable=False),
        sa.Column("secret_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("ulid", name="uq_connector_credentials_ulid"),
        sa.UniqueConstraint(
            "org_id",
            "connector_id",
            "label",
            name="uq_connector_credentials_org_connector_label",
        ),
    )
    op.create_index(
        "ix_connector_credentials_org_connector",
        "connector_credential_profiles",
        ["org_id", "connector_id"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index(
        "ix_connector_credentials_org_connector",
        table_name="connector_credential_profiles",
    )
    op.drop_table("connector_credential_profiles")
