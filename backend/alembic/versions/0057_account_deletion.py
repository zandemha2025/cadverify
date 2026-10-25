"""Account deletion: its receipt, usage counts that outlive an org, and the free-allowance ledger.

Three changes:

* ``data_deletions.scope`` also takes ``'account'``: deleting a person's sign-in
  account writes one receipt, like a part or an organization deletion.
* ``usage_events.org_id`` becomes nullable and its foreign key ``ON DELETE SET
  NULL`` (was ``CASCADE``). Deleting an organization clears the file hash of its
  usage rows first; the counts (event type, time, face count, duration) then
  stay with no organization instead of disappearing with it.
* ``deleted_account_allowances``: when an account is deleted, how many free
  checks and free catalog parts it had used, keyed by a one-way HMAC of its
  normalised email (never the email). A new account with the same normalised
  email starts from those counts, so deleting and signing up again doesn't
  hand out the free allowance twice.

The constraints are added ``NOT VALID`` and validated afterwards, so neither
table is locked against writes while existing rows are checked.

Downgrade restores both constraints. Rows the old schema can't hold are
deleted first: account receipts (the old scope check rejects them) and usage
rows whose organization was deleted (the old schema had already deleted them
with the organization). The ledger table is dropped.

Revision ID: 0057_account_deletion
Revises: 0056_part_specs_signoff
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "0057_account_deletion"
down_revision = "0056_part_specs_signoff"
branch_labels = None
depends_on = None

SCOPE_CHECK = "ck_data_deletions_scope"
SCOPE_RULE = "scope IN ('part', 'organization', 'account')"
OLD_SCOPE_RULE = "scope IN ('part', 'organization')"
USAGE_ORG_FK = "fk_usage_events_org"
LEDGER = "deleted_account_allowances"
LEDGER_CHECK = "ck_deleted_account_allowances_counts"
LEDGER_RULE = "checks_used >= 0 AND catalog_parts_used >= 0"


def _pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _timeouts() -> None:
    if _pg():
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '60000'")


def _scope_check(rule: str) -> None:
    op.drop_constraint(SCOPE_CHECK, "data_deletions", type_="check")
    if _pg():
        op.execute(f"ALTER TABLE data_deletions ADD CONSTRAINT {SCOPE_CHECK} CHECK ({rule}) NOT VALID")
        op.execute(f"ALTER TABLE data_deletions VALIDATE CONSTRAINT {SCOPE_CHECK}")
    else:
        op.create_check_constraint(SCOPE_CHECK, "data_deletions", rule)


def _usage_org_fk(ondelete: str) -> None:
    op.drop_constraint(USAGE_ORG_FK, "usage_events", type_="foreignkey")
    if _pg():
        op.execute(
            f"ALTER TABLE usage_events ADD CONSTRAINT {USAGE_ORG_FK} FOREIGN KEY (org_id) "
            f"REFERENCES organizations (id) ON DELETE {ondelete} NOT VALID"
        )
        op.execute(f"ALTER TABLE usage_events VALIDATE CONSTRAINT {USAGE_ORG_FK}")
    else:
        op.create_foreign_key(USAGE_ORG_FK, "usage_events", "organizations", ["org_id"], ["id"], ondelete=ondelete)


def upgrade():
    _timeouts()
    _scope_check(SCOPE_RULE)
    op.alter_column("usage_events", "org_id", existing_type=sa.Text(), nullable=True)
    _usage_org_fk("SET NULL")
    op.create_table(
        LEDGER,
        sa.Column("email_hmac", sa.Text(), primary_key=True),
        sa.Column("checks_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("catalog_parts_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(LEDGER_RULE, name=LEDGER_CHECK),
    )


def downgrade():
    _timeouts()
    op.drop_table(LEDGER)
    op.execute("DELETE FROM usage_events WHERE org_id IS NULL")
    _usage_org_fk("CASCADE")
    op.alter_column("usage_events", "org_id", existing_type=sa.Text(), nullable=False)
    op.execute("DELETE FROM data_deletions WHERE scope = 'account'")
    _scope_check(OLD_SCOPE_RULE)
