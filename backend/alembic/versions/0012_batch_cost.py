"""batch cost job type + per-item cost params (W3 batch-cost pipeline)

Teaches the batch pipeline to COST a portfolio, not just DFM-check it. Two
additive shape changes, both backward-safe for the existing DFM path:

  * ``batches.job_type`` — ``'dfm'`` (default) | ``'cost'``. Every existing row
    is DFM by the ``server_default='dfm'`` so no backfill is needed and the DFM
    worker path is byte-identical.
  * ``batch_items`` gains the optional per-item cost knobs a cost batch's CSV
    manifest can carry (``quantities`` as a semicolon list, ``region``,
    ``material_class``, ``shop``) plus ``cost_decision_id`` — the FK to the
    ``cost_decisions`` row a costed item produces (``SET NULL`` so pruning a
    decision never orphans the item; indexed for the results-CSV join). All
    nullable → existing DFM items are untouched.

Revision ID: 0012_batch_cost
Revises: 0011_create_ground_truth_records
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_batch_cost"
down_revision = "0011_create_ground_truth_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    # Job type: every existing batch is DFM (server_default), so no backfill.
    op.add_column(
        "batches",
        sa.Column(
            "job_type", sa.Text, nullable=False, server_default="dfm"
        ),
    )

    # Per-item cost params (all nullable → DFM items unaffected).
    op.add_column(
        "batch_items", sa.Column("quantities", sa.Text, nullable=True)
    )
    op.add_column("batch_items", sa.Column("region", sa.Text, nullable=True))
    op.add_column(
        "batch_items", sa.Column("material_class", sa.Text, nullable=True)
    )
    op.add_column("batch_items", sa.Column("shop", sa.Text, nullable=True))
    op.add_column(
        "batch_items",
        sa.Column(
            "cost_decision_id",
            sa.BigInteger,
            sa.ForeignKey("cost_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_batch_items_cost_decision_id",
        "batch_items",
        ["cost_decision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_batch_items_cost_decision_id", table_name="batch_items"
    )
    op.drop_column("batch_items", "cost_decision_id")
    op.drop_column("batch_items", "shop")
    op.drop_column("batch_items", "material_class")
    op.drop_column("batch_items", "region")
    op.drop_column("batch_items", "quantities")
    op.drop_column("batches", "job_type")
