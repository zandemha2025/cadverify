"""create cost_decisions table (persist should-cost / make-vs-buy decision)

Persists the flagship cost decision as a durable, exportable, shareable,
comparable artifact (Phase 2 gap #3). Mirrors the analyses table: JSONB
result_json holds the full report_to_dict() glass-box artifact verbatim; a
few columns are denormalized off it for listing/filtering. Dedup key is
(user_id, mesh_hash, params_hash); share_short_id gets a partial unique index.

Revision ID: 0008_create_cost_decisions
Revises: 0007
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008_create_cost_decisions"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safety: cap migration statement duration
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "cost_decisions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, unique=True, nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_key_id",
            sa.BigInteger,
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mesh_hash", sa.Text, nullable=False),
        sa.Column("params_hash", sa.Text, nullable=False),
        sa.Column("engine_version", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("file_type", sa.Text, nullable=False),
        sa.Column("result_json", JSONB, nullable=False),
        sa.Column("make_now_process", sa.Text, nullable=True),
        sa.Column("crossover_qty", sa.Float, nullable=True),
        sa.Column("quantities", JSONB, nullable=True),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column(
            "is_public", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("share_short_id", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Listing index (newest-first per user)
    op.create_index(
        "ix_cost_decisions_user_created",
        "cost_decisions",
        ["user_id", sa.text("created_at DESC")],
    )
    # Dedup: same user + same file + same cost params == same decision
    op.execute(
        "ALTER TABLE cost_decisions ADD CONSTRAINT uq_cost_decisions_dedup "
        "UNIQUE (user_id, mesh_hash, params_hash)"
    )
    # Partial unique index on the public share short id (mirror analyses)
    op.execute(
        "CREATE UNIQUE INDEX ix_cost_decisions_share ON cost_decisions "
        "(share_short_id) WHERE share_short_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cost_decisions_share")
    op.execute(
        "ALTER TABLE cost_decisions DROP CONSTRAINT IF EXISTS uq_cost_decisions_dedup"
    )
    op.drop_index(
        "ix_cost_decisions_user_created", table_name="cost_decisions"
    )
    op.drop_table("cost_decisions")
