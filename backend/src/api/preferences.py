"""Per-user settings that follow the person across devices (migration 0056).

``GET /api/v1/account/preferences`` → ``{"length_unit": "mm" | "in"}``
``PUT /api/v1/account/preferences`` with any subset of the known keys.

Only the length unit exists today: how the app shows lengths, areas and
volumes. The engine always works in millimetres; this is display only. Unknown
keys and values are a 400, never silently stored.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.db.models import User

router = APIRouter(tags=["account"])

DEFAULTS = {"length_unit": "mm"}


class PreferencesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    length_unit: Optional[Literal["mm", "in"]] = None


def public(prefs: Optional[dict]) -> dict:
    """The known settings with defaults filled in (stored junk is ignored)."""
    out = dict(DEFAULTS)
    unit = (prefs or {}).get("length_unit")
    if unit in ("mm", "in"):
        out["length_unit"] = unit
    return out


async def _user(session: AsyncSession, user_id: int) -> User:
    row = await session.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return row


@router.get("")
@limiter.limit("600/hour;5000/day")
async def get_preferences(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    return public((await _user(session, user.user_id)).preferences)


@router.put("")
@limiter.limit("120/hour;600/day")
async def set_preferences(
    request: Request,
    response: Response,
    body: PreferencesBody,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    row = await _user(session, user.user_id)
    prefs = dict(row.preferences or {})
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            prefs.pop(key, None)
        else:
            prefs[key] = value
    row.preferences = prefs
    await session.commit()
    return public(prefs)
