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

SELF-APPROVAL POLICY (ce-13): the proposer can't approve their own change when the
organization has another admin to review it (403 ``self_approval``); in a
single-admin organization they can, and the request is labelled ``self_approved``
so nobody reads it as a second pair of eyes. ``other_admins`` counts the admins
besides the reviewer from ``memberships``.

ONE WAY IN (C2): approval is the only path that publishes a governed version. The
libraries' own ``POST /{id}/publish`` routes refuse (403 ``review_required``, see
``review_required_refusal``), and a draft with an open request can't be edited
(409 ``under_review``, see ``open_request_for``), so the numbers an admin approves
are the numbers that go live.

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
from src.services import material_library_service, rate_library_service, shop_library_service

logger = logging.getLogger("cadverify.governance_service")

ASSET_RATE_CARD = "rate_card"
ASSET_SHOP_PROFILE = "shop_profile"
ASSET_MATERIAL_CATALOG = "material_catalog"
VALID_ASSET_TYPES = (ASSET_RATE_CARD, ASSET_SHOP_PROFILE, ASSET_MATERIAL_CATALOG)

# Dispatch table: asset_type -> the library service that owns its versions. All
# three expose the same thin adapter surface (get_version / publish_version), so
# the governance flow is asset-agnostic. Each one sets prices the costing engine
# uses (the rate card, a supplier's rates, material prices), so each is reviewed.
_LIBRARY = {
    ASSET_RATE_CARD: rate_library_service,
    ASSET_SHOP_PROFILE: shop_library_service,
    ASSET_MATERIAL_CATALOG: material_library_service,
}

# What each asset is called on the screens (Your shop › Changes to review).
ASSET_WORDS = {
    ASSET_RATE_CARD: "rate card",
    ASSET_SHOP_PROFILE: "supplier rate profile",
    ASSET_MATERIAL_CATALOG: "material catalog",
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


async def other_admins(session: AsyncSession, org_id: str, user_id: Optional[int]) -> int:
    """How many admins the organization has besides ``user_id``."""
    from sqlalchemy import func

    from src.db.models import Membership

    stmt = select(func.count()).select_from(Membership).where(
        Membership.org_id == org_id, Membership.org_role == "admin")
    if user_id is not None:
        stmt = stmt.where(Membership.user_id != user_id)
    return int((await session.execute(stmt)).scalar_one() or 0)


async def org_admins(session: AsyncSession, org_id: str) -> int:
    """How many admins the organization has (the review page says who can approve)."""
    return await other_admins(session, org_id, None)


async def review_required_refusal(
    session: AsyncSession,
    org_id: str,
    asset_type: str,
    version_id: int,
    user_id: Optional[int],
) -> HTTPException:
    """The 403 a library's direct publish route answers with (C2).

    A governed version is published only by approving its change request, as on
    the screens; the message says who approves in THIS organization, and the
    detail names the two calls that do it."""
    n = await other_admins(session, org_id, user_id)
    who = (
        "You're your organization's only admin, so you approve it yourself and it's marked self-approved."
        if n == 0
        else f"Another admin approves it: your organization has {n} other {'admin' if n == 1 else 'admins'}."
    )
    return HTTPException(status_code=403, detail={
        "code": "review_required",
        "message": (f"A {ASSET_WORDS.get(asset_type, asset_type)} is published when an admin approves its "
                    f"change request, as on Your shop › Changes to review. Propose this draft for review. {who}"),
        "propose": {"method": "POST", "path": "/api/v1/governance/change-requests",
                    "body": {"asset_type": asset_type, "target_version_id": version_id}},
        "approve": {"method": "POST", "path": "/api/v1/governance/change-requests/{id}/approve"},
    })


async def open_request_for(
    session: AsyncSession, org_id: str, asset_type: str, version_id: int
) -> Optional[ChangeRequest]:
    """The org's open (``proposed``) change request over this draft, if any."""
    return (
        await session.execute(
            select(ChangeRequest).where(
                ChangeRequest.org_id == org_id,
                ChangeRequest.asset_type == asset_type,
                ChangeRequest.target_version_id == version_id,
                ChangeRequest.status == "proposed",
            ).limit(1)
        )
    ).scalars().first()


async def refuse_edit_under_review(
    session: AsyncSession, org_id: str, asset_type: str, version_id: int
) -> None:
    """409 when the draft has an open change request: a reviewer approves the
    numbers they saw, so the draft can't change while it waits (C2)."""
    if await open_request_for(session, org_id, asset_type, version_id) is not None:
        raise HTTPException(status_code=409, detail={
            "code": "under_review",
            "message": ("This draft is waiting for review, so it can't be changed. An admin can reject the "
                        "change request; then edit the draft and propose it again."),
        })


# How a reviewer can have had a hand in the change they are asked to approve.
_HAND_WORDS = {
    "proposed": "You proposed this change",
    "wrote": "You wrote this draft",
    "edited": "You last edited this draft",
}


def self_approval_refusal(n_others: int, hand: str = "proposed") -> HTTPException:
    return HTTPException(status_code=403, detail={
        "code": "self_approval",
        "message": (f"{_HAND_WORDS.get(hand, _HAND_WORDS['proposed'])}, so another admin approves it. "
                    f"Your organization has {n_others} other {'admin' if n_others == 1 else 'admins'}."),
    })


def reviewer_hand(row: ChangeRequest, target: Any, reviewer_id: Optional[int]) -> Optional[str]:
    """How ``reviewer_id`` had a hand in this change: ``"proposed"`` it, ``"wrote"``
    the draft (its ``created_by``), ``"edited"`` it last (``edited_by``, where the
    library records it), else None. Any of them makes approving it a self-approval."""
    if reviewer_id is None:
        return None
    if row.proposed_by == reviewer_id:
        return "proposed"
    if target is not None and getattr(target, "created_by", None) == reviewer_id:
        return "wrote"
    if target is not None and getattr(target, "edited_by", None) == reviewer_id:
        return "edited"
    return None


async def approve(
    session: AsyncSession,
    org_id: str,
    request_id: int,
    reviewer_id: Optional[int],
    *,
    effective_from: Optional[datetime] = None,
) -> tuple[ChangeRequest, Any]:
    """Approve a PROPOSED change request and PUBLISH its target draft.

    Only a ``proposed`` request may be approved (404 if missing in the org, 409
    if already decided). On approval we stamp ``approved`` + ``decided_at`` +
    ``reviewed_by``, then delegate to the owning library's ``publish_version``
    so the draft is published through the one existing, tested code path.

    Returns ``(request, published_version)``. Any publish-time error (e.g. the
    draft was concurrently published, or an effective-date conflict) surfaces as
    the library's own HTTPException and the request is NOT marked approved.

    SELF-APPROVAL: refused (403 ``self_approval``) when the reviewer proposed it,
    wrote the draft or last edited it, and the org has another admin: anyone may
    propose any draft, so the proposer alone is not who wrote the numbers.
    Allowed in a single-admin org (and a proposer's approval is labelled
    ``self_approved``).

    ``effective_from`` (optional, not in the past) schedules the publish, as the
    libraries' direct publish used to; the reviewer picks it.
    """
    row = await _load_decidable(session, org_id, request_id)
    lib = _library_for(row.asset_type)
    hand = reviewer_hand(row, None, reviewer_id)
    if reviewer_id is not None and hand is None:
        target = await lib.get_version(session, org_id, row.target_version_id)
        hand = reviewer_hand(row, target, reviewer_id)
    if hand is not None:
        n = await other_admins(session, org_id, reviewer_id)
        if n > 0:
            raise self_approval_refusal(n, hand)
    # Publish FIRST so a publish failure (409/404/400) aborts before we mark the
    # request approved — approval and publish stay atomic within this session.
    published = await lib.publish_version(
        session, org_id, row.target_version_id, effective_from=effective_from
    )
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
        # Approved by the person who proposed it (only possible with no other admin).
        "self_approved": bool(row.status == "approved" and row.proposed_by is not None
                              and row.proposed_by == row.reviewed_by),
    }
