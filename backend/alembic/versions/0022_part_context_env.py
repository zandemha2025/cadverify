"""service-environment declaration on part_contexts (machine-inventory §6)

Adds a nullable ``service_environment`` JSONB to ``part_contexts`` so an org can
DECLARE a part's operating environment ({max_temp_c, min_temp_c, pressure_bar,
corrosive, sour_service, medium, standard}). This feeds the environment gate that
restricts materials/processes to those valid for the declared environment.

HONESTY: the environment is USER-declared (provenance ``user``), never inferred
from the mesh. NULL → no environment declared and the gate is a no-op
(byte-identical). Purely additive to the existing ``(org_id, mesh_hash)`` context
row — the leaner alternative to a dedicated ``part_requirements`` table (reuses
the org/mesh key + the declared-context honesty model).

Revision ID: 0022_part_context_env
Revises: 0021_machine_instances
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0022_part_context_env"
down_revision = "0021_machine_instances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '5000'")
    op.add_column(
        "part_contexts",
        sa.Column("service_environment", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("part_contexts", "service_environment")
