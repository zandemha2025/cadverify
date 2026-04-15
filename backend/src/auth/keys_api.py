"""/api/v1/keys — dashboard-scoped key management (list/create/rotate/revoke/rename).

All routes require a dashboard session cookie (Depends(require_dashboard_session)).
Plaintext tokens are delivered exactly once via a tightly-scoped `cv_mint_once`
cookie (path=/dashboard/keys, Max-Age=60, SameSite=Lax, Secure). The frontend
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

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])


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
        path="/dashboard/keys",
    )


@router.get("", response_model=list[KeyOut])
async def list_keys(user_id: int = Depends(require_dashboard_session)):
    async with _session()() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT id, name, prefix, created_at, last_used_at, revoked_at "
                    "FROM api_keys WHERE user_id = :u ORDER BY created_at DESC"
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
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "UPDATE api_keys SET revoked_at = now() "
                    "WHERE id = :i AND user_id = :u AND revoked_at IS NULL "
                    "RETURNING name"
                ),
                {"i": key_id, "u": user_id},
            )
        ).first()
        await s.commit()
        if r is None:
            raise HTTPException(
                404,
                detail={
                    "code": "key_not_found",
                    "message": "Key not found or already revoked.",
                    "doc_url": "https://docs.cadverify.com/errors#key_not_found",
                },
            )
        name = r[0]
    token, prefix, secret_hash = mint_token()
    new_id = await create_api_key(
        user_id, name, prefix, hmac_index(token), secret_hash
    )
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
                    "UPDATE api_keys SET revoked_at = now() "
                    "WHERE id = :i AND user_id = :u AND revoked_at IS NULL "
                    "RETURNING id"
                ),
                {"i": key_id, "u": user_id},
            )
        ).first()
        await s.commit()
    if r is None:
        raise HTTPException(
            404,
            detail={
                "code": "key_not_found",
                "message": "Key not found or already revoked.",
                "doc_url": "https://docs.cadverify.com/errors#key_not_found",
            },
        )
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
                    "UPDATE api_keys SET name = :n "
                    "WHERE id = :i AND user_id = :u RETURNING id"
                ),
                {"i": key_id, "u": user_id, "n": body.name},
            )
        ).first()
        await s.commit()
    if r is None:
        raise HTTPException(
            404,
            detail={
                "code": "key_not_found",
                "message": "Key not found.",
                "doc_url": "https://docs.cadverify.com/errors#key_not_found",
            },
        )
    return {"id": key_id, "name": body.name}
