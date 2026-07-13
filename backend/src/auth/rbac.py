"""RBAC: Role-Based Access Control for CADVerify.

Two distinct authorization axes (W1 step 2 — org-scoped RBAC):

1. PLATFORM role — ``users.role`` (``Role`` below). Governs product-tier
   capabilities on the ~43 data routes via ``require_role``: viewer(1) <
   analyst(2) < admin(3) < superadmin(4). This axis is unchanged from the flat
   pre-W1 model except for the new ``superadmin`` tier (migration 0010) — a
   *platform staff* principal that sits above every org boundary. Every existing
   role keeps its rank, so ``require_role`` and all its call sites keep working
   byte-for-byte.

2. ORG role — ``memberships.org_role`` (``OrgRole`` below). Governs who may
   administer *an organization's* resources via ``require_org_role``:
   viewer(1) < member(2) < admin(3), scoped to the caller's own org. This is the
   authority that answers "can this user manage THIS org's members" — the thing
   ``admin_routes`` now derives its access from.

The two axes are deliberately separate enums: a user can be a platform
``analyst`` while being the ``admin`` of their personal org, and a platform
``superadmin`` transcends org membership entirely (they may hold no membership
at all yet still administer any org).
"""
from __future__ import annotations

from src.config.public_urls import error_doc_url

from enum import Enum
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from src.auth.models import lookup_org_membership
from src.auth.require_api_key import AuthedUser, require_api_key


# ---------------------------------------------------------------------------
# Platform role (users.role) — the flat product-tier axis, + superadmin (0010)
# ---------------------------------------------------------------------------


class Role(str, Enum):
    viewer = "viewer"
    analyst = "analyst"
    admin = "admin"
    # W1 step 2: platform staff. Strictly above ``admin`` so ``require_role``
    # keeps admitting superadmins to every admin-gated route; distinct from an
    # org's ``admin`` (that is ``OrgRole.admin``). Provisioned out-of-band, never
    # assignable through the self-service admin API.
    superadmin = "superadmin"

    @property
    def rank(self) -> int:
        return {"viewer": 1, "analyst": 2, "admin": 3, "superadmin": 4}[self.value]


def require_role(min_role: Role):
    """Return a FastAPI dependency enforcing a minimum PLATFORM role.

    Unchanged W1-step-1 behavior: composes with ``require_api_key`` and checks
    ``users.role`` rank. A ``superadmin`` (rank 4) clears every threshold, so
    existing ``require_role(Role.admin)`` gates now also admit platform staff.
    """

    async def _check(user: AuthedUser = Depends(require_api_key)) -> AuthedUser:
        try:
            rank = Role(user.role).rank
        except ValueError:
            # An unknown role string is treated as the lowest privilege rather
            # than crashing the request (defense in depth; the DB CHECK keeps
            # the column to the known set).
            rank = 0
        if rank < min_role.rank:
            raise HTTPException(
                403,
                detail={
                    "code": "insufficient_role",
                    "message": f"Requires {min_role.value} role or higher",
                    "doc_url": error_doc_url("insufficient_role"),
                },
            )
        return user

    return _check


# ---------------------------------------------------------------------------
# Org role (memberships.org_role) — the tenant-scoped authority axis
# ---------------------------------------------------------------------------


class OrgRole(str, Enum):
    viewer = "viewer"
    member = "member"
    admin = "admin"

    @property
    def rank(self) -> int:
        return {"viewer": 1, "member": 2, "admin": 3}[self.value]


class OrgAuthContext(BaseModel):
    """Resolved org-scoped identity handed to a route by ``require_org_role``.

    Carries the authenticated principal *plus* the org boundary the route must
    enforce. ``is_superadmin`` short-circuits the boundary (platform staff see
    all orgs); for a non-superadmin that cleared ``require_org_role`` both
    ``org_id`` and ``org_role`` are guaranteed non-null (they passed *because*
    they hold a qualifying membership).
    """

    user_id: int
    api_key_id: int
    key_prefix: str
    role: str  # platform role (users.role)
    is_superadmin: bool
    org_id: Optional[str] = None
    org_role: Optional[str] = None


def require_org_role(min_role: OrgRole):
    """Return a FastAPI dependency enforcing a minimum ORG role.

    Resolves the caller's primary membership (``lookup_org_membership`` — the
    raw-SQL authorization read in ``auth.models``, oldest membership wins) and
    checks its ``org_role`` rank against ``min_role``. A platform ``superadmin``
    bypasses the org check entirely and is admitted even with no membership.

    The returned ``OrgAuthContext`` gives the route both the decision *and* the
    org boundary (``org_id``) it needs to scope its reads/writes — this is the
    first place ``resolve_org``-style resolution is wired into a real consumer.
    """

    async def _check(user: AuthedUser = Depends(require_api_key)) -> OrgAuthContext:
        is_superadmin = user.role == Role.superadmin.value
        membership = await lookup_org_membership(user.user_id)
        # Bearer keys retain their issuing org. If the user's active membership
        # changed after authentication, fail this authorization check instead of
        # silently moving the key to the new organization.
        if user.org_id is not None and (
            membership is None or membership[0] != user.org_id
        ):
            membership = None
        org_id = membership[0] if membership else None
        org_role = membership[1] if membership else None

        if not is_superadmin:
            allowed = False
            if org_role is not None:
                try:
                    allowed = OrgRole(org_role).rank >= min_role.rank
                except ValueError:
                    allowed = False
            if not allowed:
                raise HTTPException(
                    403,
                    detail={
                        "code": "insufficient_org_role",
                        "message": (
                            f"Requires org {min_role.value} role or higher"
                        ),
                        "doc_url": (
                            error_doc_url("insufficient_org_role")
                        ),
                    },
                )

        return OrgAuthContext(
            user_id=user.user_id,
            api_key_id=user.api_key_id,
            key_prefix=user.key_prefix,
            role=user.role,
            is_superadmin=is_superadmin,
            org_id=org_id,
            org_role=org_role,
        )

    return _check


def require_role_and_org_role(min_role: Role, min_org_role: OrgRole):
    """Require both product capability and active-tenant mutation authority.

    Tenant-scoped mutation routes need both axes: a platform analyst who was
    demoted to org viewer must lose write access immediately, while a platform
    viewer who happens to administer an org still cannot use analyst features.
    Platform superadmins retain the explicit ``require_org_role`` bypass.
    """
    platform_gate = require_role(min_role)
    org_gate = require_org_role(min_org_role)

    async def _check(
        user: AuthedUser = Depends(platform_gate),
        _org: OrgAuthContext = Depends(org_gate),
    ) -> AuthedUser:
        return user

    return _check
