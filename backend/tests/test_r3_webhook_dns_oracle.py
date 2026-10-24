"""Security review R3, F5: a refused webhook URL never says what its host resolved to.

POST /api/v1/batch answered a refused webhook_url with f"webhook_url rejected:
{exc}", and the guard's message named the private address the host resolved
to (or said the host didn't resolve): an oracle for the internal DNS. The
answer is now one fixed clause for both; the detail goes to the server log.
"""
from __future__ import annotations

import io
import logging
import socket
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.services import url_guard
from src.services.url_guard import UnsafeURLError, validate_outbound_url


def test_refusal_text_does_not_name_the_resolved_address():
    try:
        validate_outbound_url("http://localhost:8080/hook")
    except UnsafeURLError as exc:
        shown = f"webhook_url rejected: {exc}"  # what the route returned
    else:
        raise AssertionError("localhost was accepted")
    assert "127.0.0.1" not in shown and "::1" not in shown, shown


def _refusal(url: str, monkeypatch, resolves_to: list[str] | None) -> UnsafeURLError:
    def fake_getaddrinfo(host, *_a, **_k):
        if resolves_to is None:
            raise socket.gaierror("Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in resolves_to]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError) as info:
        validate_outbound_url(url)
    return info.value


def test_a_private_name_and_a_missing_name_get_the_same_answer(monkeypatch):
    private = _refusal("https://db.internal/hook", monkeypatch, ["10.1.2.3"])
    missing = _refusal("https://nope.internal/hook", monkeypatch, None)
    assert str(private) == str(missing) == url_guard.NOT_PUBLIC
    # The facts are kept for the server log only.
    assert "10.1.2.3" in private.detail and "does not resolve" in missing.detail


def _batch_app() -> FastAPI:
    from src.api.batch_router import router
    from src.auth.rbac import require_org_writer
    from src.auth.require_api_key import AuthedUser
    from src.auth.validation_caps import require_paid_access
    from src.db.engine import get_db_session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_paid_access] = lambda: None
    app.dependency_overrides[require_org_writer] = lambda: AuthedUser(
        user_id=1, api_key_id=1, key_prefix="cv_live_test", role="analyst", org_id="org1")
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    return app


@pytest.mark.parametrize("hook, address", [("http://127.0.0.1:8080/hook", "127.0.0.1"), ("http://[::1]/hook", "::1"),
                                           ("http://169.254.169.254/x", "169.254.169.254")])
def test_the_batch_route_answers_with_the_fixed_clause_and_logs_the_detail(hook, address, caplog):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("part.stl", b"solid test\nendsolid test")
    buf.seek(0)
    with patch("src.api.batch_router.batch_service"), caplog.at_level(logging.INFO, "cadverify.batch_router"):
        resp = TestClient(_batch_app()).post(
            "/api/v1/batch", files={"file": ("test.zip", buf, "application/zip")},
            data={"webhook_url": hook, "webhook_secret": "local-test-only-signing-sentinel"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "webhook_url_rejected"
    assert detail["message"] == ("This address can't receive webhooks: "
                                 "it doesn't resolve to a public internet address.")
    assert address not in resp.text
    assert any(address in r.getMessage() for r in caplog.records)


def test_a_wrong_scheme_still_says_what_to_fix():
    with pytest.raises(UnsafeURLError) as info:
        validate_outbound_url("ftp://example.com/hook")
    assert str(info.value) == "it must start with http:// or https://"
