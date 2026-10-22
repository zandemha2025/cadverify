"""Who may sign off a recorded make-or-buy decision, and the signer's name.

An organization chooses the role allowed to sign off (``organizations.
signoff_role``, migration 0056): ``member`` (anyone who can record an outcome,
the default) or ``admin`` (organization admins only). A sign-off reuses the
decision's ``approved_by_user_id / approved_at / approval_note``; staleness is the
decision's ``stale_at / stale_reason`` (rates, machines, specs, conditions or a
calibration changed after it was computed).

Pure rules first (unit-tested without a DB), thin adapters below.
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Membership, Organization, User

SIGNOFF_ROLES = ("member", "admin")
DEFAULT_SIGNOFF_ROLE = "member"
_RANK = {"viewer": 1, "member": 2, "admin": 3}
ROLE_WORDS = {"member": "Members and admins", "admin": "Admins only"}


def effective_role(stored: Optional[str]) -> str:
    return stored if stored in SIGNOFF_ROLES else DEFAULT_SIGNOFF_ROLE


def may_sign_off(org_role: Optional[str], signoff_role: Optional[str], *, is_superadmin: bool = False) -> bool:
    """True when an organization role clears the organization's sign-off rule."""
    if is_superadmin:
        return True
    need = _RANK[effective_role(signoff_role)]
    return _RANK.get(org_role or "", 0) >= need


def refusal(signoff_role: Optional[str]) -> str:
    if effective_role(signoff_role) == "admin":
        return "Only organization admins can sign off decisions in this organization."
    return "Members and admins can sign off decisions; viewers can't."


async def get_role(session: AsyncSession, org_id: str) -> str:
    row = (await session.execute(select(Organization.signoff_role).where(Organization.id == org_id))).first()
    return effective_role(row[0] if row else None)


async def set_role(session: AsyncSession, org_id: str, role: Optional[str]) -> str:
    if role is not None and role not in SIGNOFF_ROLES:
        raise ValueError("signoff_role must be 'member' or 'admin'")
    org = await session.get(Organization, org_id)
    if org is None:
        raise ValueError("organization not found")
    org.signoff_role = role
    await session.flush()
    return effective_role(role)


async def org_role_of(session: AsyncSession, org_id: str, user_id: int) -> Optional[str]:
    row = (await session.execute(
        select(Membership.org_role).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )).first()
    return row[0] if row else None


async def names_for(session: AsyncSession, user_ids: Iterable[Optional[int]]) -> dict:
    """``{user_id: name}``: the person's full name, else their email."""
    ids = sorted({int(u) for u in user_ids if isinstance(u, int)})
    if not ids:
        return {}
    rows = (await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))).all()
    return {r[0]: ((r[1] or "").strip() or r[2]) for r in rows}


_STALE_WORDS = {
    "machine_inventory_changed": "your machines changed",
    "rate_library_published": "new rates were published",
    "material_library_published": "new material prices were published",
    "shop_profile_published": "a shop profile was updated",
    "part_specs_changed": "the part's specs changed",
    "conditions_changed": "the part's service conditions changed",
    "calibration_changed": "a calibration was applied or undone",
}


def stale_words(reason: Optional[str]) -> str:
    """Why a record went out of date, in words ("part_specs_changed" → "the part's specs changed")."""
    if not reason:
        return "something it used changed"
    return _STALE_WORDS.get(reason.split(":", 1)[0], reason.replace("_", " ").replace(":", " "))


def signoff_view(gov: dict, names: dict) -> Optional[dict]:
    """The sign-off as shown on a part, the catalog board and the pilot report.

    ``None`` when the decision isn't signed off. ``stale`` says plainly that
    what was signed off has changed since (the reason travels with it).
    """
    if (gov or {}).get("approval_status") != "approved":
        return None
    uid = gov.get("approved_by_user_id")
    return {
        "by_user_id": uid,
        "by": names.get(uid) if uid is not None else None,
        "at": gov.get("approved_at"),
        "note": gov.get("approval_note"),
        "stale": bool(gov.get("is_stale")),
        "stale_reason": gov.get("stale_reason") if gov.get("is_stale") else None,
        "stale_at": gov.get("stale_at") if gov.get("is_stale") else None,
    }
