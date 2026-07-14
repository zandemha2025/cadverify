"""Create org-scoped direct-upload lifecycle records.

Revision ID: 0044_direct_uploads
Revises: 0043_notification_dismiss
Create Date: 2026-07-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_direct_uploads"
down_revision = "0043_notification_dismiss"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")


def upgrade() -> None:
    _timeouts()
    op.create_table(
        "direct_uploads",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ulid", sa.Text, nullable=False, unique=True),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key_hash", sa.Text, nullable=False),
        sa.Column("request_fingerprint", sa.Text, nullable=False),
        sa.Column(
            "batch_id",
            sa.BigInteger,
            sa.ForeignKey("batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="initiated"),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("expected_size_bytes", sa.BigInteger, nullable=False),
        sa.Column("expected_checksum_sha256", sa.Text, nullable=False),
        sa.Column("actual_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("part_size_bytes", sa.BigInteger, nullable=False),
        sa.Column("part_count", sa.Integer, nullable=False),
        sa.Column("object_key", sa.Text, nullable=False),
        sa.Column("multipart_upload_id", sa.Text, nullable=False),
        sa.Column("object_etag", sa.Text, nullable=True),
        sa.Column("prepare_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_code", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("attached_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("preparation_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("prepared_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("checksum_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("storage_cleaned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('batch_zip')",
            name="ck_direct_uploads_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('initiated', 'completing', 'completed', 'attached', 'preparing', "
            "'prepared', 'consumed', 'aborted', 'expired', 'failed')",
            name="ck_direct_uploads_status",
        ),
        sa.CheckConstraint(
            "expected_size_bytes > 0",
            name="ck_direct_uploads_expected_size",
        ),
        sa.CheckConstraint(
            "part_size_bytes >= 5242880",
            name="ck_direct_uploads_part_size",
        ),
        sa.CheckConstraint(
            "part_count >= 1 AND part_count <= 10000",
            name="ck_direct_uploads_part_count",
        ),
        sa.CheckConstraint(
            "length(idempotency_key_hash) = 64 AND "
            "length(request_fingerprint) = 64 AND "
            "length(expected_checksum_sha256) = 64",
            name="ck_direct_uploads_hash_lengths",
        ),
        sa.UniqueConstraint("batch_id", name="uq_direct_uploads_batch_id"),
        sa.UniqueConstraint("object_key", name="uq_direct_uploads_object_key"),
        sa.UniqueConstraint(
            "org_id",
            "idempotency_key_hash",
            name="uq_direct_uploads_org_idempotency",
        ),
    )
    op.create_index(
        "ix_direct_uploads_org_status",
        "direct_uploads",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_direct_uploads_user_created",
        "direct_uploads",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_direct_uploads_status_expires",
        "direct_uploads",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    _timeouts()
    op.drop_index("ix_direct_uploads_status_expires", table_name="direct_uploads")
    op.drop_index("ix_direct_uploads_user_created", table_name="direct_uploads")
    op.drop_index("ix_direct_uploads_org_status", table_name="direct_uploads")
    op.drop_table("direct_uploads")
