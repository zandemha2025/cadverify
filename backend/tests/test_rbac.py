"""Tests for RBAC middleware and permission matrix.

Verifies:
  - viewer can read but not write
  - analyst can read + write but not admin
  - admin can do everything including user management
  - admin cannot demote self
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key


# ---------------------------------------------------------------------------
# Helpers: build a minimal test app with role-gated routes
# ---------------------------------------------------------------------------


def _make_app_with_role(role: str) -> FastAPI:
    """Create a FastAPI app with dependency override for a user with given role."""
    from src.api.admin_routes import router as admin_router
    from src.api.routes import router as main_router

    app = FastAPI()

    fake_user = AuthedUser(
        user_id=42, api_key_id=101, key_prefix="test_pfx", role=role,
    )

    def _override():
        return fake_user

    app.dependency_overrides[require_api_key] = _override

    # Mock DB session
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

    # Disable kill switch for testing
    from src.auth.kill_switch import require_kill_switch_open

    app.dependency_overrides[require_kill_switch_open] = lambda: None

    app.include_router(main_router, prefix="/api/v1")
    app.include_router(admin_router)

    return app


# ---------------------------------------------------------------------------
# Viewer tests
# ---------------------------------------------------------------------------


class TestViewerRole:
    """Viewer (rank 1) can read but cannot trigger analysis or manage users."""

    def setup_method(self):
        self.app = _make_app_with_role("viewer")
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_viewer_can_read_processes(self):
        """Viewer can GET read-only endpoints."""
        resp = self.client.get("/api/v1/processes")
        assert resp.status_code == 200

    def test_viewer_can_read_materials(self):
        resp = self.client.get("/api/v1/materials")
        assert resp.status_code == 200

    def test_viewer_cannot_trigger_analysis(self):
        """Viewer POSTing /validate gets 403 insufficient_role."""
        resp = self.client.post(
            "/api/v1/validate",
            files={"file": ("cube.stl", b"dummy", "application/octet-stream")},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"]["code"] == "insufficient_role"
        assert "analyst" in body["detail"]["message"]

    def test_viewer_cannot_trigger_repair(self):
        resp = self.client.post(
            "/api/v1/validate/repair",
            files={"file": ("cube.stl", b"dummy", "application/octet-stream")},
        )
        assert resp.status_code == 403

    def test_viewer_cannot_manage_users(self):
        """Viewer GETting /admin/users gets 403."""
        resp = self.client.get("/api/v1/admin/users")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Analyst tests
# ---------------------------------------------------------------------------


class TestAnalystRole:
    """Analyst (rank 2) can read + write but cannot access admin endpoints."""

    def setup_method(self):
        self.app = _make_app_with_role("analyst")
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_analyst_can_read_processes(self):
        resp = self.client.get("/api/v1/processes")
        assert resp.status_code == 200

    def test_analyst_can_trigger_analysis(self):
        """Analyst POSTing /validate gets past RBAC (may get 400 for bad file, not 403)."""
        resp = self.client.post(
            "/api/v1/validate",
            files={"file": ("cube.stl", b"dummy", "application/octet-stream")},
        )
        # Should NOT be 403 -- 400 is expected (bad file content)
        assert resp.status_code != 403

    def test_analyst_cannot_manage_users(self):
        """Analyst GETting /admin/users gets 403."""
        resp = self.client.get("/api/v1/admin/users")
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "insufficient_role"

    def test_analyst_cannot_change_roles(self):
        resp = self.client.patch(
            "/api/v1/admin/users/99/role",
            json={"role": "admin"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin tests
# ---------------------------------------------------------------------------


class TestAdminRole:
    """Admin (rank 3) has full access."""

    def setup_method(self):
        self.app = _make_app_with_role("admin")
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_admin_can_read_processes(self):
        resp = self.client.get("/api/v1/processes")
        assert resp.status_code == 200

    def test_admin_can_list_users(self):
        """Admin GETting /admin/users gets 200."""
        resp = self.client.get("/api/v1/admin/users")
        assert resp.status_code == 200
        body = resp.json()
        assert "users" in body
        assert "has_more" in body

    def test_admin_can_get_user_detail(self):
        """Admin can GET user detail (returns 404 for non-existent user in mock)."""
        resp = self.client.get("/api/v1/admin/users/99")
        # 404 because mock session returns None for user lookup
        assert resp.status_code == 404

    def test_admin_can_change_role(self):
        """Admin can PATCH another user's role (returns 404 in mock since no real DB)."""
        resp = self.client.patch(
            "/api/v1/admin/users/99/role",
            json={"role": "analyst"},
        )
        # 404 because mock session returns None for user lookup -- NOT 403
        assert resp.status_code == 404

    def test_admin_cannot_demote_self(self):
        """Admin PATCHing own user ID gets 400."""
        resp = self.client.patch(
            "/api/v1/admin/users/42/role",  # user_id=42 matches fake admin user
            json={"role": "viewer"},
        )
        assert resp.status_code == 400
        assert "Cannot change own role" in resp.json()["detail"]

    def test_admin_invalid_role_rejected(self):
        """PATCH with invalid role value returns 400."""
        resp = self.client.patch(
            "/api/v1/admin/users/99/role",
            json={"role": "superadmin"},
        )
        # Could be 400 (invalid role) or 404 (user not found) depending on order
        # The role validation happens after user lookup in our implementation,
        # but self-demotion check happens first. For a different user, we check
        # role validity before DB lookup.
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Role enum tests
# ---------------------------------------------------------------------------


class TestRoleEnum:
    """Test Role enum ranking."""

    def test_role_ranks(self):
        assert Role.viewer.rank == 1
        assert Role.analyst.rank == 2
        assert Role.admin.rank == 3

    def test_role_hierarchy(self):
        assert Role.viewer.rank < Role.analyst.rank < Role.admin.rank

    def test_role_string_values(self):
        assert Role.viewer.value == "viewer"
        assert Role.analyst.value == "analyst"
        assert Role.admin.value == "admin"
