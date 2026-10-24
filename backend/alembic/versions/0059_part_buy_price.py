"""What the organization pays today to buy a part: ``part_contexts.buy_price``.

A catalog run's parts list may give each part its current price (the
"Current price" column) and the part's Decision view lets a person type one.
Make or buy then compares making the part on the shop's machines with that
price instead of the cheapest outside model price, and states the saving a
year. One nullable JSONB column on the part's declared context:

    {"usd_each": 12.4, "per": "each" | "100" | ..., "source": "parts_list" | "you",
     "run_id": "<batch ulid>" | null, "updated_at": "<iso>"}

It is a declared fact, not an engine input: it moves a part between make and
buy and sets the saving, never the engine's own figures, so it never marks a
record out of date. Additive and nullable, no backfill.

Downgrade drops the column (the prices typed or listed go with it).

Revision ID: 0059_part_buy_price
Revises: 0058_direct_upload_links
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0059_part_buy_price"
down_revision = "0058_direct_upload_links"
branch_labels = None
depends_on = None

TABLE = "part_contexts"
COLUMN = "buy_price"


def _json_type():
    return postgresql.JSONB(astext_type=sa.Text()) if op.get_bind().dialect.name == "postgresql" else sa.JSON()


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5000'")
    op.add_column(TABLE, sa.Column(COLUMN, _json_type(), nullable=True))


def downgrade():
    op.drop_column(TABLE, COLUMN)
