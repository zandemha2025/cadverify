"""What an API key may do and until when: ``api_keys.scope`` and ``api_keys.expires_at``.

An org admin governs the organization's keys, and each key carries least
privilege of its own:

- ``scope`` is ``'read'`` (GET, HEAD and OPTIONS only) or ``'read_write'``.
  NULL means read and write, so every key made before 0061 keeps working
  exactly as it did. A viewer's key is read only whatever this says; the
  authentication dependency applies that from the owner's org role.
- ``expires_at`` is when the key stops working (NULL: no expiry). Keys made
  before 0061 keep no expiry.

Additive and nullable, no backfill. Downgrade drops both columns: every key
then works as read and write with no expiry, which is how keys worked before.

Revision ID: 0061_api_key_scope
Revises: 0060_org_is_personal
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0061_api_key_scope"
down_revision = "0060_org_is_personal"
branch_labels = None
depends_on = None

TABLE = "api_keys"
SCOPE_CHECK = "ck_api_keys_scope"


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
    op.add_column(TABLE, sa.Column("scope", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_check_constraint(SCOPE_CHECK, TABLE, "scope IS NULL OR scope IN ('read', 'read_write')")


def downgrade():
    op.drop_constraint(SCOPE_CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "expires_at")
    op.drop_column(TABLE, "scope")
