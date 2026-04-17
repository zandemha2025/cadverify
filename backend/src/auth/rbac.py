"""RBAC: Role-Based Access Control for CADVerify on-prem deployments.

Three roles with hierarchical rank:
  viewer  (1) - read-only access to analyses, processes, materials
  analyst (2) - can trigger analyses, manage own API keys
  admin   (3) - full access including user management and audit logs
"""
from __future__ import annotations

from enum import Enum

from fastapi import Depends, HTTPException

from src.auth.require_api_key import AuthedUser, require_api_key


class Role(str, Enum):
    viewer = "viewer"
    analyst = "analyst"
    admin = "admin"

    @property
    def rank(self) -> int:
        return {"viewer": 1, "analyst": 2, "admin": 3}[self.value]


def require_role(min_role: Role):
    """Return a FastAPI dependency that enforces a minimum role level.

    Composes with require_api_key: the user is first authenticated via
    API key, then their role is checked against the minimum required.
    """

    async def _check(user: AuthedUser = Depends(require_api_key)) -> AuthedUser:
        if Role(user.role).rank < min_role.rank:
            raise HTTPException(
                403,
                detail={
                    "code": "insufficient_role",
                    "message": f"Requires {min_role.value} role or higher",
                    "doc_url": "https://docs.cadverify.com/errors#insufficient_role",
                },
            )
        return user

    return _check
