"""Machine schedules, and "Keep buying from our supplier" as a recorded outcome.

Two small changes the pilot answer needs:

* ``machine_instances.schedule``: the hours a machine (or identical group) is
  available a year, as the org declares it: ``{"shifts", "hours_per_shift",
  "days_per_year"}`` per machine; ``count`` multiplies it. NULL means not
  declared: the shop page shows the default ScaleCAD assumes (2 shifts × 8 h ×
  240 days) and says so. Capacity, never a fit axis.
* ``cost_decisions.user_disposition`` may be ``'supplier'``: the part stays
  bought from the supplier the org buys it from today, at its current price.
  The check constraint ``ck_cost_decisions_disposition`` is recreated with it.

Additive (a nullable column and a wider check), no backfill. Downgrade drops
the column and, because the old constraint has no ``'supplier'``, first
rewrites every ``'supplier'`` outcome to ``'outside'`` (bought outside, the
nearest outcome the old schema has); the basis keeps ``supplier: true``, so the
outcome is still readable as kept with the supplier.

Revision ID: 0064_schedule_and_supplier
Revises: 0063_supplier_links
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0064_schedule_and_supplier"
down_revision = "0063_supplier_links"
branch_labels = None
depends_on = None

CHECK = "ck_cost_decisions_disposition"
WITH_SUPPLIER = "user_disposition IS NULL OR user_disposition IN ('inhouse', 'outside', 'acquire', 'redesign', 'supplier')"
WITHOUT_SUPPLIER = "user_disposition IS NULL OR user_disposition IN ('inhouse', 'outside', 'acquire', 'redesign')"


def _json():
    return JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
    op.add_column("machine_instances", sa.Column("schedule", _json(), nullable=True))
    op.drop_constraint(CHECK, "cost_decisions", type_="check")
    op.create_check_constraint(CHECK, "cost_decisions", WITH_SUPPLIER)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
    op.execute("UPDATE cost_decisions SET user_disposition = 'outside' WHERE user_disposition = 'supplier'")
    op.drop_constraint(CHECK, "cost_decisions", type_="check")
    op.create_check_constraint(CHECK, "cost_decisions", WITHOUT_SUPPLIER)
    op.drop_column("machine_instances", "schedule")
