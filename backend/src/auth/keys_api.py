"""/api/v1/keys — dashboard-scoped key management (list/create/rotate/revoke/rename).

All routes require a dashboard session cookie (Depends(require_dashboard_session)).
Plaintext tokens are delivered exactly once via a tightly-scoped `cv_mint_once`
cookie (path=/settings/developer, Max-Age=60, SameSite=Lax, Secure). The frontend
scrubs the cookie on mount (see RevealOnceModal.tsx).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import text

from src.auth.dashboard_session import require_dashboard_session
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import _session, create_api_key
from src.services.audit_service import append_audit_entry

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])
KEY_REVEAL_PATH = "/settings/developer"

# Org boundary as defense-in-depth on personal API-key management. ``user_id``
# remains the primary owner predicate, while the correlated subquery selects
# the user's validated active organization, falling back to their oldest live
# membership when ``current_org_id`` is null or stale. This is byte-for-byte the
# same resolution rule as ``org_context.resolve_org`` and keeps SSO-created keys
# visible and manageable after a group mapping switches the active org.
_ORG_SCOPE_SQL = (
    "org_id = COALESCE("
    "(SELECT current_m.org_id FROM memberships current_m "
    "JOIN users current_u ON current_u.id = :u "
    "AND current_u.current_org_id = current_m.org_id "
    "WHERE current_m.user_id = :u LIMIT 1), "
    "(SELECT oldest_m.org_id FROM memberships oldest_m "
    "WHERE oldest_m.user_id = :u "
    "ORDER BY oldest_m.created_at ASC, oldest_m.id ASC LIMIT 1))"
)


class KeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: str
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None


class CreateIn(BaseModel):
    name: str = "Default"


class PatchIn(BaseModel):
    name: str


def _set_reveal_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "cv_mint_once",
        token,
        max_age=60,
        secure=True,
        httponly=False,  # intentional — JS reads + scrubs (see RevealOnceModal)
        samesite="lax",
        path=KEY_REVEAL_PATH,
    )


@router.get("", response_model=list[KeyOut])
async def list_keys(user_id: int = Depends(require_dashboard_session)):
    async with _session()() as s:
        rows = (
            await s.execute(
                text(
                    # nosec B608: no user input in the SQL text — _ORG_SCOPE_SQL
                    # is a module constant and every value (:u) is a bound param.
                    "SELECT id, name, prefix, created_at, last_used_at, revoked_at "  # nosec B608
                    f"FROM api_keys WHERE user_id = :u AND {_ORG_SCOPE_SQL} "
                    "ORDER BY created_at DESC"
                ),
                {"u": user_id},
            )
        ).all()
    return [
        KeyOut(
            id=r[0],
            name=r[1],
            prefix=r[2],
            created_at=str(r[3]),
            last_used_at=str(r[4]) if r[4] else None,
            revoked_at=str(r[5]) if r[5] else None,
        )
        for r in rows
    ]


@router.post("")
async def create_key(
    body: CreateIn,
    response: Response,
    user_id: int = Depends(require_dashboard_session),
):
    token, prefix, secret_hash = mint_token()
    kid = await create_api_key(
        user_id, body.name, prefix, hmac_index(token), secret_hash
    )
    _set_reveal_cookie(response, token)
    return {"id": kid, "prefix": prefix}


@router.post("/{key_id}/rotate")
async def rotate_key(
    key_id: int,
    response: Response,
    user_id: int = Depends(require_dashboard_session),
):
    token, prefix, secret_hash = mint_token()
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    # nosec B608: static constant SQL + bound params (:i, :u).
                    "UPDATE api_keys SET revoked_at = now() "  # nosec B608
                    f"WHERE id = :i AND user_id = :u AND {_ORG_SCOPE_SQL} "
                    "AND revoked_at IS NULL "
                    "RETURNING name, org_id, prefix"
                ),
                {"i": key_id, "u": user_id},
            )
        ).first()
        if r is None:
            raise HTTPException(
                404,
                detail={
                    "code": "key_not_found",
                    "message": "Key not found or already revoked.",
                    "doc_url": "https://docs.cadverify.com/errors#key_not_found",
                },
            )
        name, org_id, old_prefix = r
        created = (
            await s.execute(
                text(
                    "INSERT INTO api_keys "
                    "(user_id, org_id, name, prefix, hmac_index, secret_hash) "
                    "VALUES (:u, :o, :n, :p, :h, :s) RETURNING id"
                ),
                {
                    "u": user_id,
                    "o": org_id,
                    "n": name,
                    "p": prefix,
                    "h": hmac_index(token),
                    "s": secret_hash,
                },
            )
        ).first()
        if created is None:
            raise RuntimeError("API key rotation insert returned no row")
        new_id = int(created[0])
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
            {"key_prefix": prefix, "rotated_from_id": key_id},
            org_id=str(org_id),
        )
        await s.commit()
    _set_reveal_cookie(response, token)
    return {"id": new_id, "prefix": prefix}


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: int, user_id: int = Depends(require_dashboard_session)
):
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    # nosec B608: static constant SQL + bound params (:i, :u).
                    "UPDATE api_keys SET revoked_at = now() "  # nosec B608
                    f"WHERE id = :i AND user_id = :u AND {_ORG_SCOPE_SQL} "
                    "AND revoked_at IS NULL "
                    "RETURNING id, org_id, prefix"
                ),
                {"i": key_id, "u": user_id},
            )
        ).first()
        if r is None:
            raise HTTPException(
                404,
                detail={
                    "code": "key_not_found",
                    "message": "Key not found or already revoked.",
                    "doc_url": "https://docs.cadverify.com/errors#key_not_found",
                },
            )
        await append_audit_entry(
            s,
            user_id,
            "api_key.revoked",
            "api_key",
            str(r[0]),
            {"key_prefix": r[2], "reason": "user_requested"},
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
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    # nosec B608: static constant SQL + bound params (:n, :i, :u).
                    "UPDATE api_keys SET name = :n "  # nosec B608
                    f"WHERE id = :i AND user_id = :u AND {_ORG_SCOPE_SQL} "
                    "RETURNING id, org_id, prefix"
                ),
                {"i": key_id, "u": user_id, "n": body.name},
            )
        ).first()
        if r is None:
            raise HTTPException(
                404,
                detail={
                    "code": "key_not_found",
                    "message": "Key not found.",
                    "doc_url": "https://docs.cadverify.com/errors#key_not_found",
                },
            )
        await append_audit_entry(
            s,
            user_id,
            "api_key.renamed",
            "api_key",
            str(r[0]),
            {"key_prefix": r[2], "name": body.name},
            org_id=str(r[1]),
        )
        await s.commit()
    return {"id": key_id, "name": body.name}
