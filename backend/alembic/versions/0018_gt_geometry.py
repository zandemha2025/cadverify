"""add nullable geometry columns to ground_truth_records (P1 analogy k-NN feed)

The analogy-to-quote k-NN ensemble member (``src/costing/analogy_estimator.py``)
matches the query part against REAL ground-truth quotes by geometric distance —
but it has nothing to measure distance on unless each record carries the MEASURED
cost-drivers. This migration adds those drivers to ``ground_truth_records`` so a
record can activate the analogy member: ``volume_cm3``, ``surface_area_cm2``,
``max_bbox_mm``, ``face_count`` (mirroring ``analogy_estimator.FEATURE_KEYS`` /
``drivers.GeoDrivers``).

Purely ADDITIVE + NULLABLE: existing rows and records whose mesh does not resolve
at ingest stay NULL, and the analogy k-NN skips any record lacking usable
geometry — so nothing about the served number changes until an org has REAL
records that actually carry geometry. Geometry is populated best-effort at ingest
from the resolved mesh; it is never fabricated.

Revision ID: 0018_gt_geometry
Revises: 0017_materials
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)`` — a longer id fails the
version UPDATE and rolls back the whole upgrade.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_gt_geometry"
down_revision = "0017_materials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.add_column(
        "ground_truth_records",
        sa.Column("volume_cm3", sa.Float, nullable=True),
    )
    op.add_column(
        "ground_truth_records",
        sa.Column("surface_area_cm2", sa.Float, nullable=True),
    )
    op.add_column(
        "ground_truth_records",
        sa.Column("max_bbox_mm", sa.Float, nullable=True),
    )
    op.add_column(
        "ground_truth_records",
        sa.Column("face_count", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ground_truth_records", "face_count")
    op.drop_column("ground_truth_records", "max_bbox_mm")
    op.drop_column("ground_truth_records", "surface_area_cm2")
    op.drop_column("ground_truth_records", "volume_cm3")
