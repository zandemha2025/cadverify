"""durable notifications inbox

Revision ID: 0029_notifications_inbox
Revises: 0028_user_session_version
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029_notifications_inbox"
down_revision = "0028_user_session_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ulid", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default="info"),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("audience_role", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("dest", sa.Text(), nullable=False, server_default="verify"),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("ulid", name="uq_notifications_ulid"),
        sa.UniqueConstraint(
            "org_id",
            "kind",
            "source_type",
            "source_id",
            name="uq_notifications_source",
        ),
    )
    op.create_index(
        "ix_notifications_org_status_created",
        "notifications",
        ["org_id", "status", "created_at"],
    )
    op.create_index(
        "ix_notifications_org_kind_source",
        "notifications",
        ["org_id", "kind", "source_type", "source_id"],
    )

    op.create_table(
        "notification_reads",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("notification_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "read_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"], ["notifications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "notification_id",
            "user_id",
            name="uq_notification_reads_notification_user",
        ),
    )
    op.create_index(
        "ix_notification_reads_user_read",
        "notification_reads",
        ["user_id", "read_at"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_notification_reads_user_read", table_name="notification_reads")
    op.drop_table("notification_reads")
    op.drop_index("ix_notifications_org_kind_source", table_name="notifications")
    op.drop_index("ix_notifications_org_status_created", table_name="notifications")
    op.drop_table("notifications")
