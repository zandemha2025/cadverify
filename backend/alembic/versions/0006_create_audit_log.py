"""Create audit_log table.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "timestamp",
            TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_email", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=False),
        sa.Column("resource_id", sa.Text, nullable=True),
        sa.Column("detail_json", JSONB, nullable=True),
        sa.Column("ip_address", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("file_hash", sa.Text, nullable=True),
        sa.Column("result_summary", sa.Text, nullable=True),
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_user_timestamp", "audit_log", ["user_id", "timestamp"])
    op.create_index("ix_audit_log_action_timestamp", "audit_log", ["action", "timestamp"])


def downgrade() -> None:
    op.drop_table("audit_log")
