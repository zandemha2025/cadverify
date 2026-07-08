"""machine-inventory model (verification-thesis crux — org-owned machines)

Adds two org-scoped tables (spec §3 / §3.1):

  * ``machine_instances`` — ONE row per owned machine (or identical group) carrying
    a customer's USER-DECLARED capability fields: a small set of universal typed
    columns (mass gate, own rate, capital fraction) that are queried/indexed, plus
    a per-process-family ``capabilities`` JSONB (envelope/force/reach/resolution
    scalars) and material-qualification JSONB. ``count`` is capacity (N identical
    machines), never a fit axis.
  * ``shop_capabilities`` — ONE row per org carrying the shop-level secondary-op
    set (``ops`` JSONB: {op: True | {size/temp limits}}). Secondary ops are
    shop-level (one HIP vessel per foundry), not per-machine.

Purely ADDITIVE and honestly SEPARATE: absent inventory the platform is
byte-identical. Every capability is USER-declared (provenance ``user``), never
measured or inferred. Org-scoped (FK orgs CASCADE); cross-tenant isolation on
every query lives in the service.

Revision ID: 0021_machine_instances
Revises: 0020_manifest_parts
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0021_machine_instances"
down_revision = "0020_manifest_parts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")

    op.create_table(
        "machine_instances",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ulid", sa.Text, nullable=False),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("process", sa.Text, nullable=False),
        sa.Column("count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_workpiece_kg", sa.Float, nullable=True),
        sa.Column("hourly_rate_usd", sa.Float, nullable=True),
        sa.Column("capital_frac", sa.Float, nullable=True),
        sa.Column("capabilities", JSONB, nullable=False, server_default="{}"),
        sa.Column("materials", JSONB, nullable=True),
        sa.Column("material_thickness_map", JSONB, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # ULID is the opaque public id — unique across the table.
    op.create_index(
        "ix_machine_instances_ulid", "machine_instances", ["ulid"], unique=True
    )
    op.create_index("ix_machine_instances_org", "machine_instances", ["org_id"])
    op.create_index(
        "ix_machine_instances_org_process",
        "machine_instances",
        ["org_id", "process"],
    )

    op.create_table(
        "shop_capabilities",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "org_id",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ops", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", name="uq_shop_capabilities_org"),
    )


def downgrade() -> None:
    op.drop_table("shop_capabilities")
    op.drop_index(
        "ix_machine_instances_org_process", table_name="machine_instances"
    )
    op.drop_index("ix_machine_instances_org", table_name="machine_instances")
    op.drop_index("ix_machine_instances_ulid", table_name="machine_instances")
    op.drop_table("machine_instances")
