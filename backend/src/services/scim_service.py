"""SCIM 2.0 user and role-group lifecycle service.

This is the first real enterprise identity provisioning surface. It deliberately
uses the platform's existing bearer API-key auth at the router boundary, then
applies all writes to the caller's org membership table so deprovisioning removes
tenant access on the next request.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.disposable import normalize_email
from src.db.models import Membership, ScimIdentity, User
from src.services.org_service import VALID_ORG_ROLES

CORE_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
CORE_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

ROLE_GROUP_IDS = {
    "admin": "role:admin",
    "member": "role:member",
    "viewer": "role:viewer",
}
ROLE_BY_GROUP_ID = {value: key for key, value in ROLE_GROUP_IDS.items()}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scim_error(status: int, detail: str, scim_type: str | None = None) -> HTTPException:
    body: dict[str, Any] = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": str(status),
        "detail": detail,
    }
    if scim_type:
        body["scimType"] = scim_type
    return HTTPException(status_code=status, detail=body)


def _clean_role(value: Any, default: str = "viewer") -> str:
    role = str(value or default).strip().lower()
    if role not in VALID_ORG_ROLES:
        raise _scim_error(400, f"Unsupported org role '{value}'.", "invalidValue")
    return role


def _primary_email(payload: dict[str, Any]) -> str:
    user_name = str(payload.get("userName") or "").strip()
    if user_name:
        return user_name
    for item in payload.get("emails") or []:
        if isinstance(item, dict) and item.get("value"):
            return str(item["value"]).strip()
    raise _scim_error(400, "SCIM userName or email value is required.", "invalidValue")


def _role_from_payload(payload: dict[str, Any], default: str = "viewer") -> str:
    cadverify = payload.get("urn:cadverify:params:scim:schemas:extension:2.0:User")
    if isinstance(cadverify, dict) and cadverify.get("orgRole"):
        return _clean_role(cadverify.get("orgRole"), default)
    roles = payload.get("roles") or []
    for item in roles:
        if isinstance(item, dict) and item.get("value"):
            candidate = str(item["value"]).strip().lower()
        else:
            candidate = str(item).strip().lower()
        if candidate in VALID_ORG_ROLES:
            return candidate
    return default


def service_provider_config() -> dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 100},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer API key",
                "description": "Use an org-admin CadVerify API key as the SCIM bearer token.",
                "primary": True,
            }
        ],
    }


def schemas() -> dict[str, Any]:
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": 2,
        "startIndex": 1,
        "itemsPerPage": 2,
        "Resources": [
            {
                "id": CORE_USER_SCHEMA,
                "name": "User",
                "description": "SCIM core user schema.",
            },
            {
                "id": CORE_GROUP_SCHEMA,
                "name": "Group",
                "description": "SCIM core group schema.",
            },
        ],
    }


def resource_types() -> dict[str, Any]:
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": 2,
        "startIndex": 1,
        "itemsPerPage": 2,
        "Resources": [
            {
                "id": "User",
                "name": "User",
                "endpoint": "/Users",
                "schema": CORE_USER_SCHEMA,
            },
            {
                "id": "Group",
                "name": "Group",
                "endpoint": "/Groups",
                "schema": CORE_GROUP_SCHEMA,
            },
        ],
    }


async def _membership(
    session: AsyncSession, org_id: str, user_id: int
) -> Membership | None:
    return (
        await session.execute(
            select(Membership).where(
                Membership.org_id == org_id,
                Membership.user_id == user_id,
            )
        )
    ).scalars().first()


async def _identity(
    session: AsyncSession, org_id: str, user_id: int
) -> ScimIdentity | None:
    return (
        await session.execute(
            select(ScimIdentity).where(
                ScimIdentity.org_id == org_id,
                ScimIdentity.user_id == user_id,
            )
        )
    ).scalars().first()


async def _user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return (
        await session.execute(select(User).where(User.id == user_id))
    ).scalars().first()


async def _user_by_email(session: AsyncSession, email: str) -> User | None:
    return (
        await session.execute(
            select(User).where(User.email_lower == normalize_email(email))
        )
    ).scalars().first()


async def _admin_count(session: AsyncSession, org_id: str) -> int:
    from sqlalchemy import func

    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Membership)
                .where(Membership.org_id == org_id, Membership.org_role == "admin")
            )
        ).scalar_one()
        or 0
    )


async def _ensure_membership(
    session: AsyncSession, *, org_id: str, user: User, role: str
) -> Membership:
    role = _clean_role(role)
    membership = await _membership(session, org_id, int(user.id))
    if membership is None:
        membership = Membership(
            id=str(ULID()),
            org_id=org_id,
            user_id=int(user.id),
            org_role=role,
        )
        session.add(membership)
    else:
        if membership.org_role == "admin" and role != "admin":
            if await _admin_count(session, org_id) <= 1:
                raise _scim_error(
                    409,
                    "Cannot demote the last admin via SCIM.",
                    "mutability",
                )
        membership.org_role = role
    user.current_org_id = org_id
    await session.flush()
    return membership


async def _ensure_identity(
    session: AsyncSession,
    *,
    org_id: str,
    user: User,
    role: str,
    active: bool,
    external_id: str | None = None,
) -> ScimIdentity:
    identity = await _identity(session, org_id, int(user.id))
    role = _clean_role(role)
    if identity is None:
        identity = ScimIdentity(
            org_id=org_id,
            user_id=int(user.id),
            external_id=external_id,
            active=active,
            org_role=role,
        )
        session.add(identity)
    else:
        if external_id:
            identity.external_id = external_id
        identity.active = active
        identity.org_role = role
        identity.updated_at = _now()
    await session.flush()
    return identity


async def _deprovision_membership(
    session: AsyncSession, *, org_id: str, user: User
) -> None:
    membership = await _membership(session, org_id, int(user.id))
    if membership is None:
        return
    if membership.org_role == "admin" and await _admin_count(session, org_id) <= 1:
        raise _scim_error(409, "Cannot remove the last admin via SCIM.", "mutability")
    await session.delete(membership)
    if user.current_org_id == org_id:
        user.current_org_id = None
    user.session_version = int(user.session_version or 0) + 1
    await session.flush()


def serialize_user(
    user: User,
    membership: Membership | None,
    identity: ScimIdentity | None = None,
    *,
    base_url: str = "",
) -> dict[str, Any]:
    active = (
        bool(getattr(user, "is_active", True))
        and bool(getattr(identity, "active", membership is not None))
        and membership is not None
    )
    role = (
        identity.org_role
        if identity is not None
        else membership.org_role if membership is not None else None
    )
    org_id = (
        identity.org_id
        if identity is not None
        else membership.org_id if membership is not None else None
    )
    return {
        "schemas": [CORE_USER_SCHEMA],
        "id": str(user.id),
        "externalId": identity.external_id if identity is not None else None,
        "userName": user.email,
        "name": {"formatted": user.email},
        "emails": [{"value": user.email, "primary": True}],
        "active": active,
        "roles": [{"value": role, "primary": True}] if role else [],
        "urn:cadverify:params:scim:schemas:extension:2.0:User": {
            "orgRole": role,
            "orgId": org_id,
        },
        "meta": {
            "resourceType": "User",
            "location": f"{base_url.rstrip('/')}/scim/v2/Users/{user.id}" if base_url else None,
            "created": user.created_at.isoformat() if user.created_at else None,
        },
    }


def serialize_group(
    role: str, members: list[tuple[int, str]], *, base_url: str = ""
) -> dict[str, Any]:
    group_id = ROLE_GROUP_IDS[role]
    return {
        "schemas": [CORE_GROUP_SCHEMA],
        "id": group_id,
        "displayName": f"CadVerify {role}",
        "members": [
            {
                "value": str(user_id),
                "display": email,
                "$ref": f"{base_url.rstrip('/')}/scim/v2/Users/{user_id}" if base_url else None,
            }
            for user_id, email in members
        ],
        "meta": {
            "resourceType": "Group",
            "location": f"{base_url.rstrip('/')}/scim/v2/Groups/{group_id}" if base_url else None,
        },
    }


async def create_or_update_user(
    session: AsyncSession,
    *,
    org_id: str,
    payload: dict[str, Any],
    base_url: str = "",
) -> dict[str, Any]:
    email = _primary_email(payload)
    role = _role_from_payload(payload)
    active = bool(payload.get("active", True))
    external_id = str(payload.get("externalId") or "").strip() or None
    user = await _user_by_email(session, email)
    if user is None:
        user = User(
            email=email,
            email_lower=normalize_email(email),
            google_sub=None,
            auth_provider="scim",
            disposable_flag=False,
        )
        session.add(user)
        await session.flush()
    else:
        if user.email != email:
            user.email = email

    membership = await _membership(session, org_id, int(user.id))
    if active:
        membership = await _ensure_membership(
            session, org_id=org_id, user=user, role=role
        )
        identity = await _ensure_identity(
            session,
            org_id=org_id,
            user=user,
            role=role,
            active=True,
            external_id=external_id,
        )
    else:
        await _deprovision_membership(session, org_id=org_id, user=user)
        membership = None
        identity = await _ensure_identity(
            session,
            org_id=org_id,
            user=user,
            role=role,
            active=False,
            external_id=external_id,
        )
    await session.flush()
    return serialize_user(user, membership, identity, base_url=base_url)


async def get_user(
    session: AsyncSession, *, org_id: str, user_id: str, base_url: str = ""
) -> dict[str, Any]:
    try:
        parsed = int(user_id)
    except ValueError as exc:
        raise _scim_error(404, "SCIM user not found.") from exc
    user = await _user_by_id(session, parsed)
    if user is None:
        raise _scim_error(404, "SCIM user not found.")
    identity = await _identity(session, org_id, int(user.id))
    if identity is None:
        raise _scim_error(404, "SCIM user not found in this organization.")
    membership = await _membership(session, org_id, int(user.id))
    return serialize_user(user, membership, identity, base_url=base_url)


def _filter_email(filter_value: str | None) -> str | None:
    if not filter_value:
        return None
    raw = filter_value.strip()
    prefix = "userName eq "
    if not raw.lower().startswith(prefix.lower()):
        return None
    value = raw[len(prefix):].strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


async def list_users(
    session: AsyncSession,
    *,
    org_id: str,
    start_index: int = 1,
    count: int = 100,
    filter_value: str | None = None,
    base_url: str = "",
) -> dict[str, Any]:
    start_index = max(1, int(start_index or 1))
    count = max(1, min(int(count or 100), 100))
    stmt = (
        select(User, ScimIdentity, Membership)
        .join(ScimIdentity, ScimIdentity.user_id == User.id)
        .outerjoin(
            Membership,
            and_(
                Membership.user_id == User.id,
                Membership.org_id == ScimIdentity.org_id,
            ),
        )
        .where(ScimIdentity.org_id == org_id)
        .order_by(User.id.asc())
    )
    email_filter = _filter_email(filter_value)
    if email_filter:
        stmt = stmt.where(User.email_lower == normalize_email(email_filter))
    rows = list((await session.execute(stmt)).all())
    page = rows[start_index - 1:start_index - 1 + count]
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": len(rows),
        "startIndex": start_index,
        "itemsPerPage": len(page),
        "Resources": [
            serialize_user(user, membership, identity, base_url=base_url)
            for user, identity, membership in page
        ],
    }


async def patch_user(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    payload: dict[str, Any],
    base_url: str = "",
) -> dict[str, Any]:
    current = await get_user(session, org_id=org_id, user_id=user_id, base_url=base_url)
    user = await _user_by_id(session, int(current["id"]))
    if user is None:  # pragma: no cover - get_user already proved existence.
        raise _scim_error(404, "SCIM user not found.")
    identity = await _identity(session, org_id, int(user.id))
    if identity is None:  # pragma: no cover - get_user already proved existence.
        raise _scim_error(404, "SCIM user not found in this organization.")
    membership = await _membership(session, org_id, int(user.id))
    role = identity.org_role if identity is not None else "viewer"
    active = bool(identity.active)

    for op in payload.get("Operations") or []:
        if not isinstance(op, dict):
            continue
        path = str(op.get("path") or "").strip().lower()
        value = op.get("value")
        if path == "active":
            active = bool(value)
        elif not path and isinstance(value, dict) and "active" in value:
            active = bool(value["active"])
        elif path in {"roles", "urn:cadverify:params:scim:schemas:extension:2.0:user.orgrole"}:
            role = _role_from_payload({"roles": value if isinstance(value, list) else [value]}, role)
        elif not path and isinstance(value, dict):
            if "roles" in value:
                role = _role_from_payload(value, role)
            if "urn:cadverify:params:scim:schemas:extension:2.0:User" in value:
                role = _role_from_payload(value, role)

    if active:
        membership = await _ensure_membership(session, org_id=org_id, user=user, role=role)
        identity = await _ensure_identity(
            session, org_id=org_id, user=user, role=role, active=True
        )
    else:
        await _deprovision_membership(session, org_id=org_id, user=user)
        membership = None
        identity = await _ensure_identity(
            session, org_id=org_id, user=user, role=role, active=False
        )
    return serialize_user(user, membership, identity, base_url=base_url)


async def list_groups(
    session: AsyncSession,
    *,
    org_id: str,
    base_url: str = "",
) -> dict[str, Any]:
    resources = []
    for role in ("admin", "member", "viewer"):
        rows = (
            await session.execute(
                select(User.id, User.email)
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.org_id == org_id, Membership.org_role == role)
                .order_by(User.id.asc())
            )
        ).all()
        resources.append(serialize_group(role, [(int(uid), email) for uid, email in rows], base_url=base_url))
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": len(resources),
        "startIndex": 1,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


async def get_group(
    session: AsyncSession, *, org_id: str, group_id: str, base_url: str = ""
) -> dict[str, Any]:
    role = ROLE_BY_GROUP_ID.get(group_id)
    if role is None:
        raise _scim_error(404, "SCIM group not found.")
    rows = (
        await session.execute(
            select(User.id, User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.org_id == org_id, Membership.org_role == role)
            .order_by(User.id.asc())
        )
    ).all()
    return serialize_group(role, [(int(uid), email) for uid, email in rows], base_url=base_url)


async def patch_group(
    session: AsyncSession,
    *,
    org_id: str,
    group_id: str,
    payload: dict[str, Any],
    base_url: str = "",
) -> dict[str, Any]:
    role = ROLE_BY_GROUP_ID.get(group_id)
    if role is None:
        raise _scim_error(404, "SCIM group not found.")
    for op in payload.get("Operations") or []:
        if not isinstance(op, dict):
            continue
        action = str(op.get("op") or "").strip().lower()
        value = op.get("value") or []
        members = value if isinstance(value, list) else [value]
        for member in members:
            if not isinstance(member, dict) or not member.get("value"):
                continue
            user = await _user_by_id(session, int(member["value"]))
            if user is None:
                continue
            if action == "add":
                await _ensure_membership(session, org_id=org_id, user=user, role=role)
                await _ensure_identity(
                    session, org_id=org_id, user=user, role=role, active=True
                )
            elif action == "remove":
                membership = await _membership(session, org_id, int(user.id))
                if membership is not None and membership.org_role == role:
                    if role == "viewer":
                        await _deprovision_membership(session, org_id=org_id, user=user)
                        await _ensure_identity(
                            session,
                            org_id=org_id,
                            user=user,
                            role=role,
                            active=False,
                        )
                    else:
                        await _ensure_membership(
                            session, org_id=org_id, user=user, role="viewer"
                        )
                        await _ensure_identity(
                            session,
                            org_id=org_id,
                            user=user,
                            role="viewer",
                            active=True,
                        )
    return await get_group(session, org_id=org_id, group_id=group_id, base_url=base_url)
