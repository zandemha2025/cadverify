"""org_invites.invited_user_id — bind an invite to a RESOLVED account row

Closes the last surviving normalize_email-collision cross-tenant defect in the
invite recipient-binding guard (both directions of the collision).

Account uniqueness is ``users.email_lower``, but legacy SAML rows predate the
``normalize_email`` canonicalisation and stored a NON-normalised ``email_lower``
(gmail dots / +tags retained). Two DISTINCT account rows can therefore collide
under ``normalize_email`` (e.g. ``a.b@gmail.com`` vs ``ab@gmail.com``). The old
acceptance guard compared the accepting account's key against
``normalize_email(inv.email)`` and so — in the MIRROR direction (invitee is the
non-normalised legacy row, a distinct account holds the normalised form) — let
the WRONG account redeem the invite, up to an admin seat in another tenant.

The durable fix binds the invite to a specific account row at CREATION time:
``invited_user_id`` is resolved by an EXACT ``email_lower`` match (the real,
unique row identity — never a normalise-collision) and acceptance then requires
``accepting.id == invited_user_id``. That defeats both directions because the
exact match picks the intended row regardless of any colliding sibling. The
column is NULLABLE: an invite for an email with no account yet (invite-then-
signup) resolves to NULL and acceptance falls back to a collision-safe check.

Purely additive and reversible: every pre-existing invite backfills to NULL, so
the platform is byte-identical until a new invite is minted.

Revision ID: 0025_invite_invited_user
Revises: 0024_org_invites_deact
Create Date: 2026-07-04

Note: the revision id is kept <= 32 chars because alembic's
``alembic_version.version_num`` column is ``varchar(32)``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_invite_invited_user"
down_revision = "0024_org_invites_deact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = '10000'")

    # The account this invite was minted for, resolved by an EXACT email_lower
    # match at creation. NULLABLE — an invite for an as-yet-unregistered email
    # resolves to NULL and acceptance falls back to a collision-safe check.
    op.add_column(
        "org_invites",
        sa.Column("invited_user_id", sa.BigInteger, nullable=True),
    )
    op.create_foreign_key(
        "fk_org_invites_invited_user",
        "org_invites",
        "users",
        ["invited_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.execute("SET statement_timeout = '10000'")
    op.execute(
        "ALTER TABLE org_invites DROP CONSTRAINT IF EXISTS "
        "fk_org_invites_invited_user"
    )
    op.drop_column("org_invites", "invited_user_id")
