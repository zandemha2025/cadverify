"""rfq supplier evidence packages

Revision ID: 0032_rfq_packages
Revises: 0031_saml_group_mappings
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032_rfq_packages"
down_revision = "0031_saml_group_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")

    op.create_table(
        "rfq_packages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ulid", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("supplier_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="generated"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unvalidated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "raw_cad_included",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "live_supplier_send",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("items_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('generated','archived')",
            name="ck_rfq_packages_status",
        ),
        sa.UniqueConstraint("ulid", name="uq_rfq_packages_ulid"),
    )
    op.create_index(
        "ix_rfq_packages_org_created",
        "rfq_packages",
        ["org_id", "created_at"],
    )
    op.create_index(
        "ix_rfq_packages_org_status",
        "rfq_packages",
        ["org_id", "status"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_rfq_packages_org_status", table_name="rfq_packages")
    op.drop_index("ix_rfq_packages_org_created", table_name="rfq_packages")
    op.drop_table("rfq_packages")
