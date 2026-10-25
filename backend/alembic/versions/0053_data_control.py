"""Data control: share links that end and can be switched off; deletion receipts.

Share links (``analyses`` and ``cost_decisions``) gain four columns:

* ``share_created_at`` / ``share_created_by``: when and by whom the current link
  was made. ``share_created_by`` is filled for existing check links from the
  ``share.created`` audit row that made them; cost-record links never had one.
  ``share_created_at`` stays NULL for existing links: NULL marks a link made
  before links had an end date, so the product can say so.
* ``share_expires_at``: the link ends at this instant. NULL means the sharer
  chose no end date. Existing links had no end date; they get one 30 days after
  this migration runs (the release), never a silent "forever".
* ``share_revoked_at``: the link was switched off. The short id stays on the
  row so the public page can say "switched off" instead of "not found".

``data_deletions`` is one row per part or organization deletion: what was
removed, which stored files are still to be removed (the object store is
emptied after the database transaction commits, and retried until done), and
who asked. It has no foreign key to ``organizations`` on purpose: the receipt
outlives the organization it describes. It never holds a file name.

Downgrade keeps every link that is off today off: expired or switched-off links
lose their short id and become private again (the pre-0053 meaning), then the
columns and the table are dropped.

Revision ID: 0053_data_control
Revises: 0052_catalog_allowance
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0053_data_control"
down_revision = "0052_catalog_allowance"
branch_labels = None
depends_on = None

_SHARE_TABLES = ("analyses", "cost_decisions")
_LEGACY_LINK_DAYS = 30


def _timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
        op.execute("SET LOCAL statement_timeout = '60000'")


def upgrade():
    _timeouts()
    for table in _SHARE_TABLES:
        op.add_column(table, sa.Column("share_created_at", TIMESTAMP(timezone=True), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "share_created_by",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(table, sa.Column("share_expires_at", TIMESTAMP(timezone=True), nullable=True))
        op.add_column(table, sa.Column("share_revoked_at", TIMESTAMP(timezone=True), nullable=True))
        # Links that exist today had no end date: they end 30 days from now.
        op.execute(
            f"UPDATE {table} SET share_expires_at = now() + interval '{_LEGACY_LINK_DAYS} days' "
            "WHERE share_short_id IS NOT NULL AND is_public IS TRUE"
        )

    # Who made an existing check link: the audit row written when it was made.
    op.execute(
        "UPDATE analyses a SET share_created_by = al.user_id "
        "FROM audit_log al "
        "WHERE a.share_short_id IS NOT NULL AND al.action = 'share.created' "
        "AND al.resource_id = a.share_short_id AND al.org_id = a.org_id"
    )

    op.create_table(
        "data_deletions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ulid", sa.Text(), nullable=False, unique=True),
        sa.Column("scope", sa.Text(), nullable=False),
        # Plain text, no FK: the receipt outlives the organization.
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column(
            "requested_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="removing_files"),
        sa.Column("removed_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("steps_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("steps_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("steps_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("final_sweep_due_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('part', 'organization')", name="ck_data_deletions_scope"),
        sa.CheckConstraint(
            "status IN ('removing_files', 'done', 'failed')", name="ck_data_deletions_status"
        ),
    )
    op.create_index("ix_data_deletions_org_scope_target", "data_deletions", ["org_id", "scope", "target"])
    op.create_index("ix_data_deletions_status_updated", "data_deletions", ["status", "updated_at"])


def downgrade():
    _timeouts()
    op.drop_index("ix_data_deletions_status_updated", table_name="data_deletions")
    op.drop_index("ix_data_deletions_org_scope_target", table_name="data_deletions")
    op.drop_table("data_deletions")
    for table in _SHARE_TABLES:
        # Before 0053 an off link had no short id and was private. Keep every
        # link that is off now (switched off or past its end) off after downgrade.
        op.execute(
            f"UPDATE {table} SET share_short_id = NULL, is_public = FALSE "
            "WHERE share_revoked_at IS NOT NULL "
            "OR (share_expires_at IS NOT NULL AND share_expires_at <= now())"
        )
        op.drop_column(table, "share_revoked_at")
        op.drop_column(table, "share_expires_at")
        op.drop_column(table, "share_created_by")
        op.drop_column(table, "share_created_at")
