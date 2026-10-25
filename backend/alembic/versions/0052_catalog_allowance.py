"""Free catalog-run allowance: one row per distinct part an account ran.

A work-email account gets its first catalog parts free (separate from its
single-part checks). Each distinct part (the same file identity as a check:
filename and bytes) holds one row, so a re-run of the same file never counts
twice. A part is ``reserved`` while its batch item runs and ``counted`` once it
completes; a part that fails or is skipped gives its row back. Deleting the
batch or the part keeps the row (the slot stays used).

Revision ID: 0052_catalog_allowance
Revises: 0051_self_serve_plans
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "0052_catalog_allowance"
down_revision = "0051_self_serve_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "catalog_parts",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("file_hash", sa.Text(), primary_key=True),
        sa.Column("batch_id", sa.BigInteger(), sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_item_id", sa.BigInteger(), sa.ForeignKey("batch_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("state IN ('reserved', 'counted')", name="ck_catalog_parts_state"),
    )
    op.create_index("ix_catalog_parts_batch_item", "catalog_parts", ["batch_item_id"])


def downgrade():
    op.drop_index("ix_catalog_parts_batch_item", table_name="catalog_parts")
    op.drop_table("catalog_parts")
