"""SCIM 2.0 user and role-group lifecycle service.

This is the first real enterprise identity provisioning surface. It deliberately
uses the platform's existing bearer API-key auth at the router boundary, then
applies all writes to the caller's org membership table so deprovisioning removes
tenant access on the next request.
"""
from __future__ import annotations

import re
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


# ---------------------------------------------------------------------------
# RFC 7644 §3.5.2 PatchOp parsing (op verb + attribute-path grammar)
# ---------------------------------------------------------------------------

_VALID_PATCH_OPS = {"add", "replace", "remove"}

# A pragmatic subset of the SCIM attribute-path grammar (RFC 7644 §3.5.2 +
# the filter grammar of §3.4.2.2) that covers what Okta and Entra actually
# emit: a bare attribute (``active``), a value-path filter
# (``members[value eq "123"]``), a sub-attribute (``name.formatted``), and the
# combination (``emails[type eq "work"].value``). URN-prefixed extension paths
# (``urn:...:User:orgRole``) are matched by the leading-attribute alternative.
_PATCH_PATH_RE = re.compile(
    r"""^\s*
        (?P<attr>[^\[\].\s]+)
        (?:\[\s*(?P<fattr>[^\s\]]+)\s+(?P<fop>\w+)\s+"(?P<fval>[^"]*)"\s*\])?
        (?:\.(?P<sub>[^\[\].\s]+))?
        \s*$""",
    re.VERBOSE,
)


def _parse_patch_path(path: Any) -> tuple[str, tuple[str, str] | None, str | None]:
    """Return ``(attr_lower, (filter_attr_lower, filter_value) | None, sub_lower)``.

    An empty/omitted path returns ``("", None, None)`` (a whole-resource
    PatchOp). A path that does not parse raises a SCIM 400 ``invalidPath`` — it
    must never surface as a 500.
    """
    if path is None:
        return ("", None, None)
    if not isinstance(path, str):
        raise _scim_error(400, f"PATCH path must be a string, got {type(path).__name__}.", "invalidPath")
    raw = path.strip()
    if not raw:
        return ("", None, None)
    match = _PATCH_PATH_RE.match(raw)
    if match is None:
        raise _scim_error(400, f"Unparseable PATCH path {path!r}.", "invalidPath")
    attr = match.group("attr").strip().lower()
    filt: tuple[str, str] | None = None
    if match.group("fattr"):
        fop = (match.group("fop") or "").lower()
        if fop != "eq":
            raise _scim_error(
                400,
                f"Unsupported PATCH filter operator {match.group('fop')!r} (only 'eq').",
                "invalidPath",
            )
        filt = (match.group("fattr").strip().lower(), match.group("fval"))
    sub = match.group("sub").strip().lower() if match.group("sub") else None
    return (attr, filt, sub)


def _coerce_bool(value: Any) -> bool:
    """Coerce a SCIM value to bool. Okta sends a JSON bool; Entra sometimes
    sends the string ``"True"``/``"False"``. Anything else is ``invalidValue``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, list) and len(value) == 1:
        return _coerce_bool(value[0])
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "1"}:
            return True
        if token in {"false", "0"}:
            return False
    raise _scim_error(400, f"Invalid boolean value {value!r}.", "invalidValue")


def _role_from_patch_value(value: Any, current: str) -> str:
    """Resolve an org role from a ``roles`` PatchOp value (list | dict | str)."""
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    return _role_from_payload({"roles": items}, current)


def _email_from_patch_value(value: Any, sub_attr: str | None) -> str | None:
    """Extract a primary email string from an ``emails`` PatchOp value.

    Handles ``emails[type eq "work"].value`` (``sub_attr='value'`` + str value),
    a bare string, a single ``{"value": ...}`` object, or a list of such.
    """
    if sub_attr == "value" and isinstance(value, str):
        return value.strip() or None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        candidate = value.get("value")
        return str(candidate).strip() or None if candidate else None
    if isinstance(value, list):
        for item in value:
            got = _email_from_patch_value(item, sub_attr)
            if got:
                return got
    return None


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
                "description": "Use an org-admin ProofShape API key as the SCIM bearer token.",
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
        "displayName": f"ProofShape {role}",
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


def _apply_user_value_bag(
    value: dict[str, Any], active: bool, role: str, email_change: str | None
) -> tuple[bool, str, str | None]:
    """Apply a pathless PatchOp value object (Entra's shape) case-insensitively."""
    for key, item in value.items():
        low = str(key).strip().lower()
        if low == "active":
            active = _coerce_bool(item)
        elif low == "roles":
            role = _role_from_patch_value(item, role)
        elif low == "emails":
            email_change = _email_from_patch_value(item, None) or email_change
        elif low == "username" and isinstance(item, str) and item.strip():
            email_change = item.strip()
        elif low.startswith("urn:cadverify") and isinstance(item, dict):
            role = _role_from_payload({low: item}, role)
        # 'name' and any unknown attribute in a value bag are ignored (no 400):
        # a pathless replace legitimately carries the whole resource.
    return active, role, email_change


async def _apply_email_change(session: AsyncSession, user: User, new_email: str) -> None:
    """Update the user's primary email from a PATCH, guarding the unique key.

    A case/format-only change updates only the display ``email``. A change that
    lands on a DIFFERENT normalized identity that another row already holds is a
    SCIM 409 ``uniqueness`` (never an unhandled IntegrityError/500).
    """
    new_lower = normalize_email(new_email)
    current_lower = (user.email_lower or "").lower()
    if new_lower != current_lower:
        clash = (
            await session.execute(
                select(User).where(User.email_lower == new_lower, User.id != user.id)
            )
        ).scalars().first()
        if clash is not None:
            raise _scim_error(409, "Email already in use by another user.", "uniqueness")
        user.email = new_email
        user.email_lower = new_lower
    elif user.email != new_email:
        user.email = new_email
    await session.flush()


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
    email_change: str | None = None

    operations = payload.get("Operations")
    if operations is None or not isinstance(operations, list):
        raise _scim_error(
            400, "PatchOp requires an 'Operations' array.", "invalidSyntax"
        )

    for op in operations:
        if not isinstance(op, dict):
            raise _scim_error(400, "Each PatchOp operation must be an object.", "invalidSyntax")
        verb = str(op.get("op") or "").strip().lower()
        if verb not in _VALID_PATCH_OPS:
            raise _scim_error(400, f"Unsupported PatchOp op {op.get('op')!r}.", "invalidSyntax")
        attr, _filt, sub = _parse_patch_path(op.get("path"))
        value = op.get("value")

        if attr == "":
            # Whole-resource op: Entra sends ``replace`` with a value object.
            if verb == "remove":
                raise _scim_error(400, "A 'remove' PatchOp requires a path.", "noTarget")
            if not isinstance(value, dict):
                raise _scim_error(
                    400, "A pathless PatchOp value must be an object.", "invalidValue"
                )
            active, role, email_change = _apply_user_value_bag(
                value, active, role, email_change
            )
        elif attr == "active":
            if verb != "remove":  # remove of a boolean attr is tolerated as a no-op
                active = _coerce_bool(value)
        elif attr == "roles":
            role = "viewer" if verb == "remove" else _role_from_patch_value(value, role)
        elif attr == "orgrole" or attr.startswith("urn:cadverify"):
            role = "viewer" if verb == "remove" else _clean_role(value, role)
        elif attr == "emails":
            if verb != "remove":
                email_change = _email_from_patch_value(value, sub) or email_change
        elif attr == "username":
            if verb != "remove" and isinstance(value, str) and value.strip():
                email_change = value.strip()
        elif attr == "name":
            # No dedicated name column (name.formatted is derived from email);
            # accept and ignore rather than 400 so Okta's name sync is a no-op.
            continue
        else:
            raise _scim_error(400, f"Unsupported PATCH path {op.get('path')!r}.", "invalidPath")

    if email_change:
        await _apply_email_change(session, user, email_change)

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

    operations = payload.get("Operations")
    if operations is None or not isinstance(operations, list):
        raise _scim_error(
            400, "PatchOp requires an 'Operations' array.", "invalidSyntax"
        )

    for op in operations:
        if not isinstance(op, dict):
            raise _scim_error(400, "Each PatchOp operation must be an object.", "invalidSyntax")
        verb = str(op.get("op") or "").strip().lower()
        if verb not in _VALID_PATCH_OPS:
            raise _scim_error(400, f"Unsupported PatchOp op {op.get('op')!r}.", "invalidSyntax")
        attr, filt, _sub = _parse_patch_path(op.get("path"))

        # Group PatchOps only touch 'members' (and displayName, which we do not
        # persist). Ignore non-member paths rather than 400 so an IdP syncing
        # displayName is a tolerated no-op. A pathless op is treated as members.
        if attr not in ("", "members"):
            continue

        member_ids = _extract_member_ids(op.get("value"), filt, attr)

        if verb == "remove" and filt is None and not member_ids and attr == "members":
            # ``{"op":"remove","path":"members"}`` clears the whole group.
            member_ids = await _current_role_member_ids(session, org_id, role)

        if verb == "replace" and attr in ("", "members"):
            await _replace_group_members(session, org_id, role, member_ids)
            continue

        for raw_id in member_ids:
            user = await _resolve_member_user(session, raw_id)
            if user is None:
                continue
            if verb in ("add", "replace"):
                await _ensure_membership(session, org_id=org_id, user=user, role=role)
                await _ensure_identity(
                    session, org_id=org_id, user=user, role=role, active=True
                )
            elif verb == "remove":
                await _remove_from_role_group(session, org_id, role, user)
    return await get_group(session, org_id=org_id, group_id=group_id, base_url=base_url)


def _extract_member_ids(
    value: Any, filt: tuple[str, str] | None, attr: str
) -> list[str]:
    """Collect member ids from a value-path filter and/or a value list/object.

    Covers Okta's ``members[value eq "123"]`` (id in the filter, no value) and
    Entra's ``{"path":"members","value":[{"value":"123"}]}`` (id in the value).
    """
    ids: list[str] = []
    if filt is not None and filt[0] == "value":
        ids.append(filt[1])
    items: list[Any]
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        # A pathless value bag may wrap the list under 'members'.
        if attr == "" and isinstance(value.get("members"), list):
            items = value["members"]
        else:
            items = [value]
    elif value is None:
        items = []
    else:
        items = [value]
    for item in items:
        if isinstance(item, dict) and item.get("value") is not None:
            ids.append(str(item["value"]))
        elif isinstance(item, (str, int)):
            ids.append(str(item))
    return ids


async def _resolve_member_user(session: AsyncSession, raw_id: str) -> User | None:
    """Parse a SCIM member id to an int and load the user, or 400 invalidValue."""
    try:
        parsed = int(str(raw_id).strip())
    except (TypeError, ValueError) as exc:
        raise _scim_error(400, f"Invalid member value {raw_id!r}.", "invalidValue") from exc
    return await _user_by_id(session, parsed)


async def _current_role_member_ids(
    session: AsyncSession, org_id: str, role: str
) -> list[str]:
    rows = (
        await session.execute(
            select(Membership.user_id).where(
                Membership.org_id == org_id, Membership.org_role == role
            )
        )
    ).scalars().all()
    return [str(int(uid)) for uid in rows]


async def _remove_from_role_group(
    session: AsyncSession, org_id: str, role: str, user: User
) -> None:
    """Remove a user from a role group. A viewer removal deprovisions the org
    membership; a higher-role removal demotes to viewer (preserving access),
    mirroring the original semantics and the last-admin protection."""
    membership = await _membership(session, org_id, int(user.id))
    if membership is None or membership.org_role != role:
        return
    if role == "viewer":
        await _deprovision_membership(session, org_id=org_id, user=user)
        await _ensure_identity(session, org_id=org_id, user=user, role=role, active=False)
    else:
        await _ensure_membership(session, org_id=org_id, user=user, role="viewer")
        await _ensure_identity(session, org_id=org_id, user=user, role="viewer", active=True)


async def _replace_group_members(
    session: AsyncSession, org_id: str, role: str, member_ids: list[str]
) -> None:
    """RFC 7644 ``replace`` on ``members``: the listed ids become the exact
    membership set of the role group — add the newcomers, remove the absent."""
    desired: set[int] = set()
    for raw_id in member_ids:
        user = await _resolve_member_user(session, raw_id)
        if user is not None:
            desired.add(int(user.id))
    current = {
        int(uid) for uid in (await _current_role_member_ids(session, org_id, role))
    }
    for uid in desired - current:
        user = await _user_by_id(session, uid)
        if user is not None:
            await _ensure_membership(session, org_id=org_id, user=user, role=role)
            await _ensure_identity(session, org_id=org_id, user=user, role=role, active=True)
    for uid in current - desired:
        user = await _user_by_id(session, uid)
        if user is not None:
            await _remove_from_role_group(session, org_id, role, user)
