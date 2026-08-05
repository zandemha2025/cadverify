"""Tests for RBAC — two authorization axes (W1 step 2).

PLATFORM axis (``require_role`` on ``users.role``): viewer < analyst < admin <
superadmin. Unchanged product-tier gate on the data routes; superadmin is the
new top rank and clears every ``require_role`` threshold.

ORG axis (``require_org_role`` on ``memberships.org_role``): viewer < member <
admin, scoped to the caller's own org. A platform superadmin bypasses the org
check entirely. The membership-resolution seam (``lookup_org_membership``) is
patched here so these stay pure unit tests; the end-to-end cross-tenant
isolation (org-admin can't see another org's users) is proven against real
Postgres in ``test_admin_org_rbac.py``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.auth.rbac import (
    OrgAuthContext,
    OrgRole,
    Role,
    require_org_role,
    require_role_and_org_role,
)
from src.auth.require_api_key import AuthedUser, require_api_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with_role(role: str) -> FastAPI:
    """App exercising the PLATFORM gate (``require_role``) on the data routes.

    Only the main router is mounted — the admin router now lives on the org gate
    and is covered by the org-role tests below.
    """
    from src.api.routes import router as main_router

    app = FastAPI()

    fake_user = AuthedUser(
        user_id=42, api_key_id=101, key_prefix="test_pfx", role=role,
    )
    app.dependency_overrides[require_api_key] = lambda: fake_user

    async def _fake_db():
        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = None
        exec_result.scalars.return_value.all.return_value = []
        exec_result.scalar_one_or_none.return_value = None
        exec_result.scalar_one.return_value = 0
        session.execute.return_value = exec_result
        yield session

    from src.db.engine import get_db_session

    app.dependency_overrides[get_db_session] = _fake_db

    from src.auth.kill_switch import require_kill_switch_open

    app.dependency_overrides[require_kill_switch_open] = lambda: None

    app.include_router(main_router, prefix="/api/v1")
    return app


def _org_gate_app(platform_role: str, min_role: OrgRole = OrgRole.admin) -> FastAPI:
    """Minimal app with a single route gated by ``require_org_role``.

    Returns the resolved ``OrgAuthContext`` so tests can assert both the
    admit/deny decision and the org boundary the dependency handed down.
    """
    app = FastAPI()
    dep = require_org_role(min_role)

    @app.get("/orgadmin")
    async def _protected(ctx: OrgAuthContext = Depends(dep)):  # noqa: ANN202
        return {
            "user_id": ctx.user_id,
            "role": ctx.role,
            "is_superadmin": ctx.is_superadmin,
            "org_id": ctx.org_id,
            "org_role": ctx.org_role,
        }

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=7, api_key_id=1, key_prefix="k", role=platform_role
    )
    return app


def _get_orgadmin(platform_role: str, membership):
    """Call the org-admin-gated route with a patched membership; return response."""
    app = _org_gate_app(platform_role)
    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "src.auth.rbac.lookup_org_membership",
        new=AsyncMock(return_value=membership),
    ):
        return client.get("/orgadmin")


# ---------------------------------------------------------------------------
# Platform axis — require_role on the data routes (unchanged behavior)
# ---------------------------------------------------------------------------


class TestViewerPlatformRole:
    def setup_method(self):
        self.client = TestClient(
            _make_app_with_role("viewer"), raise_server_exceptions=False
        )

    def test_viewer_can_read_processes(self):
        assert self.client.get("/api/v1/processes").status_code == 200

    def test_viewer_can_read_materials(self):
        assert self.client.get("/api/v1/materials").status_code == 200

    def test_viewer_cannot_trigger_analysis(self):
        resp = self.client.post(
            "/api/v1/validate",
            files={"file": ("cube.stl", b"dummy", "application/octet-stream")},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "insufficient_role"
        assert "analyst" in resp.json()["detail"]["message"]


class TestAnalystPlatformRole:
    def setup_method(self):
        self.client = TestClient(
            _make_app_with_role("analyst"), raise_server_exceptions=False
        )

    def test_analyst_can_read_processes(self):
        assert self.client.get("/api/v1/processes").status_code == 200

    def test_analyst_can_trigger_analysis(self):
        resp = self.client.post(
            "/api/v1/validate",
            files={"file": ("cube.stl", b"dummy", "application/octet-stream")},
        )
        # Past RBAC (bad-file 400 is fine); crucially NOT 403.
        assert resp.status_code != 403


class TestSuperadminPlatformRole:
    """Superadmin (rank 4) clears every require_role threshold."""

    def setup_method(self):
        self.client = TestClient(
            _make_app_with_role("superadmin"), raise_server_exceptions=False
        )

    def test_superadmin_can_read(self):
        assert self.client.get("/api/v1/processes").status_code == 200

    def test_superadmin_can_trigger_analysis(self):
        resp = self.client.post(
            "/api/v1/validate",
            files={"file": ("cube.stl", b"dummy", "application/octet-stream")},
        )
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Org axis — require_org_role
# ---------------------------------------------------------------------------


class TestRequireOrgRoleAdmin:
    """Matrix for a route gated at OrgRole.admin."""

    def test_org_admin_admitted_with_boundary(self):
        resp = _get_orgadmin("analyst", ("org-A", "admin"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_superadmin"] is False
        assert body["org_id"] == "org-A"
        assert body["org_role"] == "admin"

    def test_org_member_denied(self):
        resp = _get_orgadmin("analyst", ("org-A", "member"))
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "insufficient_org_role"

    def test_org_viewer_denied(self):
        resp = _get_orgadmin("analyst", ("org-A", "viewer"))
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "insufficient_org_role"

    def test_no_membership_denied(self):
        resp = _get_orgadmin("analyst", None)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "insufficient_org_role"

    def test_platform_admin_without_org_admin_denied(self):
        """Platform role 'admin' does NOT grant org-admin — only org_role does."""
        resp = _get_orgadmin("admin", ("org-A", "member"))
        assert resp.status_code == 403

    def test_superadmin_bypasses_without_membership(self):
        resp = _get_orgadmin("superadmin", None)
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_superadmin"] is True
        assert body["org_id"] is None
        assert body["org_role"] is None

    def test_superadmin_bypasses_with_low_membership(self):
        """A superadmin who happens to be an org 'viewer' is still admitted."""
        resp = _get_orgadmin("superadmin", ("org-Z", "viewer"))
        assert resp.status_code == 200
        assert resp.json()["is_superadmin"] is True


class TestRequireOrgRoleMember:
    """A route gated at OrgRole.member admits member and admin, not viewer."""

    def test_member_admitted(self):
        app = _org_gate_app("analyst", OrgRole.member)
        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "src.auth.rbac.lookup_org_membership",
            new=AsyncMock(return_value=("org-A", "member")),
        ):
            assert client.get("/orgadmin").status_code == 200

    def test_viewer_denied_at_member_gate(self):
        app = _org_gate_app("analyst", OrgRole.member)
        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "src.auth.rbac.lookup_org_membership",
            new=AsyncMock(return_value=("org-A", "viewer")),
        ):
            assert client.get("/orgadmin").status_code == 403


class TestRequirePlatformAndOrgRole:
    """Tenant mutations must clear both independent authorization axes."""

    @staticmethod
    def _response(platform_role: str, membership):
        app = FastAPI()
        dep = require_role_and_org_role(Role.analyst, OrgRole.member)

        @app.post("/mutate")
        async def _mutate(user: AuthedUser = Depends(dep)):  # noqa: ANN202
            return {"user_id": user.user_id}

        app.dependency_overrides[require_api_key] = lambda: AuthedUser(
            user_id=7,
            api_key_id=1,
            key_prefix="k",
            role=platform_role,
        )
        with patch(
            "src.auth.rbac.lookup_org_membership",
            new=AsyncMock(return_value=membership),
        ):
            return TestClient(app, raise_server_exceptions=False).post("/mutate")

    def test_analyst_member_admitted(self):
        assert self._response("analyst", ("org-A", "member")).status_code == 200

    def test_analyst_viewer_denied_immediately(self):
        response = self._response("analyst", ("org-A", "viewer"))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "insufficient_org_role"

    def test_platform_viewer_org_admin_still_denied(self):
        response = self._response("viewer", ("org-A", "admin"))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "insufficient_role"

    def test_superadmin_without_membership_retains_explicit_bypass(self):
        assert self._response("superadmin", None).status_code == 200


# ---------------------------------------------------------------------------
# Enum ranks
# ---------------------------------------------------------------------------


class TestRoleEnum:
    def test_platform_role_ranks(self):
        assert Role.viewer.rank == 1
        assert Role.analyst.rank == 2
        assert Role.admin.rank == 3
        assert Role.superadmin.rank == 4

    def test_platform_hierarchy(self):
        assert (
            Role.viewer.rank
            < Role.analyst.rank
            < Role.admin.rank
            < Role.superadmin.rank
        )

    def test_platform_values(self):
        assert Role.superadmin.value == "superadmin"

    def test_org_role_ranks(self):
        assert OrgRole.viewer.rank == 1
        assert OrgRole.member.rank == 2
        assert OrgRole.admin.rank == 3

    def test_org_hierarchy(self):
        assert OrgRole.viewer.rank < OrgRole.member.rank < OrgRole.admin.rank

    def test_axes_are_distinct(self):
        # 'analyst' is a platform-only value; 'member' is an org-only value.
        assert "analyst" not in {r.value for r in OrgRole}
        assert "member" not in {r.value for r in Role}
