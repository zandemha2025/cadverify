"""Add org-scoped Design Studio projects and immutable revisions.

Revision ID: 0040_design_studio
Revises: 0039_auth_identities
Create Date: 2026-07-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040_design_studio"
down_revision = "0039_auth_identities"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")


def upgrade() -> None:
    _timeouts()
    op.create_table(
        "design_projects",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ulid", sa.Text(), nullable=False),
        sa.Column(
            "org_id",
            sa.Text(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="generating", nullable=False),
        sa.Column("source_kind", sa.Text(), server_default="template", nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default="1", nullable=False),
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
            "status IN ('generating','ready','failed','archived')",
            name="ck_design_projects_status",
        ),
        sa.CheckConstraint(
            "source_kind IN ('template','ai_plan')",
            name="ck_design_projects_source_kind",
        ),
        sa.CheckConstraint(
            "current_revision >= 1", name="ck_design_projects_current_revision"
        ),
        sa.UniqueConstraint("ulid", name="uq_design_projects_ulid"),
    )
    op.create_index(
        "ix_design_projects_org_updated",
        "design_projects",
        ["org_id", "updated_at"],
    )
    op.create_index(
        "ix_design_projects_org_status", "design_projects", ["org_id", "status"]
    )

    op.create_table(
        "design_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ulid", sa.Text(), nullable=False),
        sa.Column(
            "design_id",
            sa.BigInteger(),
            sa.ForeignKey("design_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Text(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column(
            "operation_plan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("design_note", sa.Text(), nullable=True),
        sa.Column(
            "generation_engine",
            sa.Text(),
            server_default="proofshape-occ-v1",
            nullable=False,
        ),
        sa.Column("geometry_hash", sa.Text(), nullable=True),
        sa.Column("step_object_key", sa.Text(), nullable=True),
        sa.Column("stl_object_key", sa.Text(), nullable=True),
        sa.Column("step_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("stl_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "geometry_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','generating','ready','failed')",
            name="ck_design_revisions_status",
        ),
        sa.CheckConstraint("revision_no >= 1", name="ck_design_revisions_number"),
        sa.UniqueConstraint("ulid", name="uq_design_revisions_ulid"),
        sa.UniqueConstraint(
            "design_id", "revision_no", name="uq_design_revisions_design_number"
        ),
    )
    op.create_index(
        "ix_design_revisions_org_created",
        "design_revisions",
        ["org_id", "created_at"],
    )
    op.create_index(
        "ix_design_revisions_design_status",
        "design_revisions",
        ["design_id", "status"],
    )


def downgrade() -> None:
    _timeouts()
    op.drop_index("ix_design_revisions_design_status", table_name="design_revisions")
    op.drop_index("ix_design_revisions_org_created", table_name="design_revisions")
    op.drop_table("design_revisions")
    op.drop_index("ix_design_projects_org_status", table_name="design_projects")
    op.drop_index("ix_design_projects_org_updated", table_name="design_projects")
    op.drop_table("design_projects")
