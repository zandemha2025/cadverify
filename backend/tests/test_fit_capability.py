"""GET /api/v1/validate/fit/capability: the access check the browser makes
before it sends (or previews) any file for Fit in context.

It must answer from the plan, the role and CONTEXT_FIT_ENABLED alone: no
upload, no preview mesh, no check reserved.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from src.auth import validation_caps
from src.auth.require_api_key import AuthedUser, require_api_key


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    import main
    importlib.reload(main)
    return TestClient(main.app)


def _pilot(monkeypatch):
    async def allow(user):
        return None
    monkeypatch.setattr(validation_caps, "require_paid_access", allow)


def _trial(monkeypatch):
    async def refuse(user):
        raise validation_caps.paid_access_required()
    monkeypatch.setattr(validation_caps, "require_paid_access", refuse)


def _no_reservations(monkeypatch):
    async def must_not_reserve(*args, **kwargs):
        raise AssertionError("The capability check reserved a check")
    monkeypatch.setattr(validation_caps, "reserve_check", must_not_reserve)


def test_pilot_with_the_setting_off_is_told_it_is_off(client, monkeypatch):
    monkeypatch.delenv("CONTEXT_FIT_ENABLED", raising=False)
    _pilot(monkeypatch)
    _no_reservations(monkeypatch)
    response = client.get("/api/v1/validate/fit/capability")
    assert response.status_code == 200, response.text
    assert response.json() == {"enabled": False, "paid_access": True, "can_submit": True, "available": False}


def test_pilot_with_the_setting_on_can_use_it(client, monkeypatch):
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    _pilot(monkeypatch)
    _no_reservations(monkeypatch)
    body = client.get("/api/v1/validate/fit/capability").json()
    assert body == {"enabled": True, "paid_access": True, "can_submit": True, "available": True}


def test_trial_account_gets_the_pilot_gate_not_a_403(client, monkeypatch):
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    _trial(monkeypatch)
    _no_reservations(monkeypatch)
    response = client.get("/api/v1/validate/fit/capability")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paid_access"] is False
    assert body["available"] is False
    assert body["enabled"] is True


def test_viewer_can_ask_but_not_submit(client, monkeypatch):
    import main
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    _pilot(monkeypatch)
    main.app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=1, api_key_id=1, key_prefix="k", role="viewer")
    body = client.get("/api/v1/validate/fit/capability").json()
    assert body["can_submit"] is False
    assert body["available"] is False
    assert body["paid_access"] is True


def test_an_unreadable_plan_is_an_error_not_a_gate(client, monkeypatch):
    async def down(user):
        raise validation_caps._unavailable()
    monkeypatch.setattr(validation_caps, "require_paid_access", down)
    response = client.get("/api/v1/validate/fit/capability")
    assert response.status_code == 503
    body = response.json()
    assert (body.get("detail") or body).get("code") == "allowance_unavailable", body


def test_the_fit_route_itself_still_refuses_while_off(client, monkeypatch, cube_10mm, stl_bytes_of):
    monkeypatch.delenv("CONTEXT_FIT_ENABLED", raising=False)
    data = stl_bytes_of(cube_10mm)
    response = client.post("/api/v1/validate/fit", files={
        "part_a": ("a.stl", data, "application/octet-stream"),
        "part_b": ("b.stl", data, "application/octet-stream"),
    })
    assert response.status_code == 404
