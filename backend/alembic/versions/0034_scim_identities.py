"""scim identities

Revision ID: 0034_scim_identities
Revises: 0033_integration_proof_levels
Create Date: 2026-07-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034_scim_identities"
down_revision = "0033_integration_proof_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.create_table(
        "scim_identities",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("org_role", sa.Text(), nullable=False, server_default="viewer"),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_scim_identities_org_user"),
        sa.UniqueConstraint(
            "org_id", "external_id", name="uq_scim_identities_org_external"
        ),
        sa.CheckConstraint(
            "org_role IN ('viewer','member','admin')",
            name="ck_scim_identities_org_role",
        ),
    )
    op.create_index(
        "ix_scim_identities_org_active",
        "scim_identities",
        ["org_id", "active"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_scim_identities_org_active", table_name="scim_identities")
    op.drop_table("scim_identities")
