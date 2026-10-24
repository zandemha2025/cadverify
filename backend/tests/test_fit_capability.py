"""GET /api/v1/validate/fit/capability: the access check the browser makes
before it sends (or previews) any file for Fit in context.

It answers from the role and CONTEXT_FIT_ENABLED alone (Fit in context is on
every plan): no upload, no preview mesh, no check reserved.
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


def _no_plan_reads(monkeypatch):
    """Fit in context is on every plan: the probe never reads the plan."""
    async def must_not_read(*args, **kwargs):
        raise AssertionError("The capability check read the plan")
    monkeypatch.setattr(validation_caps, "require_paid_access", must_not_read)
    monkeypatch.setattr(validation_caps, "effective_plan", must_not_read)


def _no_reservations(monkeypatch):
    async def must_not_reserve(*args, **kwargs):
        raise AssertionError("The capability check reserved a check")
    monkeypatch.setattr(validation_caps, "reserve_check", must_not_reserve)


def test_with_the_setting_off_it_is_off(client, monkeypatch):
    monkeypatch.delenv("CONTEXT_FIT_ENABLED", raising=False)
    _no_plan_reads(monkeypatch)
    _no_reservations(monkeypatch)
    response = client.get("/api/v1/validate/fit/capability")
    assert response.status_code == 200, response.text
    assert response.json() == {"enabled": False, "paid_access": True, "can_submit": True, "available": False}


def test_any_plan_with_the_setting_on_can_use_it(client, monkeypatch):
    """A free trial account included: paid_access stays true for older clients."""
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    _no_plan_reads(monkeypatch)
    _no_reservations(monkeypatch)
    body = client.get("/api/v1/validate/fit/capability").json()
    assert body == {"enabled": True, "paid_access": True, "can_submit": True, "available": True}


def test_viewer_can_ask_but_not_submit(client, monkeypatch):
    import main
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    _no_plan_reads(monkeypatch)
    main.app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=1, api_key_id=1, key_prefix="k", role="viewer")
    body = client.get("/api/v1/validate/fit/capability").json()
    assert body["can_submit"] is False
    assert body["available"] is False
    assert body["paid_access"] is True


def test_the_fit_route_itself_still_refuses_while_off(client, monkeypatch, cube_10mm, stl_bytes_of):
    monkeypatch.delenv("CONTEXT_FIT_ENABLED", raising=False)
    data = stl_bytes_of(cube_10mm)
    response = client.post("/api/v1/validate/fit", files={
        "part_a": ("a.stl", data, "application/octet-stream"),
        "part_b": ("b.stl", data, "application/octet-stream"),
    })
    assert response.status_code == 404
