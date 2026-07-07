"""add validation actuals metadata to ground_truth_records

Revision ID: 0026_gt_actuals_metadata
Revises: 0025_invite_invited_user
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_gt_actuals_metadata"
down_revision = "0025_invite_invited_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.add_column(
        "ground_truth_records",
        sa.Column("source_type", sa.Text(), nullable=False, server_default="actual"),
    )
    op.add_column("ground_truth_records", sa.Column("vendor_quote_id", sa.Text(), nullable=True))
    op.add_column("ground_truth_records", sa.Column("invoice_date", sa.Date(), nullable=True))
    op.add_column("ground_truth_records", sa.Column("actual_machine_hours", sa.Float(), nullable=True))
    op.add_column("ground_truth_records", sa.Column("actual_setup_hours", sa.Float(), nullable=True))
    op.add_column("ground_truth_records", sa.Column("actual_labor_hours", sa.Float(), nullable=True))
    op.add_column("ground_truth_records", sa.Column("actual_inspection_hours", sa.Float(), nullable=True))
    op.add_column("ground_truth_records", sa.Column("actual_cycle_seconds", sa.Float(), nullable=True))
    op.add_column("ground_truth_records", sa.Column("evidence_sha256", sa.Text(), nullable=True))
    op.add_column("ground_truth_records", sa.Column("evidence_uri", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ground_truth_records", "evidence_uri")
    op.drop_column("ground_truth_records", "evidence_sha256")
    op.drop_column("ground_truth_records", "actual_cycle_seconds")
    op.drop_column("ground_truth_records", "actual_inspection_hours")
    op.drop_column("ground_truth_records", "actual_labor_hours")
    op.drop_column("ground_truth_records", "actual_setup_hours")
    op.drop_column("ground_truth_records", "actual_machine_hours")
    op.drop_column("ground_truth_records", "invoice_date")
    op.drop_column("ground_truth_records", "vendor_quote_id")
    op.drop_column("ground_truth_records", "source_type")
