"""SCIM 2.0 provisioning routes.

Mounted at /scim/v2 for Okta/Entra-style provisioning. Authentication uses the
existing Bearer API-key path, and authorization requires org admin.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rbac import OrgAuthContext, OrgRole, require_org_role
from src.db.engine import get_db_session
from src.services import scim_service as svc

router = APIRouter(prefix="/scim/v2", tags=["scim"])
require_scim_admin = require_org_role(OrgRole.admin)


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _org_id(ctx: OrgAuthContext) -> str:
    if not ctx.org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "scim_org_required",
                "message": "SCIM provisioning requires an org-scoped admin API key.",
            },
        )
    return ctx.org_id


@router.get("/ServiceProviderConfig")
async def service_provider_config(
    ctx: OrgAuthContext = Depends(require_scim_admin),
):
    _org_id(ctx)
    return svc.service_provider_config()


@router.get("/Schemas")
async def schemas(ctx: OrgAuthContext = Depends(require_scim_admin)):
    _org_id(ctx)
    return svc.schemas()


@router.get("/ResourceTypes")
async def resource_types(ctx: OrgAuthContext = Depends(require_scim_admin)):
    _org_id(ctx)
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
    return await svc.list_users(
        session,
        org_id=_org_id(ctx),
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
    user = await svc.create_or_update_user(
        session,
        org_id=_org_id(ctx),
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
    return await svc.get_user(
        session, org_id=_org_id(ctx), user_id=user_id, base_url=_base_url(request)
    )


@router.put("/Users/{user_id}")
async def replace_user(
    user_id: str,
    request: Request,
    payload: dict[str, Any],
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    existing = await svc.get_user(
        session, org_id=_org_id(ctx), user_id=user_id, base_url=_base_url(request)
    )
    payload.setdefault("userName", existing["userName"])
    user = await svc.create_or_update_user(
        session,
        org_id=_org_id(ctx),
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
    if payload.get("schemas") and svc.PATCH_SCHEMA not in payload.get("schemas", []):
        raise HTTPException(status_code=400, detail="SCIM PATCH schema is required.")
    user = await svc.patch_user(
        session,
        org_id=_org_id(ctx),
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
    await svc.patch_user(
        session,
        org_id=_org_id(ctx),
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
    return await svc.list_groups(session, org_id=_org_id(ctx), base_url=_base_url(request))


@router.get("/Groups/{group_id:path}")
async def get_group(
    group_id: str,
    request: Request,
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    return await svc.get_group(
        session, org_id=_org_id(ctx), group_id=group_id, base_url=_base_url(request)
    )


@router.patch("/Groups/{group_id:path}")
async def patch_group(
    group_id: str,
    request: Request,
    payload: dict[str, Any],
    ctx: OrgAuthContext = Depends(require_scim_admin),
    session: AsyncSession = Depends(get_db_session),
):
    group = await svc.patch_group(
        session,
        org_id=_org_id(ctx),
        group_id=group_id,
        payload=payload,
        base_url=_base_url(request),
    )
    await session.commit()
    return group
