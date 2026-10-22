"""Org membership-lifecycle API (§32) — create/invite/accept/members/switch.

The org-scoped router that finally makes ScaleCad multi-user: an org admin can
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

import html
import logging
import os
import re
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
    # Optional: the page in this organization the invite is for (a catalog run),
    # opened once the invite is accepted and named in the email.
    next: Optional[str] = None


# An in-app page an invite may open after it is accepted: a path, never a site.
_NEXT_PATH = re.compile(r"^/app/[A-Za-z0-9/_-]{1,200}$")


def _safe_next(path: Optional[str]) -> Optional[str]:
    p = (path or "").strip()
    return p if p and _NEXT_PATH.match(p) and "//" not in p else None


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


def _invite_link(raw_token: str, next_path: Optional[str] = None) -> str:
    from urllib.parse import quote

    link = f"{dashboard_origin()}/orgs/accept?token={raw_token}"
    return link + (f"&next={quote(next_path, safe='/')}" if next_path else "")


def _send_invite_email(email: str, link: str, org_name: Optional[str], *, inviter: Optional[str] = None,
                       role: Optional[str] = None, what: Optional[str] = None) -> bool:
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
        # Every value is escaped for HTML: names are user text.
        who = f" to {html.escape(org_name)}" if org_name else ""
        href = html.escape(link, quote=True)
        if inviter:
            # Who sent it, to which organization, as what, and what they want you to see.
            subject = f"{inviter} invited you to {org_name or 'their organization'} on ScaleCAD"
            lead = (f"<p>{html.escape(inviter)} invited you{who} on ScaleCAD"
                    + (f" as {html.escape(role)}" if role else "") + ".</p>")
            if what:
                lead += f"<p>{html.escape(what)}</p>"
            action = "Accept and open it" if what else "Accept the invitation"
        else:
            subject = "You've been invited to a ScaleCAD organization"
            lead = f"<p>You've been invited{who}.</p>"
            action = "Accept the invitation"
        resend.Emails.send(
            {
                "from": os.environ["RESEND_FROM"],
                "to": email,
                "subject": subject,
                "html": (
                    lead
                    + f'<p><a href="{href}">{action}</a> '
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


_ROLE_WORDS = {"viewer": "a viewer", "member": "a member", "admin": "an admin"}


async def _invite_words(session: AsyncSession, user_id: int, org_id: str,
                        next_path: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """``(inviter, organization, what it's for)`` in the words the email uses."""
    from sqlalchemy import select

    from src.db.models import Batch, Organization, User

    try:
        name, email = (await session.execute(select(User.full_name, User.email).where(User.id == user_id))).one()
        org_name = (await session.execute(select(Organization.name).where(Organization.id == org_id))).scalar_one_or_none()
    except Exception:
        return None, None, None
    inviter = f"{name} ({email})" if name else email
    what = None
    m = re.match(r"^/app/many/([0-9A-HJKMNP-TV-Z]{26})$", next_path or "")
    if m:
        batch = (await session.execute(select(Batch).where(Batch.ulid == m.group(1), Batch.org_id == org_id,
                                                           Batch.job_type == "catalog"))).scalars().first()
        if batch is not None:
            from src.services.catalog_run_service import run_title

            what = f"It's to look at a make-or-buy result: {run_title(batch) or 'a catalog run'}."
    return inviter, org_name, what


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
    inviter_role = ctx.org_role
    if inviter_role is None:
        raise HTTPException(
            status_code=403,
            detail="An active organization role is required to invite members",
        )
    invite, raw = await svc.create_invite(
        session, org_id, inviter_role, body.email, body.role, ctx.user_id
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
    next_path = _safe_next(body.next)
    link = _invite_link(raw, next_path)
    inviter, org_name, what = await _invite_words(session, ctx.user_id, org_id, next_path)
    emailed = _send_invite_email(invite.email, link, org_name, inviter=inviter,
                                 role=_ROLE_WORDS.get(invite.role, invite.role), what=what)
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


@router.post("/invites/preview")
@limiter.limit("60/hour;300/day")
async def preview_invite(
    request: Request,
    response: Response,
    body: AcceptBody,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Show what accepting an invite would do, without accepting it.

    The confirm step before ``/invites/accept``: the org, the role, who sent
    it, when it expires, and whether the caller is already a member. Same
    refusals as accept (400/404/409, and 403 for any other account, so a
    forwarded token reveals nothing). POST keeps the token out of URLs and
    access logs; nothing is written, so no kill-switch gate."""
    return await svc.preview_invite(session, user.user_id, body.token)


@router.post("/invites/summary")
@limiter.limit("30/minute;300/hour")
async def invite_summary(
    request: Request,
    response: Response,
    body: AcceptBody,
    session: AsyncSession = Depends(get_db_session),
):
    """What an invite link is for, before its holder signs in: the org, the
    role, the inviter's name (never a member's address), the invited address
    and when it expires. No sign-in: the link itself is the secret (256 random
    bits, stored only as a hash), emailed to the invited address. Pending
    invites only; a used, revoked, expired or unknown one gives no details.
    Read-only, so no kill-switch gate; POST keeps the token out of URLs."""
    response.headers["Cache-Control"] = "no-store"
    return await svc.invite_summary(session, body.token)


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


# ── the org's name ───────────────────────────────────────────────────────────
class RenameBody(BaseModel):
    name: str


@router.patch("/current", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;120/day")
async def rename_current_org(
    request: Request,
    response: Response,
    body: RenameBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Rename the caller's active org (org admins only). Invites, the header and
    the member list show the new name; the org keeps its id, slug and members."""
    org_id = await _ctx_org(ctx, session)
    org, previous = await svc.rename_org(session, org_id, body.name)
    if org.name != previous:
        await _emit(session, ctx.user_id, "org.renamed", org_id,
                    {"org_id": org_id, "from": previous, "to": org.name}, org_id=org_id)
    await session.commit()
    return {"org_id": org.id, "name": org.name, "slug": org.slug, "org_role": ctx.org_role}


# ── who may sign off a make-or-buy decision ──────────────────────────────────
class SignoffBody(BaseModel):
    # "member" (members and admins, the default) | "admin" (admins only); null
    # returns to the default.
    signoff_role: Optional[str] = None


async def _signoff_payload(session: AsyncSession, org_id: str, ctx: OrgAuthContext) -> dict:
    from src.services import signoff_service as so

    role = await so.get_role(session, org_id)
    return {
        "signoff_role": role,
        "label": so.ROLE_WORDS[role],
        "your_org_role": ctx.org_role,
        "can_sign_off": so.may_sign_off(ctx.org_role, role, is_superadmin=ctx.is_superadmin),
        "can_change": ctx.is_superadmin or ctx.org_role == "admin",
    }


@router.get("/signoff")
@limiter.limit("240/hour;2000/day")
async def get_signoff_setting(
    request: Request,
    response: Response,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Who may sign off a recorded make-or-buy decision in the caller's org."""
    org_id = await _ctx_org(ctx, session)
    return await _signoff_payload(session, org_id, ctx)


@router.put("/signoff", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;300/day")
async def set_signoff_setting(
    request: Request,
    response: Response,
    body: SignoffBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Set who may sign off decisions (org admins only). Existing sign-offs stay."""
    from src.services import signoff_service as so

    org_id = await _ctx_org(ctx, session)
    try:
        role = await so.set_role(session, org_id, body.signoff_role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _emit(session, ctx.user_id, "org.signoff_role_changed", org_id,
                {"org_id": org_id, "signoff_role": role}, org_id=org_id)
    await session.commit()
    return await _signoff_payload(session, org_id, ctx)


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
