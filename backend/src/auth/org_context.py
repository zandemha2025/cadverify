"""Org resolution helpers (W1 step 1 — tenancy foundation).

``resolve_org`` answers "which organization owns this user" by reading the
user's ``memberships`` row (single-org assumption in v1). It is a **pure read**
and is deliberately NOT wired into any route read filter yet — route threading
(WHERE org_id == ...) is W1 step 3. In this step the helper is used only by the
row-creation paths so that every newly written row carries a non-null ``org_id``.

``ensure_personal_org`` is the get-or-create used at signup so that a
post-migration new user has an org (and admin membership) *before* their first
write — without it the NOT NULL ``org_id`` on the data tables would reject a new
user's first analysis/cost/key. It mirrors, at runtime, exactly what migration
0009's backfill does for pre-existing users.

Slug/name generation lives here as pure functions so the migration backfill and
the runtime signup path produce byte-identical personal orgs.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import ApiKey, Batch, Membership, User

# org_role values allowed by the memberships CHECK constraint (migration 0009).
ORG_ROLES = ("admin", "member", "viewer")

_SLUG_SANITIZE = re.compile(r"[^a-z0-9]+")


def _short_ulid() -> str:
    """A short, lowercase, collision-resistant suffix for personal-org slugs."""
    return str(ULID())[-8:].lower()


def personal_org_slug(email: str) -> str:
    """``email-local + '-' + short-ulid`` (spec-mandated slug shape).

    The local part is lowercased and stripped to ``[a-z0-9-]``; the trailing
    short-ULID guarantees uniqueness even when two users share a local part
    (e.g. ``a@x.com`` and ``a@y.com``).
    """
    local = email.split("@", 1)[0].lower()
    local = _SLUG_SANITIZE.sub("-", local).strip("-")
    if not local:
        local = "org"
    return f"{local}-{_short_ulid()}"


def personal_org_name(email: str) -> str:
    """Human-readable default name for a user's personal org."""
    local = email.split("@", 1)[0]
    return f"{local}'s Organization"


def caller_org_subquery(user_id: int):
    """Correlated scalar expression → the org_id that owns ``user_id``.

    W1 step 3 — the isolation predicate for every org-scoped **read**::

        select(X).where(X.org_id == caller_org_subquery(user_id))

    Threading the org boundary as a subquery (rather than a separate
    ``resolve_org`` round-trip) is deliberate: each org-scoped read stays a
    SINGLE ``session.execute`` — byte-for-byte the same one-query-per-read shape
    as the pre-W1 ``WHERE user_id == :u`` idiom.

    Resolution (org-membership beat): ``COALESCE(validated_current, oldest)`` —
    the user's ``current_org_id`` when it names a LIVE membership, else the
    oldest membership. This is what makes org-switch real: a member who switched
    to org B reads B's rows; a stale/removed ``current_org_id`` (points at an org
    the user no longer belongs to) yields no ``validated_current`` row and falls
    back safely to a real membership — it never leaks the removed org and never
    errors. For a user with exactly ONE membership the two branches resolve to
    the same org, so single-org behaviour is byte-identical to the pre-beat
    oldest-membership rule (the entire isolation matrix passes unchanged).

    ``user_id`` binds as a literal parameter, so the returned expression is
    self-contained (not correlated against the outer table) — safe to drop into
    any ``select`` regardless of what it reads from.
    """
    current_org = (
        select(User.current_org_id).where(User.id == user_id).scalar_subquery()
    )
    validated_current = (
        select(Membership.org_id)
        .where(
            Membership.user_id == user_id,
            Membership.org_id == current_org,
        )
        .limit(1)
        .scalar_subquery()
    )
    oldest = (
        select(Membership.org_id)
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at.asc(), Membership.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    return func.coalesce(validated_current, oldest)


async def resolve_org(session: AsyncSession, user_id: int) -> Optional[str]:
    """Return the org_id that owns ``user_id`` — the caller's ACTIVE org, else None.

    Pure read of ``memberships`` (validated against ``users.current_org_id``):
    identical resolution to :func:`caller_org_subquery` — the current org when it
    names a live membership, else the oldest membership. A user with a single
    membership always resolves to that one org (byte-identical to the pre-beat
    rule); a stale/removed ``current_org_id`` falls back to a real membership and
    NEVER 500s or leaks the removed org. Returns None for a user with no
    membership (a mocked test session, or a not-yet-provisioned user) — callers
    on real Postgres always have a membership (signup + the 0009 backfill).

    Membership is RE-VALIDATED on every call (not a cached claim), so a removed
    member loses access immediately.
    """
    return (
        await session.execute(select(caller_org_subquery(user_id)))
    ).scalar_one_or_none()


async def resolve_org_via_batch(
    session: AsyncSession, batch_id: int
) -> Optional[str]:
    """Return the org_id of the batch that owns ``batch_id``, else None.

    ``batch_items`` and ``webhook_deliveries`` have no ``user_id``; their org is
    always the parent batch's org (matches the 0009 backfill derivation).
    """
    stmt = select(Batch.org_id).where(Batch.id == batch_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def revoke_org_api_keys(
    session: AsyncSession, user_id: int, org_id: str
) -> int:
    """Revoke every live key issued to ``user_id`` by ``org_id``.

    Membership removal and credential invalidation share one transaction, so a
    key cannot survive offboarding and become usable in another organization.
    The caller owns flush/commit.
    """
    result = await session.execute(
        update(ApiKey)
        .where(
            ApiKey.user_id == user_id,
            ApiKey.org_id == org_id,
            ApiKey.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
    )
    return int(result.rowcount or 0)


async def ensure_personal_org(
    session: AsyncSession, user_id: int, email: str
) -> str:
    """Get-or-create the user's personal org; return its org_id.

    Idempotent: if the user already has a membership (backfilled or previously
    provisioned) it returns that org and writes nothing. Otherwise it creates an
    ``organizations`` row, an ``admin`` ``memberships`` row, and points
    ``users.current_org_id`` at the new org — the exact triple the 0009 backfill
    creates. Uses raw SQL so it composes with the auth module's text()-based
    session without pulling the ORM into that hot path. Does NOT commit; the
    caller owns the transaction boundary.
    """
    existing = (
        await session.execute(
            text(
                "SELECT org_id FROM memberships WHERE user_id = :u "
                "ORDER BY created_at ASC, id ASC LIMIT 1"
            ),
            {"u": user_id},
        )
    ).first()
    if existing is not None:
        return existing[0]

    org_id = str(ULID())
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :name, :slug, now())"
        ),
        {"id": org_id, "name": personal_org_name(email), "slug": personal_org_slug(email)},
    )
    await session.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :org, :u, 'admin', now())"
        ),
        {"id": str(ULID()), "org": org_id, "u": user_id},
    )
    await session.execute(
        text("UPDATE users SET current_org_id = :org WHERE id = :u"),
        {"org": org_id, "u": user_id},
    )
    return org_id
