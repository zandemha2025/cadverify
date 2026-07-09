"""part signatures — org-scoped shape-signature retrieval corpus (identity Slice 1)

Revision ID: 0036_part_signatures
Revises: 0035_connector_credentials
Create Date: 2026-07-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_part_signatures"
down_revision = "0035_connector_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.create_table(
        "part_signatures",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("mesh_hash", sa.Text(), nullable=False),
        # 18-dim MEASURED shape signature (similarity.feature_vector) as JSONB floats.
        sa.Column("signature", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("declared_part_id", sa.Text(), nullable=True),
        sa.Column("declared_name", sa.Text(), nullable=True),
        sa.Column("program", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "org_id", "mesh_hash", name="uq_part_signatures_org_mesh"
        ),
    )
    op.create_index("ix_part_signatures_org", "part_signatures", ["org_id"])


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_part_signatures_org", table_name="part_signatures")
    op.drop_table("part_signatures")
