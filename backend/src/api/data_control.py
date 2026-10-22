"""Data control: delete a part, an organization or your account, and list share links.

Routes (all org-scoped; another org's ids are the same 404 as unknown ones):

  GET    /api/v1/parts/{mesh_hash}/deletion-preview   what deleting would remove
  DELETE /api/v1/parts/{mesh_hash}                    delete the part (receipt)
  GET    /api/v1/orgs/current/deletion-preview        admin: what an org delete removes
  POST   /api/v1/orgs/current/delete                  admin: {"confirm_name": "<org name>"}
  GET    /api/v1/account/deletion-preview             what deleting your sign-in account does
  POST   /api/v1/account/delete                       {"confirm_email": "<your email>"}
  GET    /api/v1/data-deletions/{id}                  the receipt and file-removal progress
  GET    /api/v1/share-links?scope=mine|org           links with status; org = admins only

Roles (``src.auth.rbac``): deleting a part needs a platform analyst who is an
org member or admin. A member may delete a part only they checked or costed;
an admin may delete any part. Deleting the organization needs its admin (a
platform superadmin's org-role bypass does not count). Viewers read only.
Anyone may delete their own account, from a signed-in browser (not an API
key), unless they are the only admin of an organization others are in.

The database work commits in the request. Stored files are removed right after,
in this process, for up to a few seconds; anything left continues in the
background and the worker retries it (``run_data_deletion`` and the sweep).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, Role, require_org_role, require_org_writer, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import account_deletion_service as accounts
from src.services import data_deletion_service as svc
from src.services import share_links

logger = logging.getLogger("cadverify.data_control")

parts_router = APIRouter(tags=["parts"])
router = APIRouter(tags=["data-control"])

INLINE_SECONDS = 8.0
_background: set[asyncio.Task] = set()


async def _enqueue_retry(deletion_ulid: str) -> None:
    """Hand what's left to the worker (deferred a minute). The sweep is the backstop."""
    try:
        from src.jobs.arq_backend import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job(
            "run_data_deletion", deletion_ulid, _job_id=f"data-deletion:{deletion_ulid}", _defer_by=60
        )
    except Exception:  # noqa: BLE001 - the worker's sweep picks it up anyway
        logger.warning("could not enqueue file removal for %s", deletion_ulid, exc_info=True)


async def _remove_files(deletion_ulid: str) -> None:
    """Remove stored files now; whatever doesn't finish goes on in the background."""
    task = asyncio.create_task(svc.process(deletion_ulid, force=True))
    _background.add(task)
    task.add_done_callback(_background.discard)
    done, _ = await asyncio.wait({task}, timeout=INLINE_SECONDS)
    if done:
        exc = task.exception()
        if exc is None and (task.result() is None or task.result().status != "removing_files"):
            return
        if exc is not None:
            logger.warning("inline file removal for %s raised: %r", deletion_ulid, exc)
    await _enqueue_retry(deletion_ulid)


async def _fresh_receipt(session: AsyncSession, deletion_ulid: str) -> dict:
    from sqlalchemy import select

    from src.db.models import DataDeletion

    session.expire_all()
    row = (await session.execute(select(DataDeletion).where(DataDeletion.ulid == deletion_ulid))).scalar_one()
    return svc.serialize_receipt(row)


@parts_router.get("/{mesh_hash}/deletion-preview")
@limiter.limit("300/hour;3000/day")
async def part_deletion_preview(
    request: Request,
    response: Response,
    mesh_hash: str,
    keep_fixed_copies: bool = Query(False),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """What deleting this part removes, whether the caller may, and what stays."""
    response.headers["Cache-Control"] = "no-store"
    return await svc.part_deletion_preview(
        session, ctx.org_id or "", mesh_hash, ctx.user_id, ctx.org_role,
        include_copies=not keep_fixed_copies,
    )


@parts_router.delete("/{mesh_hash}")
@limiter.limit("120/hour;1000/day")
async def delete_part(
    request: Request,
    response: Response,
    mesh_hash: str,
    keep_fixed_copies: bool = Query(False),
    # Analyst and org member: a viewer is refused with the plain viewer line.
    user: AuthedUser = Depends(require_org_writer),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    session: AsyncSession = Depends(get_db_session),
):
    """Delete the part (its stored file, checks, records, context, links) now.

    Repeating it returns the same receipt. ``keep_fixed_copies=true`` keeps
    the copies ScaleCAD fixed from it (they lose the original's file name).
    """
    receipt = await svc.delete_part(
        session,
        org_id=ctx.org_id or "",
        mesh_hash=mesh_hash,
        user_id=ctx.user_id,
        org_role=ctx.org_role,
        include_copies=not keep_fixed_copies,
    )
    if receipt.status == "removing_files":
        await _remove_files(receipt.ulid)
    response.headers["Cache-Control"] = "no-store"
    return await _fresh_receipt(session, receipt.ulid)


def _org_admin(ctx: OrgAuthContext) -> str:
    if ctx.org_role != "admin" or not ctx.org_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_org_role", "message": "Only an admin of this organization can do this."},
        )
    return ctx.org_id


class OrgDeleteBody(BaseModel):
    confirm_name: str = Field(..., min_length=1, max_length=300)


@router.get("/orgs/current/deletion-preview")
@limiter.limit("120/hour;1000/day")
async def org_deletion_preview(
    request: Request,
    response: Response,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = _org_admin(ctx)
    response.headers["Cache-Control"] = "no-store"
    return await svc.org_deletion_preview(session, org_id)


@router.post("/orgs/current/delete")
@limiter.limit("10/hour;20/day")
async def delete_current_org(
    request: Request,
    response: Response,
    body: OrgDeleteBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Delete the caller's active organization and all of its data.

    Members are signed out; anyone left without an organization gets a new
    empty one. Accounts and billing records stay.
    """
    org_id = _org_admin(ctx)
    if user.org_id is not None and user.org_id != org_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    receipt = await svc.delete_organization(
        session, org_id=org_id, user_id=ctx.user_id, confirm_name=body.confirm_name
    )
    await _remove_files(receipt.ulid)
    response.headers["Cache-Control"] = "no-store"
    return await _fresh_receipt(session, receipt.ulid)


def _browser_session(user: AuthedUser) -> None:
    # Deleting an account belongs to the signed-in person, never to an API key.
    if user.key_prefix != "session":
        raise HTTPException(
            status_code=403,
            detail={"code": "browser_session_required",
                    "message": "Delete your account from the ScaleCAD web app, signed in."},
        )


class AccountDeleteBody(BaseModel):
    confirm_email: str = Field(..., min_length=1, max_length=320)


@router.get("/account/deletion-preview")
@limiter.limit("120/hour;600/day")
async def account_deletion_preview(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """What deleting the caller's account removes, what blocks it, and what stays."""
    _browser_session(user)
    response.headers["Cache-Control"] = "no-store"
    return await accounts.account_deletion_preview(session, user.user_id)


@router.post("/account/delete")
@limiter.limit("5/hour;10/day")
async def delete_account(
    request: Request,
    response: Response,
    body: AccountDeleteBody,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Delete the caller's sign-in account. Every session and key stops working.

    409 ``account_delete_blocked`` while they are the only admin of an
    organization others are in; 503 ``billing_cancel_failed`` (nothing deleted)
    when a live Pro plan couldn't be cancelled at Stripe.
    """
    _browser_session(user)
    receipt = await accounts.delete_account(session, user_id=user.user_id, confirm_email=body.confirm_email)
    await _remove_files(receipt.ulid)
    response.headers["Cache-Control"] = "no-store"
    return await _fresh_receipt(session, receipt.ulid)


@router.get("/data-deletions/{deletion_id}")
@limiter.limit("600/hour;5000/day")
async def get_deletion(
    request: Request,
    response: Response,
    deletion_id: str,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    row = await svc.get_receipt(session, deletion_id, user.user_id)
    response.headers["Cache-Control"] = "no-store"
    return svc.serialize_receipt(row)


@router.get("/share-links")
@limiter.limit("600/hour;5000/day")
async def list_share_links(
    request: Request,
    response: Response,
    scope: Literal["mine", "org"] = Query("mine"),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Share links in the caller's organization: their own, or (admins) everyone's."""
    if not ctx.org_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    is_admin = ctx.org_role == "admin"
    if scope == "org" and not is_admin:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_org_role", "message": "Only an admin sees everyone's links."},
        )
    links = await share_links.list_links(session, ctx.org_id, ctx.user_id, everyone=scope == "org")
    response.headers["Cache-Control"] = "no-store"
    return {
        "scope": scope,
        "is_admin": is_admin,
        "default_days": share_links.DEFAULT_DAYS,
        # What the Share dialog offers: these days, or a date up to a year ahead.
        "choices": list(share_links.DIALOG_CHOICES),
        "max_days": share_links.MAX_DAYS_AHEAD,
        "links": links,
    }
