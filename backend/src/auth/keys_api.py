"""/api/v1/keys — dashboard-scoped key management.

All routes require a dashboard session cookie (Depends(require_dashboard_session)).

- Each key has a scope, ``read`` (GET, HEAD and OPTIONS only) or ``read_write``,
  and an optional expiry (30, 90 or 365 days). New keys are read only unless
  the person asks for read and write; a viewer can only make read-only keys,
  and a viewer's key is read only whatever it says (``require_api_key``).
- The person who made a key lists, renames, rotates and revokes it. An org
  admin also lists every key in the organization (``GET /api/v1/keys/org``)
  and can revoke any of them; nobody but the owner can rotate or rename one.
- A new secret is returned once, in the create or rotate response body
  (``secret``), to the caller that asked for it. The legacy reveal cookie
  (``cv_mint_once``, path=/settings/developer, Max-Age=60) is still set for the
  old developer page. Only a fingerprint is stored.
"""
from __future__ import annotations

from src.config.public_urls import error_doc_url

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import text

from src.auth.dashboard_session import require_dashboard_session
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import _session
from src.auth.require_api_key import SCOPE_READ, SCOPE_READ_WRITE, effective_key_scope
from src.services.audit_service import append_audit_entry

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])
KEY_REVEAL_PATH = "/settings/developer"
EXPIRY_DAYS = (30, 90, 365)
NAME_MAX = 80
ORG_LIST_LIMIT = 500

# The user's validated active organization, falling back to their oldest live
# membership when ``current_org_id`` is null or stale. This is byte-for-byte
# the same resolution rule as ``org_context.resolve_org`` and keeps SSO-created
# keys visible and manageable after a group mapping switches the active org.
_ACTIVE_ORG_SQL = (
    "COALESCE("
    "(SELECT current_m.org_id FROM memberships current_m "
    "JOIN users current_u ON current_u.id = :u "
    "AND current_u.current_org_id = current_m.org_id "
    "WHERE current_m.user_id = :u LIMIT 1), "
    "(SELECT oldest_m.org_id FROM memberships oldest_m "
    "WHERE oldest_m.user_id = :u "
    "ORDER BY oldest_m.created_at ASC, oldest_m.id ASC LIMIT 1))"
)
# Org boundary as defense-in-depth on single-table key statements.
_ORG_SCOPE_SQL = f"org_id = {_ACTIVE_ORG_SQL}"

# Columns every key listing reads (``k`` is api_keys, ``km`` the owner's
# membership in the key's org).
_KEY_COLUMNS = (
    "k.id, k.name, k.prefix, k.created_at, k.last_used_at, k.revoked_at, "
    "k.scope, k.expires_at, "
    "(k.expires_at IS NOT NULL AND k.expires_at <= now()) AS expired, "
    "km.org_role"
)


class KeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: str
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None
    # As chosen at creation: "read" or "read_write" (keys made before scopes
    # existed read as "read_write").
    scope: str = SCOPE_READ_WRITE
    # As enforced: a viewer's key is "read" whatever ``scope`` says.
    effective_scope: str = SCOPE_READ_WRITE
    expires_at: Optional[str] = None
    expired: bool = False


class OrgKeyOut(KeyOut):
    owner_user_id: int
    owner_email: Optional[str] = None
    # The owner's org role in the key's org; None once they have left it (the
    # key then no longer works).
    owner_role: Optional[str] = None
    yours: bool = False


class OrgKeysOut(BaseModel):
    org_id: str
    org_name: Optional[str] = None
    keys: list[OrgKeyOut]


class CreateIn(BaseModel):
    name: str = "Default"
    scope: Literal["read", "read_write"] = SCOPE_READ
    expires_in_days: Optional[Literal[30, 90, 365]] = None


class PatchIn(BaseModel):
    name: str


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status,
        detail={"code": code, "message": message, "doc_url": error_doc_url(code)},
    )


def _key_not_found(message: str = "Key not found or already revoked.") -> HTTPException:
    return _error(404, "key_not_found", message)


def _clean_name(raw: str) -> str:
    return (raw or "").strip()[:NAME_MAX] or "Default"


def _iso(value) -> Optional[str]:
    return str(value) if value is not None else None


def _key_out(r) -> dict:
    stored = r[6] or SCOPE_READ_WRITE
    return {
        "id": int(r[0]),
        "name": r[1],
        "prefix": r[2],
        "created_at": str(r[3]),
        "last_used_at": _iso(r[4]),
        "revoked_at": _iso(r[5]),
        "scope": stored,
        "effective_scope": effective_key_scope(stored, r[9]),
        "expires_at": _iso(r[7]),
        "expired": bool(r[8]),
    }


def _set_reveal_cookie(response: Response, token: str) -> None:
    """The legacy developer page's one-time reveal (the v4 page reads ``secret``)."""
    response.set_cookie(
        "cv_mint_once",
        token,
        max_age=60,
        secure=True,
        httponly=False,  # intentional — JS reads + scrubs (see RevealOnceModal)
        samesite="lax",
        path=KEY_REVEAL_PATH,
    )


async def _active_membership(s, user_id: int) -> tuple[str, str] | None:
    """``(org_id, org_role)`` in the user's active organization."""
    row = (
        await s.execute(
            text(
                # nosec B608: static constant SQL + bound params (:u).
                "SELECT org_id, org_role FROM memberships "  # nosec B608
                f"WHERE user_id = :u AND {_ORG_SCOPE_SQL} LIMIT 1"
            ),
            {"u": user_id},
        )
    ).first()
    return (str(row[0]), str(row[1])) if row else None


async def _role_in(s, user_id: int, org_id: str) -> Optional[str]:
    row = (
        await s.execute(
            text("SELECT org_role FROM memberships WHERE user_id = :u AND org_id = :o"),
            {"u": user_id, "o": org_id},
        )
    ).first()
    return str(row[0]) if row else None


async def _insert_key(
    s,
    *,
    user_id: int,
    org_id: str,
    name: str,
    scope: str,
    expires_at: Optional[datetime],
) -> tuple[int, str, str]:
    """Insert a key and return ``(id, prefix, token)``; the caller commits."""
    token, prefix, secret_hash = mint_token()
    row = (
        await s.execute(
            text(
                "INSERT INTO api_keys "
                "(user_id, org_id, name, prefix, hmac_index, secret_hash, scope, expires_at) "
                "VALUES (:u, :o, :n, :p, :h, :s, :scope, :exp) RETURNING id"
            ),
            {
                "u": user_id,
                "o": org_id,
                "n": name,
                "p": prefix,
                "h": hmac_index(token),
                "s": secret_hash,
                "scope": scope,
                "exp": expires_at,
            },
        )
    ).first()
    if row is None:
        raise RuntimeError("API key insert returned no row")
    return int(row[0]), prefix, token


def _minted(
    response: Response,
    *,
    key_id: int,
    prefix: str,
    token: str,
    name: str,
    scope: str,
    org_role: Optional[str],
    expires_at: Optional[datetime],
) -> dict:
    _set_reveal_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return {
        "id": key_id,
        "prefix": prefix,
        "name": name,
        "scope": scope,
        "effective_scope": effective_key_scope(scope, org_role),
        "expires_at": expires_at.isoformat() if expires_at else None,
        # Shown once; only a fingerprint is stored.
        "secret": token,
    }


@router.get("", response_model=list[KeyOut])
async def list_keys(user_id: int = Depends(require_dashboard_session)):
    """The caller's own keys in their active organization."""
    async with _session()() as s:
        rows = (
            await s.execute(
                text(
                    # nosec B608: no user input in the SQL text — the column
                    # list and org rule are module constants; :u is bound.
                    f"SELECT {_KEY_COLUMNS} FROM api_keys k "  # nosec B608
                    "LEFT JOIN memberships km ON km.user_id = k.user_id "
                    "AND km.org_id = k.org_id "
                    f"WHERE k.user_id = :u AND k.org_id = {_ACTIVE_ORG_SQL} "
                    "ORDER BY k.created_at DESC"
                ),
                {"u": user_id},
            )
        ).all()
    return [KeyOut(**_key_out(r)) for r in rows]


@router.get("/org", response_model=OrgKeysOut)
async def list_org_keys(user_id: int = Depends(require_dashboard_session)):
    """Every key in the caller's active organization: org admins only."""
    async with _session()() as s:
        membership = await _active_membership(s, user_id)
        if membership is None or membership[1] != "admin":
            raise _error(
                403,
                "org_admin_required",
                "Only an org admin sees every key in the organization. You see your own keys.",
            )
        org_id = membership[0]
        rows = (
            await s.execute(
                text(
                    # nosec B608: constant column list; :o and :lim are bound.
                    f"SELECT {_KEY_COLUMNS}, k.user_id, u.email FROM api_keys k "  # nosec B608
                    "JOIN users u ON u.id = k.user_id "
                    "LEFT JOIN memberships km ON km.user_id = k.user_id "
                    "AND km.org_id = k.org_id "
                    "WHERE k.org_id = :o "
                    "ORDER BY (k.revoked_at IS NULL) DESC, k.created_at DESC, k.id DESC "
                    "LIMIT :lim"
                ),
                {"o": org_id, "lim": ORG_LIST_LIMIT},
            )
        ).all()
        name_row = (
            await s.execute(text("SELECT name FROM organizations WHERE id = :o"), {"o": org_id})
        ).first()
    keys = [
        OrgKeyOut(
            **_key_out(r),
            owner_user_id=int(r[10]),
            owner_email=r[11],
            owner_role=r[9],
            yours=int(r[10]) == user_id,
        )
        for r in rows
    ]
    return OrgKeysOut(org_id=org_id, org_name=name_row[0] if name_row else None, keys=keys)


@router.post("")
async def create_key(
    body: CreateIn,
    response: Response,
    user_id: int = Depends(require_dashboard_session),
):
    name = _clean_name(body.name)
    async with _session()() as s:
        membership = await _active_membership(s, user_id)
        if membership is None:
            raise _error(
                409,
                "org_required",
                "Your account isn't in an organization yet, so it can't hold a key.",
            )
        org_id, org_role = membership
        if body.scope == SCOPE_READ_WRITE and org_role == "viewer":
            raise _error(
                403,
                "api_key_scope_not_allowed",
                "Viewers can make read-only keys only. Ask an admin for Member "
                "access to make a read-and-write key.",
            )
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
            if body.expires_in_days
            else None
        )
        key_id, prefix, token = await _insert_key(
            s,
            user_id=user_id,
            org_id=org_id,
            name=name,
            scope=body.scope,
            expires_at=expires_at,
        )
        await append_audit_entry(
            s,
            user_id,
            "api_key.created",
            "api_key",
            str(key_id),
            {
                "key_prefix": prefix,
                "name": name,
                "scope": body.scope,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
            org_id=org_id,
        )
        await s.commit()
    return _minted(
        response,
        key_id=key_id,
        prefix=prefix,
        token=token,
        name=name,
        scope=body.scope,
        org_role=org_role,
        expires_at=expires_at,
    )


@router.post("/{key_id}/rotate")
async def rotate_key(
    key_id: int,
    response: Response,
    user_id: int = Depends(require_dashboard_session),
):
    """Revoke the caller's key and make its replacement, in one transaction.

    The replacement keeps the name, the scope (read only if the owner is now a
    viewer) and the same lifetime from now.
    """
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    # nosec B608: static constant SQL + bound params (:i, :u).
                    "UPDATE api_keys SET revoked_at = now() "  # nosec B608
                    f"WHERE id = :i AND user_id = :u AND {_ORG_SCOPE_SQL} "
                    "AND revoked_at IS NULL "
                    "RETURNING name, org_id, prefix, scope, expires_at - created_at"
                ),
                {"i": key_id, "u": user_id},
            )
        ).first()
        if r is None:
            raise _key_not_found()
        name, org_id, old_prefix, old_scope, lifetime = r
        org_role = await _role_in(s, user_id, org_id)
        scope = (
            SCOPE_READ
            if org_role == "viewer"
            else (old_scope or SCOPE_READ_WRITE)
        )
        expires_at = (
            datetime.now(timezone.utc) + lifetime
            if isinstance(lifetime, timedelta)
            else None
        )
        new_id, prefix, token = await _insert_key(
            s,
            user_id=user_id,
            org_id=org_id,
            name=name,
            scope=scope,
            expires_at=expires_at,
        )
        await append_audit_entry(
            s,
            user_id,
            "api_key.revoked",
            "api_key",
            str(key_id),
            {"key_prefix": old_prefix, "reason": "rotation", "replacement_id": new_id},
            org_id=str(org_id),
        )
        await append_audit_entry(
            s,
            user_id,
            "api_key.created",
            "api_key",
            str(new_id),
            {
                "key_prefix": prefix,
                "rotated_from_id": key_id,
                "name": name,
                "scope": scope,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
            org_id=str(org_id),
        )
        await s.commit()
    return _minted(
        response,
        key_id=new_id,
        prefix=prefix,
        token=token,
        name=name,
        scope=scope,
        org_role=org_role,
        expires_at=expires_at,
    )


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: int, user_id: int = Depends(require_dashboard_session)
):
    """Revoke a key: the owner's own, or any key in the org for an org admin."""
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    # nosec B608: static constant SQL + bound params (:i, :u).
                    "UPDATE api_keys SET revoked_at = now() "  # nosec B608
                    f"WHERE id = :i AND {_ORG_SCOPE_SQL} AND revoked_at IS NULL "
                    "AND (user_id = :u OR EXISTS ("
                    "SELECT 1 FROM memberships adm WHERE adm.user_id = :u "
                    "AND adm.org_id = api_keys.org_id AND adm.org_role = 'admin')) "
                    "RETURNING id, org_id, prefix, user_id"
                ),
                {"i": key_id, "u": user_id},
            )
        ).first()
        if r is None:
            raise _key_not_found()
        owner_id = int(r[3])
        detail = {
            "key_prefix": r[2],
            "reason": "user_requested" if owner_id == user_id else "org_admin_revoked",
        }
        if owner_id != user_id:
            detail["owner_user_id"] = owner_id
        await append_audit_entry(
            s,
            user_id,
            "api_key.revoked",
            "api_key",
            str(r[0]),
            detail,
            org_id=str(r[1]),
        )
        await s.commit()
    return Response(status_code=204)


@router.patch("/{key_id}")
async def rename_key(
    key_id: int,
    body: PatchIn,
    user_id: int = Depends(require_dashboard_session),
):
    name = _clean_name(body.name)
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    # nosec B608: static constant SQL + bound params (:n, :i, :u).
                    "UPDATE api_keys SET name = :n "  # nosec B608
                    f"WHERE id = :i AND user_id = :u AND {_ORG_SCOPE_SQL} "
                    "RETURNING id, org_id, prefix"
                ),
                {"i": key_id, "u": user_id, "n": name},
            )
        ).first()
        if r is None:
            raise _key_not_found("Key not found.")
        await append_audit_entry(
            s,
            user_id,
            "api_key.renamed",
            "api_key",
            str(r[0]),
            {"key_prefix": r[2], "name": name},
            org_id=str(r[1]),
        )
        await s.commit()
    return {"id": key_id, "name": name}
