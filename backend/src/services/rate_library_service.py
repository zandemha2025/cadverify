"""Governed rate-library service (W4 libraries, slice 1).

Replaces "the 487-line hardcoded ``RATE_CARD_V0`` dict with no API at all"
(long-horizon-plan §W4) with a DB-backed, org-scoped, versioned, effective-dated
rate-card asset an org admin can draft, edit, and PUBLISH with an effective date.
The costing engine reads the version *in effect at estimate time* as its base
DEFAULT table (via ``EstimateOptions.base_rate_table`` → ``build_rate_card``).

Design mirrors the repo's convention: the real versioning / effective-dating /
validation logic lives in PURE functions (``validate_rate_table``,
``select_effective``, ``default_rate_payload``) that are unit-tested without a
DB; the SQLAlchemy adapters below are thin.

HONESTY (non-negotiable rules #1/#2): a governed rate card is still a table of
DEFAULT assumptions — it is NOT measured truth. Adopting one changes *which*
default numbers an org uses; it never changes provenance semantics and never
flips a decision to ``validated`` (that comes only from real ground-truth
residuals, W5). Validation refuses a structurally-incomplete table so the engine
can never silently fabricate a missing rate.
"""
from __future__ import annotations

import copy
import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.costing.rates import RATE_CARD_V0, build_rate_card
from src.db.models import RateCardVersion

logger = logging.getLogger("cadverify.rate_library_service")

RATE_LIBRARY_FLAG = "RATE_LIBRARY_ENABLED"

# The full top-level + global key sets a governed table must carry so the engine
# never reads a missing key. Derived from the canonical default at import time.
REQUIRED_TOP_KEYS = tuple(sorted(RATE_CARD_V0.keys()))
REQUIRED_GLOBAL_KEYS = tuple(sorted(RATE_CARD_V0["global"].keys()))


def rate_library_enabled() -> bool:
    """Feature flag ``RATE_LIBRARY_ENABLED`` — default OFF.

    OFF (default) => the cost path never reads the DB asset and uses the
    hardcoded ``RATE_CARD_V0``, byte-identical to pre-W4. ON => a published,
    effective-dated card for the caller's org is used as the base table when one
    exists (otherwise still the hardcoded default).
    """
    return os.getenv(RATE_LIBRARY_FLAG, "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without a DB)
# ---------------------------------------------------------------------------


def default_rate_payload() -> dict:
    """A deep copy of the canonical ``RATE_CARD_V0`` — the seed for a first draft."""
    return copy.deepcopy(RATE_CARD_V0)


def validate_rate_table(payload: Any) -> None:
    """Raise ``ValueError`` unless ``payload`` is a structurally-complete,
    engine-consumable rate table.

    A governed card must be at least as complete as ``RATE_CARD_V0`` so the
    engine never reads a missing key and silently substitutes a fabricated
    value. We assert the top-level shape and the full ``global`` key set, then
    dry-run-bind it through ``build_rate_card`` so a structurally-valid but
    engine-broken table is rejected at publish, not at cost time.
    """
    if not isinstance(payload, dict):
        raise ValueError("rate table must be a JSON object")
    missing_top = [k for k in REQUIRED_TOP_KEYS if k not in payload]
    if missing_top:
        raise ValueError(f"rate table is missing top-level keys: {missing_top}")
    g = payload.get("global")
    if not isinstance(g, dict):
        raise ValueError("rate table 'global' must be an object")
    missing_global = [k for k in REQUIRED_GLOBAL_KEYS if k not in g]
    if missing_global:
        raise ValueError(
            f"rate table 'global' is missing keys: {missing_global}"
        )
    try:
        build_rate_card(base_rate_table=payload)
    except Exception as exc:  # noqa: BLE001 — surface the engine's own message
        raise ValueError(f"rate table is not engine-consumable: {exc}") from exc


def select_effective(
    rows: Iterable[Any], as_of: datetime
) -> Optional[Any]:
    """Pick the PUBLISHED row in effect at ``as_of`` (pure).

    In effect ⇔ ``status == 'published'``, ``effective_from`` set and ``<= as_of``,
    and (``effective_to`` is None or ``> as_of``). On a well-formed timeline at
    most one row qualifies; a defensive tie breaks to the highest ``version``.
    All timestamps must be timezone-aware (Postgres ``TIMESTAMP(timezone=True)``).
    """
    best = None
    for r in rows:
        if getattr(r, "status", None) != "published":
            continue
        ef = r.effective_from
        if ef is None or ef > as_of:
            continue
        et = r.effective_to
        if et is not None and et <= as_of:
            continue
        if best is None or r.version > best.version:
            best = r
    return best


# ---------------------------------------------------------------------------
# Resolution cache (single-process; invalidated on publish)
# ---------------------------------------------------------------------------
# org_id -> {"payload", "effective_from", "effective_to", "version"}. Like the
# in-memory rate limiter, each worker process holds its own copy — a documented
# limitation, not a correctness bug: a stale cache only delays a just-published
# card by the effective-window check, and every publish invalidates the process
# that served it. Multi-worker cache coherence is a later item (needs Redis/pub-sub).
_CACHE: dict[str, dict] = {}


def invalidate(org_id: str) -> None:
    _CACHE.pop(org_id, None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def resolve_rate_table_for_org(
    session: AsyncSession,
    org_id: Optional[str],
    as_of: Optional[datetime] = None,
) -> Optional[dict]:
    """Return the org's published rate-table payload in effect at ``as_of``.

    Returns ``None`` — meaning "use the hardcoded ``RATE_CARD_V0``" — when the
    flag is off, there is no org, or the org has no published card in effect.
    ``None`` keeps the cost path byte-identical to pre-W4.
    """
    if not rate_library_enabled() or not org_id:
        return None
    now = as_of or _now()

    cached = _CACHE.get(org_id)
    if cached is not None:
        ef, et = cached["effective_from"], cached["effective_to"]
        if ef is not None and ef <= now and (et is None or et > now):
            return cached["payload"]

    rows = (
        await session.execute(
            select(RateCardVersion).where(
                RateCardVersion.org_id == org_id,
                RateCardVersion.status == "published",
            )
        )
    ).scalars().all()
    row = select_effective(rows, now)
    if row is None:
        return None
    _CACHE[org_id] = {
        "payload": row.payload,
        "effective_from": row.effective_from,
        "effective_to": row.effective_to,
        "version": row.version,
    }
    return row.payload


# ---------------------------------------------------------------------------
# DB adapters (thin; the router owns auth + serialization)
# ---------------------------------------------------------------------------


async def _next_version(session: AsyncSession, org_id: str) -> int:
    current = (
        await session.execute(
            select(func.max(RateCardVersion.version)).where(
                RateCardVersion.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    return int(current or 0) + 1


async def list_versions(session: AsyncSession, org_id: str) -> list:
    return list(
        (
            await session.execute(
                select(RateCardVersion)
                .where(RateCardVersion.org_id == org_id)
                .order_by(RateCardVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )


async def get_version(
    session: AsyncSession, org_id: str, version_id: int
) -> Optional[RateCardVersion]:
    return (
        await session.execute(
            select(RateCardVersion).where(
                RateCardVersion.org_id == org_id,
                RateCardVersion.id == version_id,
            )
        )
    ).scalars().first()


async def create_draft(
    session: AsyncSession,
    org_id: str,
    *,
    name: str = "",
    change_note: str = "",
    payload: Optional[dict] = None,
    from_version_id: Optional[int] = None,
    created_by: Optional[int] = None,
) -> RateCardVersion:
    """Create a new DRAFT version. Payload defaults to the canonical table (first
    draft) or a deep copy of ``from_version_id`` (iterate on an existing card)."""
    if payload is None:
        if from_version_id is not None:
            src = await get_version(session, org_id, from_version_id)
            if src is None:
                raise HTTPException(status_code=404, detail="source version not found")
            payload = copy.deepcopy(src.payload)
        else:
            payload = default_rate_payload()
    validate_rate_table(payload)
    row = RateCardVersion(
        ulid=str(ULID()),
        org_id=org_id,
        version=await _next_version(session, org_id),
        name=name or "",
        status="draft",
        payload=payload,
        change_note=change_note or "",
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    return row


async def update_draft(
    session: AsyncSession,
    org_id: str,
    version_id: int,
    *,
    name: Optional[str] = None,
    change_note: Optional[str] = None,
    payload: Optional[dict] = None,
) -> RateCardVersion:
    row = await get_version(session, org_id, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")
    if row.status != "draft":
        raise HTTPException(
            status_code=409, detail="only draft versions can be edited"
        )
    if payload is not None:
        validate_rate_table(payload)
        row.payload = payload
    if name is not None:
        row.name = name
    if change_note is not None:
        row.change_note = change_note
    await session.flush()
    return row


async def publish_version(
    session: AsyncSession,
    org_id: str,
    version_id: int,
    *,
    effective_from: Optional[datetime] = None,
) -> RateCardVersion:
    """Publish a draft: stamp ``effective_from`` and close the currently-open
    published version's ``effective_to`` so the timeline never overlaps."""
    row = await get_version(session, org_id, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")
    if row.status == "published":
        raise HTTPException(status_code=409, detail="version already published")
    if row.status != "draft":
        raise HTTPException(
            status_code=409, detail="only draft versions can be published"
        )
    validate_rate_table(row.payload)

    now = _now()
    eff = effective_from or now
    if eff.tzinfo is None:
        eff = eff.replace(tzinfo=timezone.utc)
    if eff < now:
        raise HTTPException(
            status_code=400, detail="effective_from cannot be in the past"
        )

    open_rows = (
        await session.execute(
            select(RateCardVersion).where(
                RateCardVersion.org_id == org_id,
                RateCardVersion.status == "published",
                RateCardVersion.effective_to.is_(None),
            )
        )
    ).scalars().all()
    for prev in open_rows:
        prev.effective_to = eff

    row.status = "published"
    row.effective_from = eff
    row.published_at = now
    await session.flush()
    invalidate(org_id)
    return row


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def serialize_version(row: RateCardVersion, *, include_payload: bool = False) -> dict:
    out = {
        "id": row.id,
        "ulid": row.ulid,
        "version": row.version,
        "name": row.name,
        "status": row.status,
        "change_note": row.change_note,
        "effective_from": _iso(row.effective_from),
        "effective_to": _iso(row.effective_to),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "published_at": _iso(row.published_at),
        # Honest, always-present posture: a governed card is DEFAULT assumptions,
        # never measured/validated. The UI must not badge it as certified.
        "provenance": "default",
        "validated": False,
    }
    if include_payload:
        out["payload"] = row.payload
    return out
