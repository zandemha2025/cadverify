"""SCIM 2.0 provisioning routes.

Mounted at /scim/v2 for Okta/Entra-style provisioning, and only on deployments
that use single sign-on (AUTH_MODE saml, oidc or hybrid) or that set
``SCIM_ENABLED=1``; see :func:`mount_scim`. Authentication uses the existing
Bearer API-key path, authorization requires org admin, and the key's org must
be a shared organization: a personal org never uses SCIM.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rbac import OrgAuthContext, OrgRole, require_org_role
from src.db.engine import get_db_session
from src.services import scim_service as svc

logger = logging.getLogger("cadverify.scim")

router = APIRouter(prefix="/scim/v2", tags=["scim"])
require_scim_admin = require_org_role(OrgRole.admin)

# Deployments whose sign-in goes through an enterprise identity provider.
_SSO_AUTH_MODES = frozenset({"saml", "oidc", "hybrid"})
_FLAG_ON = frozenset({"1", "true", "yes", "on"})
_FLAG_OFF = frozenset({"0", "false", "no", "off"})


def scim_routes_enabled() -> bool:
    """SCIM is served only where single sign-on is in use, or when forced on.

    ``SCIM_ENABLED=1`` mounts it on any deployment and ``SCIM_ENABLED=0`` keeps
    it off; unset, it follows AUTH_MODE (default ``google``, so off).
    """
    flag = (os.getenv("SCIM_ENABLED") or "").strip().lower()
    if flag in _FLAG_ON:
        return True
    if flag in _FLAG_OFF:
        return False
    mode = (os.getenv("AUTH_MODE") or "google").strip().lower()
    return mode in _SSO_AUTH_MODES


def mount_scim(app: FastAPI) -> bool:
    """Include the SCIM router when :func:`scim_routes_enabled`; log either way."""
    mode = os.getenv("AUTH_MODE") or "google"
    flag = os.getenv("SCIM_ENABLED") or "unset"
    if scim_routes_enabled():
        app.include_router(router)
        logger.info(
            "SCIM provisioning mounted at /scim/v2 (AUTH_MODE=%s, SCIM_ENABLED=%s)",
            mode,
            flag,
        )
        return True
    logger.info(
        "SCIM provisioning not mounted (AUTH_MODE=%s, SCIM_ENABLED=%s): it needs "
        "AUTH_MODE saml, oidc or hybrid, or SCIM_ENABLED=1",
        mode,
        flag,
    )
    return False


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _scim_org_required(message: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": "scim_org_required", "message": message},
    )


async def _org_id(ctx: OrgAuthContext, session: AsyncSession) -> str:
    """The org this SCIM call provisions: the admin key's own shared org."""
    if not ctx.org_id:
        raise _scim_org_required(
            "SCIM provisioning requires an org-scoped admin API key."
        )
    if await svc.org_is_personal(session, ctx.org_id):
        raise _scim_org_required(
            "SCIM provisioning works only for a shared organization, not a "
            "personal one. Create an organization for your team and use an "
            "admin API key issued in it."
        )
    return ctx.org_id


@router.get("/ServiceProviderConfig")
async def service_provider_config(
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    await _org_id(ctx, session)
    return svc.service_provider_config()


@router.get("/Schemas")
async def schemas(
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    await _org_id(ctx, session)
    return svc.schemas()


@router.get("/ResourceTypes")
async def resource_types(
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    await _org_id(ctx, session)
    return svc.resource_types()


@router.get("/Users")
async def list_users(
    request: Request,
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1, le=100),
    filter: str | None = Query(None),  # noqa: A002 - SCIM parameter name.
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    return await svc.list_users(
        session,
        org_id=org_id,
        start_index=startIndex,
        count=count,
        filter_value=filter,
        base_url=_base_url(request),
    )


@router.post("/Users", status_code=201)
async def create_user(
    request: Request,
    payload: dict[str, Any],
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    user = await svc.create_or_update_user(
        session,
        org_id=org_id,
        payload=payload,
        base_url=_base_url(request),
    )
    await session.commit()
    return user


@router.get("/Users/{user_id}")
async def get_user(
    user_id: str,
    request: Request,
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    return await svc.get_user(
        session, org_id=org_id, user_id=user_id, base_url=_base_url(request)
    )


@router.put("/Users/{user_id}")
async def replace_user(
    user_id: str,
    request: Request,
    payload: dict[str, Any],
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    existing = await svc.get_user(
        session, org_id=org_id, user_id=user_id, base_url=_base_url(request)
    )
    payload.setdefault("userName", existing["userName"])
    user = await svc.create_or_update_user(
        session,
        org_id=org_id,
        payload=payload,
        base_url=_base_url(request),
    )
    await session.commit()
    return user


@router.patch("/Users/{user_id}")
async def patch_user(
    user_id: str,
    request: Request,
    payload: dict[str, Any],
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    if payload.get("schemas") and svc.PATCH_SCHEMA not in payload.get("schemas", []):
        raise HTTPException(status_code=400, detail="SCIM PATCH schema is required.")
    user = await svc.patch_user(
        session,
        org_id=org_id,
        user_id=user_id,
        payload=payload,
        base_url=_base_url(request),
    )
    await session.commit()
    return user


@router.delete("/Users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    request: Request,
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    await svc.patch_user(
        session,
        org_id=org_id,
        user_id=user_id,
        payload={"Operations": [{"op": "replace", "path": "active", "value": False}]},
        base_url=_base_url(request),
    )
    await session.commit()
    return Response(status_code=204)


@router.get("/Groups")
async def list_groups(
    request: Request,
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    return await svc.list_groups(session, org_id=org_id, base_url=_base_url(request))


@router.get("/Groups/{group_id:path}")
async def get_group(
    group_id: str,
    request: Request,
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    return await svc.get_group(
        session, org_id=org_id, group_id=group_id, base_url=_base_url(request)
    )


@router.patch("/Groups/{group_id:path}")
async def patch_group(
    group_id: str,
    request: Request,
    payload: dict[str, Any],
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org_id(ctx, session)
    group = await svc.patch_group(
        session,
        org_id=org_id,
        group_id=group_id,
        payload=payload,
        base_url=_base_url(request),
    )
    await session.commit()
    return group
