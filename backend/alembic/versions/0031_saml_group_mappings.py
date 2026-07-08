"""saml group-to-org-role mappings

Revision ID: 0031_saml_group_mappings
Revises: 0030_integration_runs
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_saml_group_mappings"
down_revision = "0030_integration_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")

    op.create_table(
        "saml_group_mappings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("attribute_name", sa.Text(), nullable=False),
        sa.Column("group_value", sa.Text(), nullable=False),
        sa.Column("org_role", sa.Text(), nullable=False, server_default="viewer"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
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
        sa.CheckConstraint(
            "org_role IN ('viewer','member','admin')",
            name="ck_saml_group_mappings_org_role",
        ),
        sa.UniqueConstraint(
            "org_id",
            "attribute_name",
            "group_value",
            name="uq_saml_group_mappings_org_attr_value",
        ),
    )
    op.create_index(
        "ix_saml_group_mappings_org",
        "saml_group_mappings",
        ["org_id"],
    )
    op.create_index(
        "ix_saml_group_mappings_attr_value",
        "saml_group_mappings",
        ["attribute_name", "group_value"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_saml_group_mappings_attr_value", table_name="saml_group_mappings")
    op.drop_index("ix_saml_group_mappings_org", table_name="saml_group_mappings")
    op.drop_table("saml_group_mappings")
