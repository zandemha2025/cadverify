"""Add unique index on (analysis_id, job_type) for job idempotency.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5s'")
    op.create_index(
        "ix_jobs_idempotency",
        "jobs",
        ["analysis_id", "job_type"],
        unique=True,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_idempotency", table_name="jobs")
