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

from src.auth.org_binding import gate_org
from src.db.models import ApiKey, Batch, Membership, Organization, User

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
    """The name personal orgs had before 0060 (and the 0009 backfill gave)."""
    local = email.split("@", 1)[0]
    return f"{local}'s Organization"


# Second-level labels under a country code ("acme.co.uk"): the company is the label before them.
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc", "or", "ne", "go"}
ORG_NAME_MAX = 80


# Trade words a run-together company domain ends with ("northfieldpumps" -> "Northfield
# Pumps", "tricountyprecision" -> "Tricounty Precision"). Only a trailing word is split
# off, and only when at least 3 letters stay in front; anything else stays one word.
_TRADE_WORDS = tuple(sorted({
    "pumps", "pump", "valves", "valve", "fluid", "fluids", "precision", "machining", "machine",
    "machines", "manufacturing", "mfg", "industries", "industrial", "systems", "engineering",
    "aerospace", "aero", "tooling", "tools", "tool", "works", "metals", "metal", "products",
    "controls", "robotics", "motors", "motor", "technologies", "tech", "labs", "design",
    "fabrication", "fab", "castings", "casting", "forge", "forging", "plastics", "molding",
    "moulding", "components", "devices", "medical", "energy", "power", "solutions", "group",
    "automation", "dynamics", "instruments", "electric", "electronics", "hydraulics", "gears",
    "gear", "parts", "supply", "marine", "motion", "fasteners", "springs", "bearings", "steel",
    "foundry", "industries", "equipment", "sensors", "optics", "defense", "defence",
}, key=len, reverse=True))


def _split_trade_word(word: str) -> list[str]:
    for t in _TRADE_WORDS:
        if word.endswith(t) and len(word) - len(t) >= 3:
            return [*_split_trade_word(word[: -len(t)]), t]
    return [word]


def company_from_domain(domain: str) -> str | None:
    """The company in a work email's domain: "northfieldpumps.com" -> "Northfield Pumps",
    "mail.acme-aero.co.uk" -> "Acme Aero", "ridgelinefluid.com" -> "Ridgeline Fluid". A
    run-together name is split before a trailing trade word (``_TRADE_WORDS``); it is
    a reading of the domain, so the org can be renamed (PATCH /orgs/current) and the
    app asks once. None when there's no usable label."""
    labels = [label for label in domain.strip().lower().rstrip(".").split(".") if label]
    if len(labels) < 2:
        return None
    pick = labels[-3] if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2 else labels[-2]
    words = [w for w in re.split(r"[-_]+", pick) if w and not w.isdigit()]
    if not words:
        return None
    words = [part for w in words for part in _split_trade_word(w)]
    return " ".join(w[:1].upper() + w[1:] for w in words)[:ORG_NAME_MAX]


def same_org_name(a: object, b: object) -> bool:
    """Two org names that differ only in spacing and case ("Northfieldpumps" and the
    "Northfield Pumps" sign-up gives now) are the same name."""
    norm = lambda x: re.sub(r"\s+", "", str(x or "")).lower()  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


def personal_org_display_name(email: str, full_name: str | None = None) -> str:
    """What a new account's own organization is called.

    A work email: the company from its domain ("Ridgelinefluid"). A personal
    email: the person's workspace ("Jordan Pike's workspace", else the email's
    local part). Either can be renamed later (PATCH /orgs/current).
    """
    from src.auth.email_tiers import email_tier

    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    if email_tier(email) == "work":
        company = company_from_domain(domain)
        if company:
            return company
    who = " ".join((full_name or "").split()) or email.split("@", 1)[0] or "Your"
    return f"{who}'s workspace"[:ORG_NAME_MAX]


_PERSONAL_NAME_SUFFIX = "'s Organization"
_SHORT_ULID_RE = re.compile(r"[0-9a-z]{8}")


def matches_legacy_personal_naming(name: object, slug: object) -> bool:
    """True when ``(name, slug)`` is the pair personal orgs were created with before 0060.

    Only migration 0060's backfill uses this rule (it keeps its own copy). The
    marker is ``organizations.is_personal``: a personal org can be renamed, so
    its name proves nothing.
    """
    if not isinstance(name, str) or not isinstance(slug, str):
        return False
    if not name.endswith(_PERSONAL_NAME_SUFFIX):
        return False
    local = name[: -len(_PERSONAL_NAME_SUFFIX)]
    stem = _SLUG_SANITIZE.sub("-", local.lower()).strip("-") or "org"
    prefix = f"{stem}-"
    return slug.startswith(prefix) and _SHORT_ULID_RE.fullmatch(slug[len(prefix):]) is not None


def is_personal_org(is_personal: object) -> bool:
    """True for a personal org, read from its ``is_personal`` column (never its name)."""
    return is_personal is True


async def org_is_personal(session: AsyncSession, org_id: str) -> bool:
    """True for a personal org (the one every account gets at sign-up), by its column."""
    row = (
        await session.execute(
            select(Organization.is_personal).where(Organization.id == org_id)
        )
    ).first()
    if row is None:
        return False
    return is_personal_org(row[0])


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

    Inside a request whose role gate already checked an org for this user
    (``auth.org_binding``, R2 F1), the answer is that org — still only while the
    membership is live (else NULL: no rows, never another org) — so a switch
    sent while the request runs can't move it into an org the gate never
    checked.
    """
    bound = gate_org(user_id)
    if bound is not None:
        return (
            select(Membership.org_id)
            .where(Membership.user_id == user_id, Membership.org_id == bound)
            .limit(1)
            .scalar_subquery()
        )
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

    Inside a request whose role gate checked an org, this is that org (see
    :func:`caller_org_subquery`).
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
    session: AsyncSession,
    user_id: int,
    email: str,
    full_name: str | None = None,
    *,
    name: str | None = None,
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
            "INSERT INTO organizations (id, name, slug, is_personal, created_at) "
            "VALUES (:id, :name, :slug, true, now())"
        ),
        {"id": org_id, "name": name or personal_org_display_name(email, full_name), "slug": personal_org_slug(email)},
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
