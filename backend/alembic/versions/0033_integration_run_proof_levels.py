"""integration run proof levels

Revision ID: 0033_integration_proof_levels
Revises: 0032_rfq_packages
Create Date: 2026-07-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_integration_proof_levels"
down_revision = "0032_rfq_packages"
branch_labels = None
depends_on = None


CONNECTOR_MODES = (
    "offline_csv",
    "sandbox_api",
    "live_readonly",
    "live_write_draft",
    "live_send",
)
BOUNDARY_LABELS = (
    "simulation",
    "exported_fixture",
    "sandbox",
    "live_readonly",
    "draft_write",
    "live_send",
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")

    op.add_column(
        "integration_runs",
        sa.Column(
            "connector_mode",
            sa.Text(),
            nullable=False,
            server_default="offline_csv",
        ),
    )
    op.add_column(
        "integration_runs",
        sa.Column(
            "boundary_label",
            sa.Text(),
            nullable=False,
            server_default="exported_fixture",
        ),
    )
    op.add_column("integration_runs", sa.Column("api_name", sa.Text(), nullable=True))
    op.add_column("integration_runs", sa.Column("api_version", sa.Text(), nullable=True))
    op.add_column(
        "integration_runs",
        sa.Column("external_tenant_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_runs",
        sa.Column(
            "correlation_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("integration_runs", sa.Column("watermark", sa.Text(), nullable=True))
    op.add_column(
        "integration_runs",
        sa.Column("idempotency_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_runs",
        sa.Column(
            "source_record_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "integration_runs",
        sa.Column(
            "normalized_record_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.execute(
        "UPDATE integration_runs SET source_record_count = rows_total, "
        "normalized_record_count = rows_valid"
    )
    op.create_check_constraint(
        "ck_integration_runs_connector_mode",
        "integration_runs",
        f"connector_mode IN ({_in_list(CONNECTOR_MODES)})",
    )
    op.create_check_constraint(
        "ck_integration_runs_boundary_label",
        "integration_runs",
        f"boundary_label IN ({_in_list(BOUNDARY_LABELS)})",
    )
    op.create_index(
        "ix_integration_runs_org_boundary",
        "integration_runs",
        ["org_id", "boundary_label"],
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.drop_index("ix_integration_runs_org_boundary", table_name="integration_runs")
    op.drop_constraint(
        "ck_integration_runs_boundary_label",
        "integration_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_integration_runs_connector_mode",
        "integration_runs",
        type_="check",
    )
    op.drop_column("integration_runs", "normalized_record_count")
    op.drop_column("integration_runs", "source_record_count")
    op.drop_column("integration_runs", "idempotency_key")
    op.drop_column("integration_runs", "watermark")
    op.drop_column("integration_runs", "correlation_ids_json")
    op.drop_column("integration_runs", "external_tenant_hash")
    op.drop_column("integration_runs", "api_version")
    op.drop_column("integration_runs", "api_name")
    op.drop_column("integration_runs", "boundary_label")
    op.drop_column("integration_runs", "connector_mode")
