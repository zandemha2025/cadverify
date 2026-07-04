"""Governed shop-library service (W4 libraries, slice 2).

The DB-backed successor to the read-only ``backend/data/shop_profiles/*.json``
flat files: an org-scoped, versioned, effective-dated, PER-SLUG shop-calibration
asset an org admin can draft, edit, and PUBLISH with an effective date. The
costing engine binds the version *in effect at estimate time* for the requested
slug as that shop's SHOP-provenance overrides (via ``EstimateOptions.shop`` →
``build_rate_card(shop_overrides=…)``) instead of loading the flat file.

Design mirrors ``rate_library_service`` exactly: the real versioning /
effective-dating / validation logic lives in PURE functions
(``validate_shop_payload``, ``select_effective``, ``default_shop_payload``,
``governed_shop_profile``) that are unit-tested without a DB; the SQLAlchemy
adapters below are thin. The one difference is scope: a shop is identified by
``slug``, so the effective row is resolved PER ``(org_id, slug)``.

HONESTY (non-negotiable rules #1/#2): a governed shop profile is the org's
DECLARED shop calibration. ``build_rate_card`` already flips its keys to SHOP
provenance (``shop_keys``) — a declared assumption, NOT measured truth. Adopting
one changes *which* shop numbers an org uses; it never flips a decision to
``validated`` (that comes only from real ground-truth residuals, W5). Validation
refuses an unrecognized override key so the engine can never silently bind a
fabricated rate.
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

from src.costing.rates import build_rate_card
from src.costing.shop_profile import ShopProfile, _slug, resolve_shop
from src.db.models import ShopProfileVersion

logger = logging.getLogger("cadverify.shop_library_service")

SHOP_LIBRARY_FLAG = "SHOP_LIBRARY_ENABLED"

# Reserved payload keys that are shop IDENTITY metadata, not rate-override keys.
# They carry the display name / region used for the SHOP binding label and are
# split out before the overrides dry-run so they are never mistaken for a rate.
RESERVED_META_KEYS = ("name", "region")


def shop_library_enabled() -> bool:
    """Feature flag ``SHOP_LIBRARY_ENABLED`` — default OFF.

    OFF (default) => the cost path never reads the DB asset and resolves shops
    only from the flat-file store (``resolve_shop``), byte-identical to pre-W4.
    ON => a published, effective-dated governed profile for the caller's org +
    slug is bound when one exists (otherwise still the flat-file path).
    """
    return os.getenv(SHOP_LIBRARY_FLAG, "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without a DB)
# ---------------------------------------------------------------------------


def _split_payload(payload: dict) -> tuple[dict, dict]:
    """Split a shop payload into (rate-override keys, identity metadata)."""
    overrides = {k: v for k, v in payload.items() if k not in RESERVED_META_KEYS}
    meta = {k: payload[k] for k in RESERVED_META_KEYS if k in payload}
    return overrides, meta


def validate_shop_payload(payload: Any) -> None:
    """Raise ``ValueError`` unless ``payload`` is a dict of recognized
    shop-override keys (plus optional ``name``/``region`` metadata).

    The overrides are dry-run-bound through ``build_rate_card(shop_overrides=…)``
    so a key the engine does not understand is rejected at draft/publish, not at
    cost time — the engine can never silently bind a fabricated rate. An empty
    overrides dict is valid (a shop that overrides nothing stays all-DEFAULT).
    """
    if not isinstance(payload, dict):
        raise ValueError("shop profile must be a JSON object")
    overrides, meta = _split_payload(payload)
    for k in ("name", "region"):
        if k in meta and not isinstance(meta[k], str):
            raise ValueError(f"shop profile {k!r} must be a string")
    for key in overrides:
        if not isinstance(key, str):
            raise ValueError("shop-override keys must be strings")
    try:
        build_rate_card(shop_overrides=overrides)
    except Exception as exc:  # noqa: BLE001 — surface the engine's own message
        raise ValueError(f"shop profile has an unrecognized override: {exc}") from exc


def default_shop_payload(slug: str) -> dict:
    """Seed for a first draft of ``slug``.

    If a flat-file profile with the same slug/name exists it is migrated verbatim
    (its ``to_shop_overrides()`` plus ``name``/``region``) — the honest bridge
    from the read-only JSON store to the governed asset. Otherwise an empty
    overrides dict (a shop that overrides nothing, everything DEFAULT).
    """
    try:
        prof = resolve_shop(slug)
    except Exception:  # noqa: BLE001 — no flat-file counterpart is fine
        prof = None
    if prof is None:
        return {}
    payload = dict(prof.to_shop_overrides())
    payload["name"] = prof.name
    payload["region"] = prof.region
    return payload


def select_effective(
    rows: Iterable[Any], as_of: datetime, slug: Optional[str] = None
) -> Optional[Any]:
    """Pick the PUBLISHED row in effect at ``as_of`` (pure), scoped to ``slug``.

    In effect ⇔ ``status == 'published'``, ``effective_from`` set and ``<= as_of``,
    and (``effective_to`` is None or ``> as_of``). When ``slug`` is given, only
    rows for that slug are considered — a published version for slug A is never
    returned for slug B. On a well-formed per-(org, slug) timeline at most one row
    qualifies; a defensive tie breaks to the highest ``version``.
    """
    best = None
    for r in rows:
        if getattr(r, "status", None) != "published":
            continue
        if slug is not None and getattr(r, "slug", None) != slug:
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


def governed_shop_profile(slug: str, payload: dict) -> "_GovernedShopProfile":
    """Build the ShopProfile-like binding for a governed payload.

    The dotted-key overrides bind as SHOP; ``name``/``region`` (from the payload
    metadata, defaulting to the slug / ``"US"``) carry the shop label + region.
    """
    overrides, meta = _split_payload(payload)
    name = meta.get("name") or slug
    region = meta.get("region") or "US"
    return _GovernedShopProfile(slug=slug, name=name, region=region, overrides=overrides)


class _GovernedShopProfile(ShopProfile):
    """A ``ShopProfile`` whose overrides come straight from a governed payload's
    dotted-key dict rather than the structured dataclass fields.

    Subclasses ``ShopProfile`` so ``resolve_shop`` accepts it (its ``isinstance``
    check), and overrides ``to_shop_overrides`` to emit the governed dict verbatim
    — the same form ``build_rate_card(shop_overrides=…)`` consumes, tagged SHOP.
    """

    def __init__(self, *, slug: str, name: str, region: str, overrides: dict):
        super().__init__(name=name, region=region)
        self.slug = slug
        self._overrides = dict(overrides)

    def to_shop_overrides(self) -> dict:
        return dict(self._overrides)


# ---------------------------------------------------------------------------
# Resolution cache (single-process; invalidated on publish) — keyed (org, slug)
# ---------------------------------------------------------------------------
# Like the rate-library cache, each worker process holds its own copy — a stale
# entry only delays a just-published profile by the effective-window check, and
# every publish/archive invalidates the (org, slug) that served it. Multi-worker
# coherence is a later item (needs Redis/pub-sub).
_CACHE: dict[tuple[str, str], dict] = {}


def invalidate(org_id: str, slug: Optional[str] = None) -> None:
    """Drop the cached resolution for one (org, slug), or all of an org's slugs."""
    if slug is not None:
        _CACHE.pop((org_id, slug), None)
        return
    for key in [k for k in _CACHE if k[0] == org_id]:
        _CACHE.pop(key, None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def resolve_shop_overrides_for(
    session: AsyncSession,
    org_id: Optional[str],
    slug: Optional[str],
    as_of: Optional[datetime] = None,
) -> Optional[dict]:
    """Return the org's published shop payload for ``slug`` in effect at ``as_of``.

    Returns ``None`` — meaning "fall through to the flat-file ``resolve_shop``
    path" — when the flag is off, there is no org/slug, or the org has no
    published version for that slug in effect. ``None`` keeps the cost path
    byte-identical to pre-W4.
    """
    if not shop_library_enabled() or not org_id or not slug:
        return None
    now = as_of or _now()

    cached = _CACHE.get((org_id, slug))
    if cached is not None:
        ef, et = cached["effective_from"], cached["effective_to"]
        if ef is not None and ef <= now and (et is None or et > now):
            return cached["payload"]

    rows = (
        await session.execute(
            select(ShopProfileVersion).where(
                ShopProfileVersion.org_id == org_id,
                ShopProfileVersion.slug == slug,
                ShopProfileVersion.status == "published",
            )
        )
    ).scalars().all()
    row = select_effective(rows, now, slug=slug)
    if row is None:
        return None
    _CACHE[(org_id, slug)] = {
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
            select(func.max(ShopProfileVersion.version)).where(
                ShopProfileVersion.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    return int(current or 0) + 1


async def list_versions(session: AsyncSession, org_id: str) -> list:
    return list(
        (
            await session.execute(
                select(ShopProfileVersion)
                .where(ShopProfileVersion.org_id == org_id)
                .order_by(ShopProfileVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )


async def get_version(
    session: AsyncSession, org_id: str, version_id: int
) -> Optional[ShopProfileVersion]:
    return (
        await session.execute(
            select(ShopProfileVersion).where(
                ShopProfileVersion.org_id == org_id,
                ShopProfileVersion.id == version_id,
            )
        )
    ).scalars().first()


async def create_draft(
    session: AsyncSession,
    org_id: str,
    *,
    slug: str,
    name: str = "",
    change_note: str = "",
    payload: Optional[dict] = None,
    from_version_id: Optional[int] = None,
    created_by: Optional[int] = None,
) -> ShopProfileVersion:
    """Create a new DRAFT version for ``slug``. Payload defaults to the migrated
    flat-file profile (first draft of a known slug) or a deep copy of
    ``from_version_id`` (iterate on an existing governed profile)."""
    if not slug or not slug.strip():
        raise ValueError("shop profile requires a non-empty slug")
    # Canonicalize the slug so cost-path resolution (which normalizes the
    # caller's ?shop= via the same _slug) always matches the stored value.
    slug = _slug(slug)
    if payload is None:
        if from_version_id is not None:
            src = await get_version(session, org_id, from_version_id)
            if src is None:
                raise HTTPException(status_code=404, detail="source version not found")
            payload = copy.deepcopy(src.payload)
            slug = src.slug
        else:
            payload = default_shop_payload(slug)
    validate_shop_payload(payload)
    row = ShopProfileVersion(
        ulid=str(ULID()),
        org_id=org_id,
        version=await _next_version(session, org_id),
        slug=slug,
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
    slug: Optional[str] = None,
) -> ShopProfileVersion:
    row = await get_version(session, org_id, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")
    if row.status != "draft":
        raise HTTPException(
            status_code=409, detail="only draft versions can be edited"
        )
    if payload is not None:
        validate_shop_payload(payload)
        row.payload = payload
    if name is not None:
        row.name = name
    if change_note is not None:
        row.change_note = change_note
    if slug is not None and slug.strip():
        row.slug = _slug(slug)
    await session.flush()
    return row


async def discard_draft(
    session: AsyncSession, org_id: str, version_id: int
) -> ShopProfileVersion:
    """Delete a DRAFT version outright (governance: discard, not "hide").

    Only a draft may be discarded — a published or archived version is part of
    the org's audit trail (which shop numbers were actually in effect when) and
    must never be deleted. 409 otherwise.
    """
    row = await get_version(session, org_id, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")
    if row.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="only draft versions can be discarded; published/archived "
            "versions are the audit trail",
        )
    await session.delete(row)
    await session.flush()
    return row


async def archive_version(
    session: AsyncSession, org_id: str, version_id: int
) -> ShopProfileVersion:
    """Archive a PUBLISHED version: published -> archived.

    GUARD: the version currently IN EFFECT for its slug can NOT be archived —
    that would strand the cost path with no governed profile to resolve for that
    slug. A superseded published version (its ``effective_to`` already closed by a
    later publish) is fine to archive. Archived rows never resolve via
    ``select_effective`` (published-only), so an archived profile can never
    silently resolve as effective again.
    """
    row = await get_version(session, org_id, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")
    if row.status != "published":
        raise HTTPException(
            status_code=409, detail="only published versions can be archived"
        )
    now = _now()
    ef, et = row.effective_from, row.effective_to
    currently_in_effect = (
        ef is not None and ef <= now and (et is None or et > now)
    )
    if currently_in_effect:
        raise HTTPException(
            status_code=409,
            detail="cannot archive the version currently in effect for this "
            "slug; publish a replacement first",
        )
    row.status = "archived"
    await session.flush()
    invalidate(org_id, row.slug)
    return row


async def publish_version(
    session: AsyncSession,
    org_id: str,
    version_id: int,
    *,
    effective_from: Optional[datetime] = None,
) -> ShopProfileVersion:
    """Publish a draft: stamp ``effective_from`` and close the currently-open
    published version FOR THE SAME SLUG so that slug's timeline never overlaps."""
    row = await get_version(session, org_id, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")
    if row.status == "published":
        raise HTTPException(status_code=409, detail="version already published")
    if row.status != "draft":
        raise HTTPException(
            status_code=409, detail="only draft versions can be published"
        )
    validate_shop_payload(row.payload)

    now = _now()
    eff = effective_from or now
    if eff.tzinfo is None:
        eff = eff.replace(tzinfo=timezone.utc)
    if eff < now:
        raise HTTPException(
            status_code=400, detail="effective_from cannot be in the past"
        )

    # Close only the open published version for THIS slug (per-slug timeline).
    open_rows = (
        await session.execute(
            select(ShopProfileVersion).where(
                ShopProfileVersion.org_id == org_id,
                ShopProfileVersion.slug == row.slug,
                ShopProfileVersion.status == "published",
                ShopProfileVersion.effective_to.is_(None),
            )
        )
    ).scalars().all()
    for prev in open_rows:
        prev.effective_to = eff

    row.status = "published"
    row.effective_from = eff
    row.published_at = now
    await session.flush()
    invalidate(org_id, row.slug)
    return row


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def serialize_version(row: ShopProfileVersion, *, include_payload: bool = False) -> dict:
    out = {
        "id": row.id,
        "ulid": row.ulid,
        "version": row.version,
        "slug": row.slug,
        "name": row.name,
        "status": row.status,
        "change_note": row.change_note,
        "effective_from": _iso(row.effective_from),
        "effective_to": _iso(row.effective_to),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "published_at": _iso(row.published_at),
        # Honest posture: a governed shop profile is the org's DECLARED shop
        # calibration — bound as SHOP provenance, never measured/validated.
        "provenance": "shop",
        "validated": False,
    }
    if include_payload:
        out["payload"] = row.payload
    return out
