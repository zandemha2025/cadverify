"""Focused HTTP probes for read-only mutation boundaries.

The UI hides these controls, but the backend remains the security boundary. A
platform viewer (the product's auditor/read-only persona) and any unknown role
must be rejected before a mutation service is called.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import cost_decisions, designs, rfq_packages
from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session


def _app(role: str) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(cost_decisions.router, prefix="/api/v1/cost-decisions")
    app.include_router(rfq_packages.router, prefix="/api/v1/rfq-packages")
    app.include_router(designs.router, prefix="/api/v1/designs")

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=7,
        api_key_id=0,
        key_prefix="session",
        role=role,
        org_id="org-a",
    )
    app.dependency_overrides[require_kill_switch_open] = lambda: None

    async def _session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _session
    return app


@pytest.mark.parametrize("role", ["viewer", "auditor"])
def test_read_only_roles_cannot_mutate_cost_rfq_or_design_surfaces(role, monkeypatch):
    blocked_services = [
        (cost_decisions.svc, "set_disposition_owned"),
        (cost_decisions.svc, "approve_owned"),
        (cost_decisions.svc, "reopen_owned"),
        (cost_decisions.svc, "create_share"),
        (cost_decisions.svc, "revoke_share"),
        (rfq_packages.svc, "create_package"),
        (designs.svc, "create_design"),
        (designs.svc, "create_revision"),
        (designs.svc, "archive_design"),
    ]
    mocks = []
    for module, name in blocked_services:
        mocked = AsyncMock()
        monkeypatch.setattr(module, name, mocked)
        mocks.append(mocked)

    requests = [
        ("PUT", "/api/v1/cost-decisions/decision-1/disposition", {"disposition": "outside"}),
        ("POST", "/api/v1/cost-decisions/decision-1/approve", {"note": "no"}),
        ("DELETE", "/api/v1/cost-decisions/decision-1/approve", None),
        ("POST", "/api/v1/cost-decisions/decision-1/share", None),
        ("DELETE", "/api/v1/cost-decisions/decision-1/share", None),
        ("POST", "/api/v1/rfq-packages", {"decision_ids": ["decision-1"]}),
        (
            "POST",
            "/api/v1/designs",
            {
                "name": "Plate",
                "plan": {
                    "kind": "plate",
                    "width_mm": 80,
                    "depth_mm": 50,
                    "thickness_mm": 6,
                    "holes": [],
                },
            },
        ),
        ("POST", "/api/v1/designs/interpret", {"prompt": "80 x 50 x 6 mm plate"}),
        (
            "POST",
            "/api/v1/designs/design-1/revisions",
            {
                "plan": {
                    "kind": "plate",
                    "width_mm": 90,
                    "depth_mm": 50,
                    "thickness_mm": 6,
                    "holes": [],
                }
            },
        ),
        ("DELETE", "/api/v1/designs/design-1", None),
    ]

    with patch(
        "src.auth.rbac.lookup_org_membership",
        new=AsyncMock(return_value=("org-a", "viewer")),
    ):
        client = TestClient(_app(role), raise_server_exceptions=False)
        for method, path, body in requests:
            response = client.request(method, path, json=body)
            assert response.status_code == 403, (role, method, path, response.text)
            assert response.json()["detail"]["code"] in {
                "insufficient_role",
                "insufficient_org_role",
            }

    for mocked in mocks:
        mocked.assert_not_awaited()
