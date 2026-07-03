"""create ground_truth_records table (W5 flywheel — durable real-quote store)

The org-scoped, durable home for the costing ground-truth loop's
``GroundTruthRecord``. Real cost/quotes land here via the ingest API instead of
a Python REPL; recalibration reads them (WHERE org_id = caller-org) to fit the
served Calibration / ResidualModel. ``stand_in`` defaults false (the API is for
REAL data); a true row can shape a band's spread but never validates it (rail
enforced in the costing layer). Dedup (last write wins on
part+process+qty+shop within an org) is enforced in the service, mirroring
``groundtruth.add_record``.

Revision ID: 0011_create_ground_truth_records
Revises: 0010_superadmin_role
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_create_ground_truth_records"
down_revision = "0010_superadmin_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "ground_truth_records",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, unique=True, nullable=False),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("part_id", sa.Text, nullable=False),
        sa.Column("process", sa.Text, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("actual_unit_cost_usd", sa.Float, nullable=False),
        sa.Column(
            "material_class", sa.Text, nullable=False, server_default="polymer"
        ),
        sa.Column("shop", sa.Text, nullable=True),
        sa.Column("region", sa.Text, nullable=True),
        sa.Column("currency", sa.Text, nullable=False, server_default="USD"),
        sa.Column("source", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "stand_in", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("part_path", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Org-scoped read index (all reads filter by org_id); the composite also
    # serves the per-part lookup the recalibration + dedup paths use.
    op.create_index(
        "ix_ground_truth_records_org", "ground_truth_records", ["org_id"]
    )
    op.create_index(
        "ix_ground_truth_records_org_part",
        "ground_truth_records",
        ["org_id", "part_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ground_truth_records_org_part", table_name="ground_truth_records"
    )
    op.drop_index(
        "ix_ground_truth_records_org", table_name="ground_truth_records"
    )
    op.drop_table("ground_truth_records")
