"""A durable marker for a personal organization: ``organizations.is_personal``.

Every account gets a personal organization at sign-up. Until now the only way
to tell one apart was its name/slug pair ("<email local>'s Organization" and
"<sanitized local>-<8 ulid chars>"), and SAML group mappings and SCIM refuse a
personal org by that pair. An organization can now be named after the company
and renamed, which would make a personal org read as a shared one, so the
marker becomes a column: ``is_personal boolean NOT NULL DEFAULT false``,
backfilled true for every row today's name/slug rule recognises. Code reads
only the column from here on.

Additive; the backfill touches only rows that match the rule. Downgrade drops
the column (a personal org renamed after 0060 would then no longer be known as
personal, so downgrade only before any rename, or rename it back first).

Revision ID: 0060_org_is_personal
Revises: 0059_part_buy_price
Create Date: 2026-10-22
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "0060_org_is_personal"
down_revision = "0059_part_buy_price"
branch_labels = None
depends_on = None

TABLE = "organizations"
COLUMN = "is_personal"

# The rule personal orgs were recognised by before 0060 (src.auth.org_context
# at 0059), copied so this migration never changes with the application.
_SUFFIX = "'s Organization"
_SANITIZE = re.compile(r"[^a-z0-9]+")
_ULID8 = re.compile(r"[0-9a-z]{8}")


def legacy_personal(name, slug) -> bool:
    if not isinstance(name, str) or not isinstance(slug, str) or not name.endswith(_SUFFIX):
        return False
    local = name[: -len(_SUFFIX)]
    stem = _SANITIZE.sub("-", local.lower()).strip("-") or "org"
    prefix = f"{stem}-"
    return slug.startswith(prefix) and _ULID8.fullmatch(slug[len(prefix):]) is not None


def upgrade():
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id, name, slug FROM {TABLE} WHERE name LIKE :suffix"), {"suffix": f"%{_SUFFIX}"}).fetchall()
    ids = [row[0] for row in rows if legacy_personal(row[1], row[2])]
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        bind.execute(
            sa.text(f"UPDATE {TABLE} SET {COLUMN} = true WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": chunk},
        )


def downgrade():
    op.drop_column(TABLE, COLUMN)
