"""Immutable source-linked engineering packages.

Revision ID: 0047_engineering_packages
Revises: 0046_trial_plan
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0047_engineering_packages"
down_revision = "0046_trial_plan"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")
    op.create_table("engineering_packages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("org_id", sa.Text(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("series_id", sa.Text(), nullable=False),
        sa.Column("mesh_hash", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "series_id", "version", name="uq_engineering_package_version"),
        sa.CheckConstraint("version > 0", name="ck_engineering_package_version"),
        sa.CheckConstraint("state IN ('draft', 'issued')", name="ck_engineering_package_state"),
    )
    op.create_index("ix_engineering_packages_part", "engineering_packages", ["org_id", "mesh_hash", "id"])
    op.create_index("ix_engineering_packages_latest", "engineering_packages", ["org_id", "id"], postgresql_where=sa.text("is_latest"))
    op.create_index("uq_engineering_packages_latest", "engineering_packages", ["org_id", "series_id"], unique=True, postgresql_where=sa.text("is_latest"))


def downgrade():
    op.drop_table("engineering_packages")
