"""Org membership-lifecycle service (§32 + §39).

The service layer for the membership seam that sits on top of 0009's tenancy
ISOLATION: create named orgs, invite/accept members (single-use hashed expiring
tokens), list/role-change/remove members (with last-admin protection), leave, and
switch the active org. Org resolution (``resolve_org`` / ``caller_org_subquery``)
already validates ``users.current_org_id`` against a live membership, so a switch
takes effect immediately and a removed member loses access on the very next read.

HONESTY / SECURITY rails:
  * Invite tokens are generated with ``secrets``, stored ONLY as a SHA-256 hash
    (the raw token is returned once and never persisted/logged), single-use, and
    expiring (default 7 days). A DB leak cannot be replayed into a membership.
  * An invite's role may never exceed the inviter's own org role; accepting an
    invite may never ESCALATE an existing member's role.
  * An invite is bound to its recipient email — only the account whose email
    matches may redeem it, so a leaked/forwarded token cannot be claimed by a
    different logged-in user (no cross-account grant, incl. admin seats).
  * An org can never lose its last admin (demote/remove/leave all guard it).

Single-org invariant: none of this changes behaviour for a user with exactly one
(personal) org — the whole existing isolation matrix passes unchanged.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.disposable import normalize_email
from src.auth.org_context import personal_org_slug
from src.db.models import Membership, OrgInvite, Organization, User

# admin(3) > member(2) > viewer(1) — mirrors rbac.OrgRole ranks.
ORG_ROLE_RANK = {"viewer": 1, "member": 2, "admin": 3}
VALID_ORG_ROLES = frozenset(ORG_ROLE_RANK)

_DEFAULT_INVITE_TTL_DAYS = 7
_MAX_INVITE_TTL_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _invite_ttl_days() -> int:
    try:
        d = int(os.getenv("ORG_INVITE_TTL_DAYS", str(_DEFAULT_INVITE_TTL_DAYS)))
    except ValueError:
        d = _DEFAULT_INVITE_TTL_DAYS
    return max(1, min(d, _MAX_INVITE_TTL_DAYS))


# ---------------------------------------------------------------------------
# Token helpers (secrets-generated, stored hashed, never logged)
# ---------------------------------------------------------------------------


def generate_invite_token() -> tuple[str, str]:
    """Return ``(raw_token, token_hash)``. Only the hash is ever persisted."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_invite_token(raw)


def hash_invite_token(raw: str) -> str:
    """SHA-256 hex of the raw token — the accept-path lookup/compare key."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _403(msg: str) -> HTTPException:
    return HTTPException(status_code=403, detail=msg)


def _404(msg: str) -> HTTPException:
    return HTTPException(status_code=404, detail=msg)


def _409(msg: str) -> HTTPException:
    return HTTPException(status_code=409, detail=msg)


def _400(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


# ---------------------------------------------------------------------------
# Membership reads
# ---------------------------------------------------------------------------


async def _get_membership(
    session: AsyncSession, org_id: str, user_id: int
) -> Optional[Membership]:
    return (
        await session.execute(
            select(Membership).where(
                Membership.org_id == org_id,
                Membership.user_id == user_id,
            )
        )
    ).scalars().first()


async def _admin_count(session: AsyncSession, org_id: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id == org_id, Membership.org_role == "admin")
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# Create org
# ---------------------------------------------------------------------------


async def create_org(
    session: AsyncSession, user_id: int, name: str
) -> Organization:
    """Create a named org; the creator becomes its ``admin``.

    Does NOT switch the caller into the new org (``current_org_id`` is
    unchanged), so personal orgs and the caller's active org are unaffected —
    the caller opts in explicitly via ``switch_org``. Returns the new org.
    """
    clean = (name or "").strip()
    if not clean:
        raise _400("Organization name is required.")
    if len(clean) > 200:
        raise _400("Organization name is too long (max 200).")

    org_id = str(ULID())
    slug = f"{personal_org_slug(clean.replace(' ', '-'))}"
    org = Organization(id=org_id, name=clean, slug=slug)
    session.add(org)
    session.add(
        Membership(
            id=str(ULID()), org_id=org_id, user_id=user_id, org_role="admin"
        )
    )
    await session.flush()
    return org


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


async def create_invite(
    session: AsyncSession,
    org_id: str,
    inviter_role: str,
    email: str,
    role: str,
    created_by: int,
) -> tuple[OrgInvite, str]:
    """Issue a single-use, hashed, expiring invite; return ``(invite, raw_token)``.

    ``role`` must be a valid org role and may NOT exceed the inviter's own org
    role (a member cannot mint an admin invite). The raw token is returned once
    (emailed / handed to the admin) and NEVER persisted.
    """
    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        raise _400("A valid invitee email is required.")
    if role not in VALID_ORG_ROLES:
        raise _400(
            f"Invalid role '{role}'. Must be one of {sorted(VALID_ORG_ROLES)}."
        )
    # A superadmin acting without an org membership resolves inviter_role None —
    # they are platform staff and may issue any role. Otherwise cap at the
    # inviter's rank so authority is never escalated through an invite.
    if inviter_role is not None:
        if ORG_ROLE_RANK.get(role, 99) > ORG_ROLE_RANK.get(inviter_role, 0):
            raise _403(
                "An invite's role may not exceed your own org role "
                f"({inviter_role})."
            )

    raw, token_hash = generate_invite_token()
    invite = OrgInvite(
        org_id=org_id,
        email=email_norm,
        role=role,
        token_hash=token_hash,
        expires_at=_now() + timedelta(days=_invite_ttl_days()),
        created_by=created_by,
    )
    session.add(invite)
    await session.flush()
    return invite, raw


def _invite_status(inv: OrgInvite) -> str:
    if inv.accepted_at is not None:
        return "accepted"
    if inv.revoked_at is not None:
        return "revoked"
    if inv.expires_at is not None and _as_aware(inv.expires_at) < _now():
        return "expired"
    return "pending"


def _as_aware(dt: datetime) -> datetime:
    """Treat a naive timestamp (defensive) as UTC for comparison."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def serialize_invite(inv: OrgInvite) -> dict:
    """Public invite view — NEVER includes the token or its hash."""
    return {
        "id": inv.id,
        "org_id": inv.org_id,
        "email": inv.email,
        "role": inv.role,
        "status": _invite_status(inv),
        "created_by": inv.created_by,
        "accepted_by": inv.accepted_by,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
        "revoked_at": inv.revoked_at.isoformat() if inv.revoked_at else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


async def list_invites(session: AsyncSession, org_id: str) -> list[dict]:
    rows = (
        await session.execute(
            select(OrgInvite)
            .where(OrgInvite.org_id == org_id)
            .order_by(OrgInvite.id.desc())
        )
    ).scalars().all()
    return [serialize_invite(r) for r in rows]


async def revoke_invite(
    session: AsyncSession, org_id: str, invite_id: int
) -> OrgInvite:
    """Revoke a pending invite (org-scoped). 404 if absent; 409 if not pending."""
    inv = (
        await session.execute(
            select(OrgInvite).where(
                OrgInvite.id == invite_id, OrgInvite.org_id == org_id
            )
        )
    ).scalars().first()
    if inv is None:
        raise _404("Invite not found.")
    if inv.accepted_at is not None:
        raise _409("Invite has already been accepted.")
    if inv.revoked_at is not None:
        return inv  # idempotent
    inv.revoked_at = _now()
    await session.flush()
    return inv


async def accept_invite(
    session: AsyncSession, user_id: int, raw_token: str
) -> tuple[Membership, OrgInvite, bool]:
    """Redeem a raw token → a membership for ``user_id``. Returns
    ``(membership, invite, created)`` where ``created`` is False when the user
    was already a member (in which case the role is NOT escalated).

    Enforces single-use (``accepted_at``/``revoked_at`` NULL), expiry, the hash
    compare (the raw token is never stored), AND recipient binding: only the
    account whose email matches the invite's may redeem it. A leaked/forwarded
    token cannot be claimed by another logged-in user, and an invite can never
    escalate a *different* account into the org (including at admin). Consumes
    the invite atomically with the membership write.
    """
    if not raw_token or not raw_token.strip():
        raise _400("An invite token is required.")
    token_hash = hash_invite_token(raw_token.strip())
    inv = (
        await session.execute(
            select(OrgInvite).where(OrgInvite.token_hash == token_hash)
        )
    ).scalars().first()
    if inv is None:
        raise _404("Invite not found or already used.")
    if inv.revoked_at is not None:
        raise _409("This invite has been revoked.")
    if inv.accepted_at is not None:
        raise _409("This invite has already been used.")
    if _as_aware(inv.expires_at) < _now():
        raise _409("This invite has expired.")

    # Recipient binding (§39): an invite is bound to the email it was minted
    # for, and may be redeemed by EXACTLY the invited account — no other.
    #
    # We bind to the account's REAL uniqueness key: ``users.email_lower`` is the
    # column the unique index and every login lookup key on, so it — not a fresh
    # re-derivation from ``accepting.email`` — is the identity that must match.
    # Compare it against the invite email reduced the SAME way (``normalize_email``:
    # lower-case, strip +tags, collapse gmail dots), which is exactly how every
    # provisioning path sets ``email_lower`` (password/oauth/magic, and SAML after
    # the saml.py fix that made its ``email_lower`` normalised too).
    #
    # The prior guard re-derived with ``normalize_email(accepting.email)`` and was
    # UNSOUND: because SAML historically stored a NON-normalised ``email_lower``
    # (dots/+tags retained), two DISTINCT account rows can normalise-collide
    # (e.g. ``a.b@gmail.com`` vs ``ab@gmail.com``). Re-normalising the wrong
    # account's raw email then matched the invite, letting a *different* account
    # redeem — including into an ADMIN seat in another tenant. Keying on the
    # stored ``email_lower`` (a real, unique row identity) closes that: a colliding
    # SAML row's own ``email_lower`` differs from the normalised invite key, so it
    # is refused. Without any binding, any authenticated holder of the raw token
    # (email forward, shared inbox, no-email admin paste, shoulder-surf) could
    # claim the seat.
    accepting = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if accepting is None:
        raise _404("Accepting user not found.")
    account_key = accepting.email_lower or normalize_email(accepting.email or "")
    if account_key != normalize_email(inv.email):
        raise _403("This invite was issued to a different email address.")

    existing = await _get_membership(session, inv.org_id, user_id)
    if existing is not None:
        # Already a member — consume the invite but DO NOT escalate the role.
        created = False
        membership = existing
    else:
        membership = Membership(
            id=str(ULID()),
            org_id=inv.org_id,
            user_id=user_id,
            org_role=inv.role,
        )
        session.add(membership)
        created = True

    inv.accepted_by = user_id
    inv.accepted_at = _now()
    await session.flush()
    return membership, inv, created


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


async def list_members(session: AsyncSession, org_id: str) -> list[dict]:
    rows = (
        await session.execute(
            select(
                User.id,
                User.email,
                User.is_active,
                Membership.org_role,
                Membership.created_at,
            )
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.org_id == org_id)
            .order_by(Membership.created_at.asc(), Membership.id.asc())
        )
    ).all()
    return [
        {
            "user_id": uid,
            "email": email,
            "is_active": bool(is_active),
            "org_role": org_role,
            "joined_at": created_at.isoformat() if created_at else None,
        }
        for (uid, email, is_active, org_role, created_at) in rows
    ]


async def change_member_role(
    session: AsyncSession, org_id: str, target_user_id: int, new_role: str
) -> Membership:
    """Change a member's org role. Last-admin protected: the final admin may not
    be demoted (an org can never lose its last admin)."""
    if new_role not in VALID_ORG_ROLES:
        raise _400(
            f"Invalid role '{new_role}'. Must be one of {sorted(VALID_ORG_ROLES)}."
        )
    m = await _get_membership(session, org_id, target_user_id)
    if m is None:
        raise _404("User is not a member of this organization.")
    if m.org_role == "admin" and new_role != "admin":
        if await _admin_count(session, org_id) <= 1:
            raise _409(
                "Cannot demote the last admin — an org must keep at least one."
            )
    m.org_role = new_role
    await session.flush()
    return m


async def remove_member(
    session: AsyncSession,
    org_id: str,
    target_user_id: int,
    actor_user_id: int,
) -> bool:
    """Remove a member from an org (self-leave when target == actor).

    Last-admin protected: the final admin can neither be removed nor leave.
    Returns True on removal. The removed member loses access IMMEDIATELY because
    org resolution re-validates membership on every request.
    """
    m = await _get_membership(session, org_id, target_user_id)
    if m is None:
        raise _404("User is not a member of this organization.")
    if m.org_role == "admin" and await _admin_count(session, org_id) <= 1:
        raise _409(
            "Cannot remove the last admin — an org must keep at least one."
        )
    await session.delete(m)
    # If the removed member's active org pointed here, clear it so resolution
    # falls back to a real membership (never leaks the removed org).
    await session.execute(
        User.__table__.update()
        .where(User.id == target_user_id, User.current_org_id == org_id)
        .values(current_org_id=None)
    )
    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Switch active org
# ---------------------------------------------------------------------------


async def switch_org(
    session: AsyncSession, user_id: int, target_org_id: str
) -> dict:
    """Set ``users.current_org_id`` to ``target_org_id`` after validating it is a
    LIVE membership. A non-membership target 403s (never silently switches)."""
    m = await _get_membership(session, target_org_id, user_id)
    if m is None:
        raise _403("You are not a member of that organization.")
    await session.execute(
        User.__table__.update()
        .where(User.id == user_id)
        .values(current_org_id=target_org_id)
    )
    await session.flush()
    org = (
        await session.execute(
            select(Organization).where(Organization.id == target_org_id)
        )
    ).scalars().first()
    return {
        "org_id": target_org_id,
        "name": org.name if org is not None else None,
        "org_role": m.org_role,
    }


async def list_my_orgs(session: AsyncSession, user_id: int) -> dict:
    """Every org the caller belongs to + which one is active (resolved)."""
    from src.auth.org_context import resolve_org

    rows = (
        await session.execute(
            select(
                Organization.id,
                Organization.name,
                Membership.org_role,
                Membership.created_at,
            )
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at.asc(), Membership.id.asc())
        )
    ).all()
    active = await resolve_org(session, user_id)
    return {
        "active_org_id": active,
        "organizations": [
            {
                "org_id": oid,
                "name": name,
                "org_role": org_role,
                "joined_at": created_at.isoformat() if created_at else None,
                "is_active": oid == active,
            }
            for (oid, name, org_role, created_at) in rows
        ],
    }


# ---------------------------------------------------------------------------
# Account-level deactivation (superadmin; enforced at the router)
# ---------------------------------------------------------------------------


async def set_user_active(
    session: AsyncSession, target_user_id: int, active: bool
) -> dict:
    """Flip a user's ``is_active`` flag (True = reactivate, False = deactivate).

    Deactivation is account-level (blocks every auth path via the is_active
    gate); org admins only REMOVE members from their org. Idempotent.
    """
    user = (
        await session.execute(select(User).where(User.id == target_user_id))
    ).scalars().first()
    if user is None:
        raise _404("User not found.")
    user.is_active = active
    user.deactivated_at = None if active else _now()
    await session.flush()
    return {
        "user_id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "deactivated_at": (
            user.deactivated_at.isoformat() if user.deactivated_at else None
        ),
    }
