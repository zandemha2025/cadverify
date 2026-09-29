"""Connection tests must cross the HTTP boundary without leaking credentials."""
from datetime import datetime, timezone
from ipaddress import ip_address

import httpx
import pytest
import base64

from src.db.models import ConnectorCredentialProfile
from src.services import connector_credentials_service as svc, url_guard

HTTP_CLIENT = httpx.AsyncClient

def profile(**changes):
    values = dict(
        ulid="01PROBE", connector_id="sap_s4hana_product_bom_readonly",
        base_url="https://sap.example", auth_type="bearer", revoked_at=None,
        encrypted_secret_json=svc.encrypt_secret({"token": "probe-secret"})[0],
        secret_fingerprint="fingerprint",
    )
    values.update(changes)
    return ConnectorCredentialProfile(**values)


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(url_guard, "_resolve_ips", lambda host: [ip_address("93.184.216.34")])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: HTTP_CLIENT(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
@pytest.mark.parametrize("connector,path,payload", [
    ("sap_s4hana_product_bom_readonly", "/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product", {"d": {"results": [{"Product": "P1"}]}}),
    ("windchill_part_bom_readonly", "/Windchill/servlet/odata/ProdMgmt/Parts", {"value": [{"Number": "P1"}]}),
])
async def test_probe_performs_authenticated_bounded_read(monkeypatch, connector, path, payload):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "93.184.216.34", "connect to the validated IP, not a second DNS answer"
        assert request.headers["host"] == "sap.example"
        assert request.extensions["sni_hostname"] == "sap.example"
        assert request.url.path == path
        assert request.url.params["$top"] == "1"
        assert request.headers["authorization"] == "Bearer probe-secret"
        return httpx.Response(200, json=payload)
    mock_http(monkeypatch, handle)
    result = await svc.probe_profile(profile(connector_id=connector))
    assert len(requests) == 1
    assert result["configured"] is True
    assert result["connected"] is True
    assert result["records_read"] == 1
    assert result["capability"] == "product_read"
    assert result["checked_at"]
    assert "probe-secret" not in str(result)
    assert "P1" not in str(result), "a probe must not return vendor records"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,reason", [
    (401, {"error": "probe-secret"}, "rejected"),
    (403, {}, "permission"),
    (404, {}, "endpoint"),
    (302, {}, "redirect"),
    (429, {}, "rate limit"),
    (503, {}, "unavailable"),
    (200, {"unexpected": True}, "OData"),
    (200, {"value": ["bad row"]}, "OData"),
])
async def test_unsuccessful_connection_is_never_reported_as_connected(monkeypatch, status, payload, reason):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=payload, headers={"location": "https://other.example/leak"})
    mock_http(monkeypatch, handle)
    result = await svc.probe_profile(profile())
    assert len(requests) == 1
    assert result["configured"] is True
    assert result["connected"] is False
    assert reason.lower() in result["reason"].lower()
    assert "probe-secret" not in str(result)


@pytest.mark.asyncio
async def test_revoked_profile_never_decrypts_or_connects(monkeypatch):
    row = profile(revoked_at=datetime.now(timezone.utc))
    monkeypatch.setattr(svc, "decrypt_secret", lambda _: pytest.fail("revoked credential decrypted"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("revoked credential sent"))
    result = await svc.probe_profile(row)
    assert result["connected"] is False
    assert result["configured"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("ips", [["127.0.0.1"], ["93.184.216.34", "10.0.0.1"], ["169.254.169.254"], ["::ffff:127.0.0.1"]])
async def test_private_dns_answers_block_egress_even_with_webhook_switch_off(monkeypatch, ips):
    monkeypatch.setenv("WEBHOOK_SSRF_GUARD_ENABLED", "0")
    monkeypatch.setattr(url_guard, "_resolve_ips", lambda host: [ip_address(ip) for ip in ips])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("unsafe egress"))
    result = await svc.probe_profile(profile())
    assert result["connected"] is False
    assert "public" in result["reason"]


@pytest.mark.asyncio
async def test_probe_caps_response_and_hides_transport_errors(monkeypatch):
    mock_http(monkeypatch, lambda req: httpx.Response(200, content=b"x" * (1024 * 1024 + 1)))
    result = await svc.probe_profile(profile())
    assert result["connected"] is False
    assert "limit" in result["reason"]
    def timeout(req):
        raise httpx.ReadTimeout("probe-secret", request=req)
    mock_http(monkeypatch, timeout)
    result = await svc.probe_profile(profile())
    assert result["connected"] is False
    assert "probe-secret" not in str(result)


@pytest.mark.asyncio
async def test_oauth_token_endpoint_is_checked_and_token_stays_server_side(monkeypatch):
    secret = {"client_id": "client", "client_secret": "client-secret", "token_url": "https://login.example/token"}
    row = profile(auth_type="oauth2_client_credentials", encrypted_secret_json=svc.encrypt_secret(secret)[0])
    requests = []
    def handle(req):
        requests.append(req)
        if req.url.path == "/token":
            assert req.method == "POST"
            assert req.headers["host"] == "login.example"
            assert "grant_type=client_credentials" in req.content.decode()
            return httpx.Response(200, json={"access_token": "oauth-secret", "token_type": "Bearer"})
        assert req.method == "GET"
        assert req.headers["authorization"] == "Bearer oauth-secret"
        return httpx.Response(200, json={"d": {"results": []}})
    mock_http(monkeypatch, handle)
    result = await svc.probe_profile(row)
    assert len(requests) == 2
    assert result["connected"] is True
    assert result["records_read"] == 0
    assert "secret" not in str({k: v for k, v in result.items() if not k.startswith("secret_")})


@pytest.mark.asyncio
@pytest.mark.parametrize("auth,secret,header,value", [
    ("basic", {"username": "üser", "password": "päss"}, "authorization", "Basic " + base64.b64encode("üser:päss".encode()).decode()),
    ("api_key", {"header_name": "APIKey", "api_key": "key-sentinel"}, "apikey", "key-sentinel"),
])
async def test_other_auth_modes_use_headers_only(monkeypatch, auth, secret, header, value):
    def handle(req):
        assert req.headers[header] == value
        assert value not in str(req.url)
        return httpx.Response(200, json={"d": {"results": []}})
    mock_http(monkeypatch, handle)
    result = await svc.probe_profile(profile(auth_type=auth, encrypted_secret_json=svc.encrypt_secret(secret)[0]))
    assert result["connected"] is True
    assert value not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", [
    {"header_name": "Host", "api_key": "key-sentinel"},
    {"header_name": "X-API-Key", "api_key": "key-sentinel\r\nHost: other"},
    {"query_param": "key", "api_key": "key-sentinel"},
])
async def test_invalid_auth_cannot_override_routing_or_leak_in_urls(monkeypatch, secret):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("unsafe credential sent"))
    result = await svc.probe_profile(profile(auth_type="api_key", encrypted_secret_json=svc.encrypt_secret(secret)[0]))
    assert result["connected"] is False
    assert "key-sentinel" not in str(result)


@pytest.mark.asyncio
async def test_oauth_private_token_url_is_rejected_before_sending_client_secret(monkeypatch):
    secret = {"client_id": "client", "client_secret": "private-secret", "token_url": "https://169.254.169.254/token"}
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("token request leaked"))
    result = await svc.probe_profile(profile(auth_type="oauth2_client_credentials", encrypted_secret_json=svc.encrypt_secret(secret)[0]))
    assert result["connected"] is False
    assert "public" in result["reason"]
    assert "private-secret" not in str(result)
