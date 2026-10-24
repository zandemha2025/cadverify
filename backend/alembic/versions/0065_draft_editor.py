"""Who last edited a library draft, and whether an approval was a self-approval.

Two small columns the "another admin approves it" rule needs (security review
R2 F3):

* ``edited_by`` on ``rate_card_versions``, ``shop_profile_versions`` and
  ``material_library_versions``: the account that last changed the draft
  (``PATCH`` on the library). An admin who wrote or last edited a draft can't
  approve it while the organization has another admin. NULL for a draft nobody
  has edited since it was made (its author is ``created_by``) and for every row
  made before this migration.
* ``change_requests.self_approved``: set when a request is approved, true when
  the reviewer proposed it, wrote the draft or last edited it (only possible in
  a single-admin organization). NULL for requests decided before this
  migration; they keep the old reading (approved by their proposer).

Additive (four nullable columns), no backfill. Downgrade drops the four
columns.

Revision ID: 0065_draft_editor
Revises: 0064_schedule_and_supplier
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0065_draft_editor"
down_revision = "0064_schedule_and_supplier"
branch_labels = None
depends_on = None

DRAFT_TABLES = ("rate_card_versions", "shop_profile_versions", "material_library_versions")


def _timeouts():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")


def upgrade():
    _timeouts()
    for table in DRAFT_TABLES:
        op.add_column(
            table,
            sa.Column(
                "edited_by",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.add_column("change_requests", sa.Column("self_approved", sa.Boolean(), nullable=True))


def downgrade():
    _timeouts()
    op.drop_column("change_requests", "self_approved")
    for table in DRAFT_TABLES:
        op.drop_column(table, "edited_by")
