"""Supplier links: what a share link shows, and a link for a whole RFQ package.

A share link is what a buyer sends a supplier, so it carries none of our cost
unless the buyer turns that on for that link (``src.services.share_links``):

* ``cost_decisions.share_options``: what the record's current link shows,
  ``{"include_cost", "include_cad", "note", "quantity"}``. NULL marks a link
  made before this; such a link shows the part and its specs, never the cost
  (it fails closed; its maker shares again with the cost on to show it).
* ``rfq_packages`` gets the link columns a record has (0053): ``is_public``,
  ``share_short_id``, ``share_created_at``, ``share_created_by``,
  ``share_expires_at``, ``share_revoked_at``, plus ``share_options``, so a
  package is shared as one link. A partial index finds a package by its short id.

Additive and nullable (``is_public`` defaults to false), no backfill. Downgrade
drops the columns: package links stop resolving, and record links show what
they showed before 0063 (the cost included).

Revision ID: 0063_supplier_links
Revises: 0062_two_step_sign_in
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0063_supplier_links"
down_revision = "0062_two_step_sign_in"
branch_labels = None
depends_on = None

INDEX = "ix_rfq_packages_share"


def _json():
    return JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
    op.add_column("cost_decisions", sa.Column("share_options", _json(), nullable=True))
    op.add_column("rfq_packages", sa.Column("is_public", sa.Boolean(), nullable=False,
                                            server_default=sa.text("false")))
    op.add_column("rfq_packages", sa.Column("share_short_id", sa.Text(), nullable=True))
    op.add_column("rfq_packages", sa.Column("share_created_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("rfq_packages", sa.Column(
        "share_created_by", sa.BigInteger(),
        sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_rfq_packages_share_created_by"),
        nullable=True))
    op.add_column("rfq_packages", sa.Column("share_expires_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("rfq_packages", sa.Column("share_revoked_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("rfq_packages", sa.Column("share_options", _json(), nullable=True))
    op.create_index(INDEX, "rfq_packages", ["share_short_id"],
                    postgresql_where=sa.text("share_short_id IS NOT NULL"))


def downgrade():
    op.drop_index(INDEX, table_name="rfq_packages")
    for column in ("share_options", "share_revoked_at", "share_expires_at", "share_created_by",
                   "share_created_at", "share_short_id", "is_public"):
        op.drop_column("rfq_packages", column)
    op.drop_column("cost_decisions", "share_options")
