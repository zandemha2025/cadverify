"""Org membership-lifecycle API (§32) — create/invite/accept/members/switch.

The org-scoped router that finally makes CadVerify multi-user: an org admin can
invite teammates (single-use, hashed, expiring tokens), manage roles and
removals (last-admin protected), and any member can switch which org is active.
Sits on the same rails as the catalog / machine-inventory routers: per-route rate
limits, kill-switch gate on mutations, ``require_role`` / ``require_org_role``
auth (so the check_route_auth allowlist stays untouched — every route is authed),
and the ``resolve_org`` boundary.

Tenancy: every invite/member operation is scoped to the caller's ACTIVE org
(``ctx.org_id``, resolved via the current_org_id-validated membership). One org's
invites/members never leak into another's. Single-org callers are unaffected.

Honesty: invite tokens are generated with ``secrets``, stored only as a hash, and
returned to the admin exactly once; the email send is best-effort with a graceful
no-email fallback (the one-time link is always in the response).
"""
from __future__ import annotations

from src.config.public_urls import dashboard_origin, error_doc_url

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, Role, require_org_role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import org_service as svc
from src.services import org_saml_service as saml_svc

logger = logging.getLogger("cadverify.orgs")

router = APIRouter(tags=["orgs"])


# ── request bodies ────────────────────────────────────────────────────────────
class CreateOrgBody(BaseModel):
    name: str


class InviteBody(BaseModel):
    email: str
    role: str = "member"


class AcceptBody(BaseModel):
    token: str


class RoleBody(BaseModel):
    role: str


class SwitchBody(BaseModel):
    org_id: str


class SamlGroupMappingBody(BaseModel):
    attribute_name: str
    group_value: str
    org_role: str = "member"


# ── helpers ───────────────────────────────────────────────────────────────────
async def _ctx_org(ctx: OrgAuthContext, session: AsyncSession) -> str:
    """The caller's active org for an org-scoped write. A platform superadmin may
    carry no membership; fall back to ``resolve_org`` and 403 if there is none."""
    org_id = ctx.org_id or await resolve_org(session, ctx.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    return org_id


async def _emit(
    session: AsyncSession,
    actor_id: int,
    action: str,
    resource_id: Optional[str],
    detail: dict,
    *,
    org_id: Optional[str] = None,
) -> None:
    """Append an org-lifecycle event to the mutation transaction."""
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=actor_id,
        action=action,
        resource_type="org",
        resource_id=resource_id,
        detail=detail,
        org_id=org_id,
    )


def _invite_link(raw_token: str) -> str:
    return f"{dashboard_origin()}/orgs/accept?token={raw_token}"


def _send_invite_email(email: str, link: str, org_name: Optional[str]) -> bool:
    """Best-effort invite email via Resend. Returns True if a send was attempted.

    Graceful no-email fallback: when RESEND_API_KEY is unset (local/dev) we skip
    sending and rely on the one-time link returned to the admin in the response —
    the flow never breaks on missing email infra. Mirrors magic_link's sender.
    """
    if not os.getenv("RESEND_API_KEY") or not os.getenv("RESEND_FROM"):
        return False
    try:
        import resend

        resend.api_key = os.environ["RESEND_API_KEY"]
        who = f" to {org_name}" if org_name else ""
        resend.Emails.send(
            {
                "from": os.environ["RESEND_FROM"],
                "to": email,
                "subject": "You've been invited to a ProofShape organization",
                "html": (
                    f'<p>You\'ve been invited{who}.</p>'
                    f'<p><a href="{link}">Accept the invitation</a> '
                    f"(expires in {svc._invite_ttl_days()} days).</p>"
                ),
            }
        )
        return True
    except Exception:
        # Never break invite creation on an email failure — the admin still has
        # the one-time link in the response.
        logger.warning("invite email send failed for %s", email, exc_info=True)
        return False


# ── org create / list / switch ────────────────────────────────────────────────
@router.post("", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def create_org(
    request: Request,
    response: Response,
    body: CreateOrgBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a named org; the caller becomes its admin. Personal orgs and the
    caller's active org are unaffected (no auto-switch)."""
    org = await svc.create_org(session, user.user_id, body.name)
    await _emit(
        session, user.user_id, "org.created", org.id, {"name": org.name}, org_id=org.id
    )
    await session.commit()
    response.status_code = 201
    return {"org_id": org.id, "name": org.name, "slug": org.slug, "org_role": "admin"}


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_orgs(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Every org the caller belongs to + which one is active."""
    return await svc.list_my_orgs(session, user.user_id)


@router.post("/switch", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;600/day")
async def switch_org(
    request: Request,
    response: Response,
    body: SwitchBody,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Set the caller's active org using a dashboard session only.

    Bearer API keys are permanently bound to their issuing organization. Letting
    a key mutate ``users.current_org_id`` would move that credential, and every
    user-scoped route behind it, across the tenant boundary.
    """
    if user.org_id is not None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "api_key_org_bound",
                "message": (
                    "API keys cannot switch organizations. "
                    "Use a dashboard session to switch organizations."
                ),
                "doc_url": error_doc_url("api_key_org_bound"),
            },
        )
    result = await svc.switch_org(session, user.user_id, body.org_id)
    await _emit(
        session,
        user.user_id,
        "org.switched",
        body.org_id,
        {"org_role": result["org_role"]},
        org_id=body.org_id,
    )
    await session.commit()
    return result


# ── SAML group mappings ───────────────────────────────────────────────────────
@router.get("/saml/group-mappings")
@limiter.limit("120/hour;1000/day")
async def list_saml_group_mappings(
    request: Request,
    response: Response,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """List the caller org's SAML JIT group-to-role mappings."""
    org_id = await _ctx_org(ctx, session)
    return {"mappings": await saml_svc.list_saml_group_mappings(session, org_id)}


@router.post("/saml/group-mappings", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;300/day")
async def create_saml_group_mapping(
    request: Request,
    response: Response,
    body: SamlGroupMappingBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Create one SAML JIT mapping for the caller org."""
    org_id = await _ctx_org(ctx, session)
    row = await saml_svc.create_saml_group_mapping(
        session,
        org_id,
        attribute_name=body.attribute_name,
        group_value=body.group_value,
        org_role=body.org_role,
        created_by=ctx.user_id,
    )
    await _emit(
        session,
        ctx.user_id,
        "saml.group_mapping.created",
        str(row.id),
        {
            "org_id": org_id,
            "attribute_name": row.attribute_name,
            "group_value": row.group_value,
            "org_role": row.org_role,
        },
        org_id=org_id,
    )
    await session.commit()
    response.status_code = 201
    return saml_svc.serialize_mapping(row)


@router.delete(
    "/saml/group-mappings/{mapping_id}",
    dependencies=[Depends(require_kill_switch_open)],
)
@limiter.limit("60/hour;300/day")
async def delete_saml_group_mapping(
    request: Request,
    response: Response,
    mapping_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Delete one SAML JIT mapping from the caller org."""
    org_id = await _ctx_org(ctx, session)
    row = await saml_svc.delete_saml_group_mapping(session, org_id, mapping_id)
    await _emit(
        session,
        ctx.user_id,
        "saml.group_mapping.deleted",
        str(row.id),
        {
            "org_id": org_id,
            "attribute_name": row.attribute_name,
            "group_value": row.group_value,
            "org_role": row.org_role,
        },
        org_id=org_id,
    )
    await session.commit()
    return {"deleted": True, "id": row.id, "org_id": org_id}


# ── invites ───────────────────────────────────────────────────────────────────
@router.post("/invites", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("20/hour;100/day")
async def create_invite(
    request: Request,
    response: Response,
    body: InviteBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Invite an email to the caller's org at a role (admin-only; role may not
    exceed the inviter's). Returns the one-time accept link; emails it when
    configured (graceful no-email fallback otherwise). Rate-limited (no spam)."""
    org_id = await _ctx_org(ctx, session)
    invite, raw = await svc.create_invite(
        session, org_id, ctx.org_role, body.email, body.role, ctx.user_id
    )
    await _emit(
        session,
        ctx.user_id,
        "member.invited",
        str(invite.id),
        {"org_id": org_id, "email": invite.email, "role": invite.role},
        org_id=org_id,
    )
    await session.commit()
    link = _invite_link(raw)
    emailed = _send_invite_email(invite.email, link, None)
    response.status_code = 201
    out = svc.serialize_invite(invite)
    # The raw token / accept link is returned exactly once, here, and never
    # persisted — the admin forwards it if email is not configured.
    out["accept_link"] = link
    out["emailed"] = emailed
    return out


@router.get("/invites")
@limiter.limit("120/hour;1000/day")
async def list_invites(
    request: Request,
    response: Response,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """List the org's invites (pending/accepted/expired/revoked). No tokens."""
    org_id = await _ctx_org(ctx, session)
    return {"invites": await svc.list_invites(session, org_id)}


@router.post("/invites/accept", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;300/day")
async def accept_invite(
    request: Request,
    response: Response,
    body: AcceptBody,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Accept an invite with the raw token → a membership (single-use, expiry +
    revoke enforced; the token is hash-compared). Accepting never escalates an
    existing member's role."""
    membership, invite, created = await svc.accept_invite(
        session, user.user_id, body.token
    )
    if created:
        await _emit(
            session,
            user.user_id,
            "member.joined",
            str(invite.id),
            {"org_id": invite.org_id, "role": membership.org_role},
            org_id=invite.org_id,
        )
    await session.commit()
    return {
        "org_id": membership.org_id,
        "org_role": membership.org_role,
        "created": created,
    }


@router.delete("/invites/{invite_id}", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;300/day")
async def revoke_invite(
    request: Request,
    response: Response,
    invite_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Revoke a pending invite (org-scoped). 404 if absent; 409 if accepted."""
    org_id = await _ctx_org(ctx, session)
    inv = await svc.revoke_invite(session, org_id, invite_id)
    await session.commit()
    return svc.serialize_invite(inv)


# ── members ───────────────────────────────────────────────────────────────────
@router.get("/members")
@limiter.limit("120/hour;1000/day")
async def list_members(
    request: Request,
    response: Response,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """List the caller org's members with their org roles."""
    org_id = await _ctx_org(ctx, session)
    return {"members": await svc.list_members(session, org_id)}


@router.patch(
    "/members/{user_id}/role", dependencies=[Depends(require_kill_switch_open)]
)
@limiter.limit("120/hour;600/day")
async def change_member_role(
    request: Request,
    response: Response,
    user_id: int,
    body: RoleBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Change a member's org role (admin-only). The last admin cannot be
    demoted (an org must always keep at least one admin)."""
    org_id = await _ctx_org(ctx, session)
    m = await svc.change_member_role(session, org_id, user_id, body.role)
    await _emit(
        session,
        ctx.user_id,
        "member.role_changed",
        str(user_id),
        {"org_id": org_id, "new_role": m.org_role},
        org_id=org_id,
    )
    await session.commit()
    return {"user_id": user_id, "org_role": m.org_role}


@router.delete("/members/{user_id}", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;600/day")
async def remove_member(
    request: Request,
    response: Response,
    user_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Remove a member (admin-only) or leave the org yourself. The last admin
    can neither be removed nor leave. A removed member loses access immediately."""
    org_id = await _ctx_org(ctx, session)
    is_self = user_id == ctx.user_id
    if not is_self and not (ctx.is_superadmin or ctx.org_role == "admin"):
        # A non-admin may only remove THEMSELVES (self-leave).
        raise HTTPException(
            status_code=403,
            detail={
                "code": "insufficient_org_role",
                "message": "Only an org admin may remove another member.",
                "doc_url": error_doc_url("insufficient_org_role"),
            },
        )
    await svc.remove_member(session, org_id, user_id, ctx.user_id)
    await _emit(
        session,
        ctx.user_id,
        "member.left" if is_self else "member.removed",
        str(user_id),
        {"org_id": org_id},
        org_id=org_id,
    )
    await session.commit()
    return {"removed": True, "user_id": user_id, "org_id": org_id}
