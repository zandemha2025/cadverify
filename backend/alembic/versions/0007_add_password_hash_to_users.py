"""add password_hash to users (email+password credential)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
