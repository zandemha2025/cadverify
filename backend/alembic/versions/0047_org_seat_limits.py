"""Org seat limits: organizations.seat_limit column (nullable = unlimited).

Revision ID: 0047_org_seat_limits
Revises: 0046_trial_plan
Create Date: 2026-09-14

Shared-seats quota for customer-ready team/org workspaces. ``seat_limit`` is
the maximum number of seats an org may consume, where consumed seats =
active memberships + pending (unexpired, unrevoked, unaccepted) invites.
NULL means unlimited — every legacy/personal org keeps byte-identical
behaviour (no backfill, no default). Enforcement lives in
``src/services/org_service.py`` at invite creation and invite acceptance;
governance (an admin setting/lowering the limit) lives on the orgs router.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_org_seat_limits"
down_revision = "0046_trial_plan"
branch_labels = None
depends_on = None


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")


def upgrade() -> None:
    _timeouts()
    op.add_column(
        "organizations",
        # Nullable Integer, NO server default: NULL = unlimited, so existing
        # orgs are untouched and only an explicit governance action caps seats.
        sa.Column("seat_limit", sa.Integer(), nullable=True),
    )
    op.execute(
        "COMMENT ON COLUMN organizations.seat_limit IS "
        "'Max consumed seats (memberships + pending invites); NULL = unlimited'"
    )


def downgrade() -> None:
    _timeouts()
    op.drop_column("organizations", "seat_limit")
