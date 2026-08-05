"""Make public pilot-request receipts race-safe.

Revision ID: 0038_pilot_receipts
Revises: 0037_bom_edges
Create Date: 2026-07-11

The public intake uses ``audit_log`` as its append-only system of record. A
partial unique index makes the browser UUID an actual idempotency key under
concurrent retries without changing uniqueness semantics for any other audit
action. Any pre-index duplicate rows are retained and reclassified so an
upgrade cannot fail or erase historical intake evidence.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_pilot_receipts"
down_revision = "0037_bom_edges"
branch_labels = None
depends_on = None

_RECLASSIFY_DUPLICATES = sa.text(
    """
    WITH ranked_pilot_receipts AS (
        SELECT
            id,
            row_number() OVER (
                PARTITION BY resource_id
                ORDER BY id
            ) AS receipt_rank
        FROM audit_log
        WHERE action = 'pilot.requested'
          AND resource_id IS NOT NULL
    )
    UPDATE audit_log
    SET action = 'pilot.requested.duplicate'
    WHERE id IN (
        SELECT id
        FROM ranked_pilot_receipts
        WHERE receipt_rank > 1
    )
    """
)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")
        # Freeze writes before ranking so an old application process cannot
        # insert another duplicate between cleanup and CREATE UNIQUE INDEX. The
        # lock and DDL are bounded above and roll back together if DB is busy.
        op.execute("LOCK TABLE audit_log IN SHARE MODE")
    # Preserve every audit row. The earliest row remains the canonical receipt;
    # later rows are accurately classified as legacy duplicate submissions and
    # therefore fall outside the canonical-receipt index predicate.
    op.execute(_RECLASSIFY_DUPLICATES)
    op.create_index(
        "uq_audit_log_pilot_request_receipt",
        "audit_log",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text(
            "action = 'pilot.requested' AND resource_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "action = 'pilot.requested' AND resource_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '10000'")
    op.drop_index(
        "uq_audit_log_pilot_request_receipt",
        table_name="audit_log",
    )
    op.execute(
        "UPDATE audit_log "
        "SET action = 'pilot.requested' "
        "WHERE action = 'pilot.requested.duplicate'"
    )
