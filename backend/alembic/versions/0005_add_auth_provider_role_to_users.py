"""add auth_provider and role columns to users table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "auth_provider",
            sa.Text(),
            nullable=False,
            server_default="google",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Text(),
            nullable=False,
            server_default="analyst",
        ),
    )
    # CHECK constraint: role must be one of viewer, analyst, admin
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('viewer', 'analyst', 'admin')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
    op.drop_column("users", "auth_provider")
