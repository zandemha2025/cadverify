"""Governance change-request service (W4 governance zone, MVP).

The "change request -> review -> publish" flow over the governed rate-card and
shop-profile libraries. A member PROPOSES a DRAFT version for review; an org
admin either APPROVES it — which PUBLISHES the draft through the library's
existing, tested ``publish_version`` path — or REJECTS it, leaving the draft a
draft. This is a thin governance GATE on top of the real publish machinery, not
a reimplementation of it.

Design mirrors the sibling library services: the SQLAlchemy adapters here are
thin; the actual versioning / effective-dating / validation semantics live in
``rate_library_service`` / ``shop_library_service`` and are unchanged. Approval
delegates to those modules' ``publish_version`` so there is exactly one publish
code path (honest: governance decides WHO may trigger the switch and records the
review, it does not duplicate the switch).

SELF-APPROVAL POLICY (v1, DOCUMENTED DEFAULT): v1 is PERMISSIVE — any org admin
may approve, including the proposer. Real separation-of-duties (reviewer must
differ from proposer) is a later slice; enforcing it now would gate behavior the
tests don't cover. The seam is here (``approve`` receives ``reviewer_id`` and
the row carries ``proposed_by``) so a future ``allow_self_approve=False`` is a
one-line guard with its own test.

HONESTY (non-negotiable rules #1/#2): governance never launders an assumption
into a fact. Approving a change request only triggers the existing publish path;
it changes WHICH default/shop numbers an org uses and WHO may flip the switch. It
never flips a decision to ``validated`` (that comes only from real ground-truth
residuals, W5).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import ChangeRequest
from src.services import rate_library_service, shop_library_service

logger = logging.getLogger("cadverify.governance_service")

ASSET_RATE_CARD = "rate_card"
ASSET_SHOP_PROFILE = "shop_profile"
VALID_ASSET_TYPES = (ASSET_RATE_CARD, ASSET_SHOP_PROFILE)

# Dispatch table: asset_type -> the library service that owns its versions. Both
# expose the same thin adapter surface (get_version / publish_version), so the
# governance flow is asset-agnostic.
_LIBRARY = {
    ASSET_RATE_CARD: rate_library_service,
    ASSET_SHOP_PROFILE: shop_library_service,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _library_for(asset_type: str):
    lib = _LIBRARY.get(asset_type)
    if lib is None:
        raise HTTPException(
            status_code=400,
            detail=f"asset_type must be one of {list(VALID_ASSET_TYPES)}",
        )
    return lib


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


async def propose(
    session: AsyncSession,
    org_id: str,
    asset_type: str,
    target_version_id: int,
    *,
    title: str = "",
    note: str = "",
    proposed_by: Optional[int] = None,
) -> ChangeRequest:
    """Open a change request over a DRAFT version.

    Verifies the target version exists IN THIS ORG and is still a ``draft`` (a
    published/archived version is not a proposable change — 404 if missing in
    the org, 400 if not a draft). Creates a ``proposed`` ChangeRequest. The
    ``asset_type`` dispatches to the owning library's ``get_version``.
    """
    lib = _library_for(asset_type)
    target = await lib.get_version(session, org_id, target_version_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target version not found")
    if target.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="only a draft version can be proposed for review; "
            f"target is '{target.status}'",
        )
    row = ChangeRequest(
        ulid=str(ULID()),
        org_id=org_id,
        asset_type=asset_type,
        target_version_id=target_version_id,
        status="proposed",
        title=title or "",
        note=note or "",
        proposed_by=proposed_by,
    )
    session.add(row)
    await session.flush()
    return row


async def list_requests(
    session: AsyncSession, org_id: str, status: Optional[str] = None
) -> list[ChangeRequest]:
    """All change requests for the org, newest first; optionally by ``status``."""
    stmt = select(ChangeRequest).where(ChangeRequest.org_id == org_id)
    if status is not None:
        stmt = stmt.where(ChangeRequest.status == status)
    stmt = stmt.order_by(ChangeRequest.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_request(
    session: AsyncSession, org_id: str, request_id: int
) -> Optional[ChangeRequest]:
    return (
        await session.execute(
            select(ChangeRequest).where(
                ChangeRequest.org_id == org_id,
                ChangeRequest.id == request_id,
            )
        )
    ).scalars().first()


async def approve(
    session: AsyncSession,
    org_id: str,
    request_id: int,
    reviewer_id: Optional[int],
) -> tuple[ChangeRequest, Any]:
    """Approve a PROPOSED change request and PUBLISH its target draft.

    Only a ``proposed`` request may be approved (404 if missing in the org, 409
    if already decided). On approval we stamp ``approved`` + ``decided_at`` +
    ``reviewed_by``, then delegate to the owning library's ``publish_version``
    so the draft is published through the one existing, tested code path.

    Returns ``(request, published_version)``. Any publish-time error (e.g. the
    draft was concurrently published, or an effective-date conflict) surfaces as
    the library's own HTTPException and the request is NOT marked approved.

    SELF-APPROVAL: permitted in v1 (see module docstring). ``reviewer_id`` is
    recorded so a future separation-of-duties policy has the data it needs.
    """
    row = await _load_decidable(session, org_id, request_id)
    lib = _library_for(row.asset_type)
    # Publish FIRST so a publish failure (409/404/400) aborts before we mark the
    # request approved — approval and publish stay atomic within this session.
    published = await lib.publish_version(session, org_id, row.target_version_id)
    row.status = "approved"
    row.reviewed_by = reviewer_id
    row.decided_at = _now()
    await session.flush()
    return row, published


async def reject(
    session: AsyncSession,
    org_id: str,
    request_id: int,
    reviewer_id: Optional[int],
    note: str = "",
) -> ChangeRequest:
    """Reject a PROPOSED change request — the draft stays a draft (not published).

    Only a ``proposed`` request may be rejected (404 if missing in the org, 409
    if already decided). Stamps ``rejected`` + ``decided_at`` + ``reviewed_by``;
    an optional ``note`` appends the reviewer's reason.
    """
    row = await _load_decidable(session, org_id, request_id)
    row.status = "rejected"
    row.reviewed_by = reviewer_id
    row.decided_at = _now()
    if note:
        row.note = f"{row.note}\n{note}".strip() if row.note else note
    await session.flush()
    return row


async def _load_decidable(
    session: AsyncSession, org_id: str, request_id: int
) -> ChangeRequest:
    """Load a change request that is still open for a decision.

    404 if it does not exist in the org (never a cross-tenant read/decision);
    409 if it has already been decided (approved/rejected are terminal).
    """
    row = await get_request(session, org_id, request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="change request not found")
    if row.status != "proposed":
        raise HTTPException(
            status_code=409,
            detail=f"change request already {row.status}",
        )
    return row


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def serialize_request(row: ChangeRequest) -> dict:
    return {
        "id": row.id,
        "ulid": row.ulid,
        "org_id": row.org_id,
        "asset_type": row.asset_type,
        "target_version_id": row.target_version_id,
        "status": row.status,
        "title": row.title,
        "note": row.note,
        "proposed_by": row.proposed_by,
        "reviewed_by": row.reviewed_by,
        "created_at": _iso(row.created_at),
        "decided_at": _iso(row.decided_at),
    }
