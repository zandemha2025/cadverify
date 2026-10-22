"""Two-step sign-in routes, under /auth (this router rides ``password.router``).

Sign-in (no session yet; the Next.js server holds the challenge in an httpOnly
cookie and posts it here):
  POST /auth/two-step/challenge/state          what the challenge asks for
  POST /auth/two-step/challenge/verify         code or recovery code -> session
  POST /auth/two-step/challenge/setup          org requires it: new secret + QR
  POST /auth/two-step/challenge/setup/confirm  first code -> session + recovery codes

Account › Security (dashboard session):
  GET  /auth/two-step                status
  POST /auth/two-step/enrol          new secret + QR (pending until confirmed)
  POST /auth/two-step/enrol/confirm  first code -> on; other browsers signed out
  POST /auth/two-step/disable        current code or recovery code
  POST /auth/two-step/recovery-codes current code -> ten new codes
  POST /auth/sessions/sign-out-others
  POST /auth/two-step/step-up        joined an org that requires it: session -> setup challenge

Organization rule (dashboard session, org admin to change):
  GET  /auth/two-step/org            the rule, and (admins) who has it on
  PUT  /auth/two-step/org            {"required": bool}

Responses that carry a session are read by the Next.js server, which sets the
first-party cookie and never passes the token to browser JavaScript.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import two_step as ts
from src.auth.client_ip import client_ip, client_user_agent, require_auth_proxy_if_enabled
from src.auth.dashboard_session import require_dashboard_session, sign
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, require_org_role
from src.config.public_urls import error_doc_url
from src.db.engine import get_db_session

router = APIRouter(tags=["auth"])
logger = logging.getLogger("cadverify.auth.two_step")


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message, "doc_url": error_doc_url(code)})


class ChallengeIn(BaseModel):
    challenge: str = Field(min_length=16, max_length=1024)


class ProveIn(BaseModel):
    code: Optional[str] = Field(default=None, max_length=32)
    recovery_code: Optional[str] = Field(default=None, max_length=64)


class ChallengeProveIn(ChallengeIn, ProveIn):
    pass


class CodeIn(BaseModel):
    code: str = Field(max_length=32)


class ChallengeCodeIn(ChallengeIn):
    code: str = Field(max_length=32)


class PolicyIn(BaseModel):
    required: bool


async def _user(session: AsyncSession, user_id: int) -> tuple[str, str, bool, int]:
    row = (
        await session.execute(
            text("SELECT email, role, is_active, session_version FROM users WHERE id = :u"),
            {"u": int(user_id)},
        )
    ).first()
    if row is None:
        raise _err(401, "two_step_challenge_invalid", "This sign-in expired. Sign in again.")
    return str(row[0]), str(row[1] or "analyst"), bool(row[2]), int(row[3] or 0)


async def _open_challenge(session: AsyncSession, token: str, purpose: str | None = None) -> tuple[ts.Challenge, str, str]:
    """The challenge, still valid for this account as it is now."""
    ch = ts.read_challenge(token)
    if ch is None:
        raise _err(401, "two_step_challenge_invalid", "This sign-in expired after 10 minutes. Sign in again.")
    email, role, active, version = await _user(session, ch.user_id)
    if not active:
        raise _err(403, "account_deactivated", "This account has been deactivated.")
    if version != ch.session_version:
        raise _err(401, "two_step_challenge_invalid", "This sign-in is no longer valid. Sign in again.")
    if purpose is not None and ch.purpose != purpose:
        raise _err(409, "two_step_challenge_purpose", "This sign-in asks for something else. Reload the page.")
    return ch, email, role


async def _bump_version(session: AsyncSession, user_id: int) -> int:
    return int(
        (
            await session.execute(
                text("UPDATE users SET session_version = session_version + 1 WHERE id = :u RETURNING session_version"),
                {"u": int(user_id)},
            )
        ).scalar_one()
    )


async def _audit(session: AsyncSession, request: Request | None, user_id: int, action: str, detail: dict | None = None, *, email: str | None = None, resource_type: str = "user", resource_id: str | None = None, org_id: str | None = None) -> None:
    from src.services.audit_service import append_audit_entry

    await append_audit_entry(
        session,
        int(user_id),
        action,
        resource_type,
        resource_id if resource_id is not None else str(user_id),
        detail,
        user_email=email,
        org_id=org_id,
        ip_address=client_ip(request) if request is not None else None,
        user_agent=client_user_agent(request),
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


# ── sign-in ───────────────────────────────────────────────────────────────────
@router.post("/two-step/challenge/state")
@limiter.limit("60/minute")
async def challenge_state(body: ChallengeIn, request: Request, response: Response, session: AsyncSession = Depends(get_db_session)) -> dict:
    require_auth_proxy_if_enabled(request)
    _no_store(response)
    ch, email, _role = await _open_challenge(session, body.challenge)
    left = await ts.recovery_codes_left(session, ch.user_id) if ch.purpose == "verify" else 0
    return {
        "purpose": ch.purpose,
        "method": ch.method,
        "email": email,
        "required_by": [o["name"] for o in await ts.requiring_orgs(session, ch.user_id)],
        "recovery_codes_left": left,
        "expires_in_seconds": max(0, ts.CHALLENGE_TTL - int(time.time() - ch.issued_at)),
    }


@router.post("/two-step/challenge/verify")
@limiter.limit("20/minute;200/day")
async def challenge_verify(body: ChallengeProveIn, request: Request, response: Response, session: AsyncSession = Depends(get_db_session)) -> dict:
    require_auth_proxy_if_enabled(request)
    _no_store(response)
    ch, email, role = await _open_challenge(session, body.challenge, "verify")
    used = await ts.prove(session, ch.user_id, code=body.code, recovery_code=body.recovery_code)
    left = await ts.recovery_codes_left(session, ch.user_id)
    if used == "recovery":
        await _audit(session, request, ch.user_id, "auth.two_step_recovery_used", {"recovery_codes_left": left, "during": "sign_in"}, email=email)
    await _audit(session, request, ch.user_id, "auth.login", {"auth_provider": ch.method, "two_step": used}, email=email, resource_type="session", resource_id=None)
    await session.commit()
    return {
        "user": {"id": ch.user_id, "email": email, "role": role},
        "session": sign(ch.user_id, session_version=ch.session_version),
        "used": used,
        "recovery_codes_left": left,
    }


@router.post("/two-step/challenge/setup")
@limiter.limit("20/minute")
async def challenge_setup(body: ChallengeIn, request: Request, response: Response, session: AsyncSession = Depends(get_db_session)) -> dict:
    require_auth_proxy_if_enabled(request)
    _no_store(response)
    ch, email, _role = await _open_challenge(session, body.challenge, "setup")
    data = await ts.begin_enrolment(session, ch.user_id, email)
    await session.commit()
    return data


@router.post("/two-step/challenge/setup/confirm")
@limiter.limit("20/minute;200/day")
async def challenge_setup_confirm(body: ChallengeCodeIn, request: Request, response: Response, session: AsyncSession = Depends(get_db_session)) -> dict:
    require_auth_proxy_if_enabled(request)
    _no_store(response)
    ch, email, role = await _open_challenge(session, body.challenge, "setup")
    codes = await ts.confirm_enrolment(session, ch.user_id, body.code)
    version = await _bump_version(session, ch.user_id)
    orgs = [o["name"] for o in await ts.requiring_orgs(session, ch.user_id)]
    await _audit(session, request, ch.user_id, "auth.two_step_enabled", {"during": "sign_in", "required_by": orgs}, email=email)
    await _audit(session, request, ch.user_id, "auth.login", {"auth_provider": ch.method, "two_step": "setup"}, email=email, resource_type="session", resource_id=None)
    await session.commit()
    return {
        "user": {"id": ch.user_id, "email": email, "role": role},
        "session": sign(ch.user_id, session_version=version),
        "recovery_codes": codes,
    }


# ── Account › Security ────────────────────────────────────────────────────────
@router.get("/two-step")
async def get_status(response: Response, user_id: int = Depends(require_dashboard_session), session: AsyncSession = Depends(get_db_session)) -> dict:
    _no_store(response)
    return await ts.status(session, user_id)


@router.post("/two-step/enrol")
@limiter.limit("20/minute")
async def enrol(request: Request, response: Response, user_id: int = Depends(require_dashboard_session), session: AsyncSession = Depends(get_db_session)) -> dict:
    _no_store(response)
    email, _role, _active, _version = await _user(session, user_id)
    data = await ts.begin_enrolment(session, user_id, email)
    await session.commit()
    return data


@router.post("/two-step/enrol/confirm")
@limiter.limit("20/minute;200/day")
async def enrol_confirm(body: CodeIn, request: Request, response: Response, user_id: int = Depends(require_dashboard_session), session: AsyncSession = Depends(get_db_session)) -> dict:
    _no_store(response)
    email, _role, _active, _version = await _user(session, user_id)
    codes = await ts.confirm_enrolment(session, user_id, body.code)
    version = await _bump_version(session, user_id)
    await _audit(session, request, user_id, "auth.two_step_enabled", {"during": "account"}, email=email)
    await session.commit()
    return {"session": sign(user_id, session_version=version), "recovery_codes": codes, "status": await ts.status(session, user_id)}


@router.post("/two-step/disable")
@limiter.limit("20/minute;200/day")
async def disable(body: ProveIn, request: Request, response: Response, user_id: int = Depends(require_dashboard_session), session: AsyncSession = Depends(get_db_session)) -> dict:
    _no_store(response)
    email, _role, _active, _version = await _user(session, user_id)
    orgs = await ts.requiring_orgs(session, user_id)
    if orgs:
        await ts.disable(session, user_id)  # raises the plain refusal naming the org
    used = await ts.prove(session, user_id, code=body.code, recovery_code=body.recovery_code)
    await ts.disable(session, user_id)
    await _audit(session, request, user_id, "auth.two_step_disabled", {"proved_with": used}, email=email)
    await session.commit()
    return await ts.status(session, user_id)


@router.post("/two-step/recovery-codes")
@limiter.limit("20/minute;200/day")
async def new_recovery_codes(body: ProveIn, request: Request, response: Response, user_id: int = Depends(require_dashboard_session), session: AsyncSession = Depends(get_db_session)) -> dict:
    _no_store(response)
    email, _role, _active, _version = await _user(session, user_id)
    used = await ts.prove(session, user_id, code=body.code, recovery_code=body.recovery_code)
    codes = await ts.replace_recovery_codes(session, user_id)
    await _audit(session, request, user_id, "auth.two_step_recovery_codes_replaced", {"proved_with": used}, email=email)
    await session.commit()
    return {"recovery_codes": codes, "status": await ts.status(session, user_id)}


@router.post("/two-step/step-up")
@limiter.limit("30/minute")
async def step_up(request: Request, response: Response, user_id: int = Depends(require_dashboard_session), session: AsyncSession = Depends(get_db_session)) -> dict:
    """A session that now owes two-step setup becomes a setup challenge.

    Joining an organization that requires two-step (sign-up from an invite, or
    accepting one while signed in) happens inside a session made before the
    rule applied to this person. When the account has no two-step yet, every
    one of its sessions ends here and a setup challenge is returned, so the
    organization's data is reached only after setting it up. An account that
    already has two-step (or owes nothing) keeps its session: it signed in with
    a code, or through single sign-on, which is exempt.
    """
    require_auth_proxy_if_enabled(request)
    _no_store(response)
    if await ts.sign_in_requirement(session, user_id) != "setup":
        return {"two_step": None}
    version = await _bump_version(session, user_id)
    email, _role, _active, _v = await _user(session, user_id)
    await _audit(session, request, user_id, "user.sessions_revoked", {"revoked_by": user_id, "scope": "two_step_setup_required"}, email=email)
    await session.commit()
    return {"two_step": "setup", "challenge": ts.make_challenge(user_id, version, "setup", "password")}


@router.post("/sessions/sign-out-others")
@limiter.limit("30/hour")
async def sign_out_others(request: Request, response: Response, user_id: int = Depends(require_dashboard_session), session: AsyncSession = Depends(get_db_session)) -> dict:
    """End every other browser's session; this one gets a fresh session.

    Sessions are signed cookies carrying the account's session version, with
    no server-side row per browser, so there is no device list to show:
    raising the version ends them all at once, and this browser is re-issued.
    """
    _no_store(response)
    email, _role, _active, _version = await _user(session, user_id)
    version = await _bump_version(session, user_id)
    await _audit(session, request, user_id, "user.sessions_revoked", {"revoked_by": user_id, "scope": "others"}, email=email)
    await session.commit()
    return {"ok": True, "session": sign(user_id, session_version=version)}


# ── organization rule ─────────────────────────────────────────────────────────
@router.get("/two-step/org")
async def get_org_rule(response: Response, ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)), session: AsyncSession = Depends(get_db_session)) -> dict:
    _no_store(response)
    org_id = ctx.org_id
    if not org_id:
        raise _err(403, "insufficient_org_role", "No organization for this account.")
    org = (await session.execute(text("SELECT name, is_personal, require_two_step FROM organizations WHERE id = :o"), {"o": org_id})).first()
    is_admin = ctx.is_superadmin or ctx.org_role == "admin"
    out = {
        "org_id": org_id,
        "org_name": org[0] if org else None,
        "is_personal": bool(org[1]) if org else False,
        "required": bool(org[2]) if org else False,
        "can_change": is_admin and ctx.api_key_id == 0,
    }
    if is_admin:
        out["members"] = await ts.member_status(session, org_id)
    return out


@router.put("/two-step/org")
@limiter.limit("30/hour")
async def set_org_rule(body: PolicyIn, request: Request, response: Response, ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)), session: AsyncSession = Depends(get_db_session)) -> dict:
    _no_store(response)
    if ctx.api_key_id != 0:
        raise _err(403, "two_step_rule_needs_session", "Change sign-in rules in the app, not with an API key.")
    org_id = ctx.org_id
    if not org_id:
        raise _err(403, "insufficient_org_role", "No organization for this account.")
    before = await ts.org_policy(session, org_id)
    result = await ts.set_org_policy(session, org_id, ctx.user_id, body.required)
    if before != body.required:
        await _audit(
            session, request, ctx.user_id, "org.two_step_policy_changed",
            {"required": body.required, "members_signed_out": len(result["signed_out_user_ids"])},
            resource_type="org", resource_id=org_id, org_id=org_id,
        )
    await session.commit()
    response_body = await get_org_rule(response, ctx, session)
    response_body["members_signed_out"] = len(result["signed_out_user_ids"])
    return response_body
