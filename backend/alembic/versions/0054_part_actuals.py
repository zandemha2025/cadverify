"""Part actuals: hours-only actuals, what each matched, and calibrations with an undo.

``ground_truth_records`` holds a customer's real numbers for a part. Until now a
row needed a real cost per part, so an export that carries only machine hours
(the common case for a shop's own machines) couldn't be kept. This migration:

* lets ``actual_unit_cost_usd`` be empty when ``actual_machine_hours`` is given
  (a CHECK keeps at least one of the two);
* adds ``part_number`` (the customer's own part number, as given), ``machine``
  (the machine the job ran on, as given) and ``match_basis`` (how the row was
  matched to a checked part: ``file_hash`` / ``part_number`` / ``file_name`` /
  ``chosen``). A matched row also keeps the part's file hash in
  ``evidence_sha256``, which recalibration and part deletion already read.

``org_calibrations`` records each calibration an organization applied to its
future estimates: the per-method factors, what they were fitted on, who applied
it and when, and who undid it and when. The newest row with status ``applied``
is the one in effect; undo marks it ``undone`` and the one before it (if any)
takes effect again.

Downgrade: rows that carry machine hours but no cost can't exist before 0054
(the cost column was NOT NULL). They are deleted, with a warning that names how
many, before the column is made NOT NULL again; then the columns, the CHECK and
the table are dropped.

Revision ID: 0054_part_actuals
Revises: 0053_data_control
Create Date: 2026-10-22
"""
import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0054_part_actuals"
down_revision = "0053_data_control"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_GT = "ground_truth_records"
_COST_OR_HOURS = "ck_ground_truth_cost_or_hours"
_MATCH_BASIS = "ck_ground_truth_match_basis"


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '60000'")


def upgrade():
    _timeouts()
    op.alter_column(_GT, "actual_unit_cost_usd", existing_type=sa.Float(), nullable=True)
    op.add_column(_GT, sa.Column("part_number", sa.Text(), nullable=True))
    op.add_column(_GT, sa.Column("machine", sa.Text(), nullable=True))
    op.add_column(_GT, sa.Column("match_basis", sa.Text(), nullable=True))
    op.create_check_constraint(
        _COST_OR_HOURS,
        _GT,
        "actual_unit_cost_usd IS NOT NULL OR actual_machine_hours IS NOT NULL",
    )
    op.create_check_constraint(
        _MATCH_BASIS,
        _GT,
        "match_basis IS NULL OR match_basis IN ('file_hash', 'part_number', 'file_name', 'chosen')",
    )
    op.create_index("ix_ground_truth_records_org_evidence", _GT, ["org_id", "evidence_sha256"])

    op.create_table(
        "org_calibrations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ulid", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "org_id",
            sa.Text(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("factors", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("basis", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="applied"),
        sa.Column(
            "applied_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("applied_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "undone_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("undone_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('applied', 'undone')", name="ck_org_calibrations_status"),
    )
    op.create_index("ix_org_calibrations_org_applied", "org_calibrations", ["org_id", "applied_at"])


def downgrade():
    _timeouts()
    op.drop_index("ix_org_calibrations_org_applied", table_name="org_calibrations")
    op.drop_table("org_calibrations")

    bind = op.get_bind()
    n = bind.execute(sa.text(f"SELECT count(*) FROM {_GT} WHERE actual_unit_cost_usd IS NULL")).scalar() or 0
    if n:
        logger.warning(
            "0054 downgrade: deleting %d ground_truth_records row(s) that carry machine hours "
            "but no cost; the cost column is NOT NULL before 0054.",
            n,
        )
        op.execute(f"DELETE FROM {_GT} WHERE actual_unit_cost_usd IS NULL")

    op.drop_index("ix_ground_truth_records_org_evidence", table_name=_GT)
    op.drop_constraint(_MATCH_BASIS, _GT, type_="check")
    op.drop_constraint(_COST_OR_HOURS, _GT, type_="check")
    op.drop_column(_GT, "match_basis")
    op.drop_column(_GT, "machine")
    op.drop_column(_GT, "part_number")
    op.alter_column(_GT, "actual_unit_cost_usd", existing_type=sa.Float(), nullable=False)
