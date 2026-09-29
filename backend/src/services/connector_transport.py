"""Bounded, authenticated product-read probes. No vendor writes or raw records stored."""
from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Any

import httpx

from src.services.url_guard import UnsafeURLError, resolve_public_host

_MAX_RESPONSE = 1024 * 1024
_PRODUCT_PATHS = {
    "sap_s4hana_product_bom_readonly": "/sap/opu/odata/sap/API_PRODUCT_SRV",
    "windchill_part_bom_readonly": "/Windchill/servlet/odata/ProdMgmt",
}


class ConnectorConnectionError(ValueError):
    """Safe, actionable error text; never contains a URL, response body or credential."""


def _url(value: str) -> httpx.URL:
    try:
        url = httpx.URL(value)
        if (url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment
                or any(c.isspace() or c == "\\" for c in value)):
            raise ValueError
        return url
    except (ValueError, httpx.InvalidURL) as exc:
        raise ConnectorConnectionError("Use an HTTPS service URL without credentials, query or fragment.") from exc


def _secret_text(secret: dict[str, Any], field: str) -> str:
    value = secret.get(field)
    if (not isinstance(value, str) or not value.strip() or len(value) > 8192
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or (field in {"token", "access_token", "header_name", "api_key"} and not value.isascii())):
        raise ConnectorConnectionError(f"The credential field {field} is missing or invalid.")
    return value


def _basic(user: str, password: str) -> str:
    if ":" in user:
        raise ConnectorConnectionError("Basic authentication usernames cannot contain a colon.")
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


async def _request_json(
    url: httpx.URL, *, headers: dict[str, str], data: dict[str, str] | None = None,
) -> dict[str, Any]:
    # Pin the validated address for the connection. Re-resolving the hostname
    # inside HTTPX would allow DNS rebinding between validation and connection.
    try:
        addresses = await asyncio.to_thread(resolve_public_host, url.host)
    except UnsafeURLError as exc:
        raise ConnectorConnectionError("The service must resolve to public addresses; check its DNS and URL.") from exc
    host = url.netloc.decode("ascii")
    request_headers = {**headers, "Host": host, "Accept": "application/json", "Accept-Encoding": "identity"}
    # Try the vetted addresses only, preserving certificate verification and SNI.
    async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
        for index, address in enumerate(addresses):
            try:
                async with client.stream(
                    "POST" if data is not None else "GET", url.copy_with(host=address),
                    headers=request_headers, data=data, extensions={"sni_hostname": url.host},
                ) as response:
                    status = response.status_code
                    if status != 200:
                        reason = {
                            401: "Credentials were rejected. Update the credential profile.",
                            403: "The account lacks permission to read this API.",
                            404: "The API endpoint was not found. Check the service URL and API activation.",
                            429: "The vendor rate limit was reached. Try again later.",
                        }.get(status)
                        if 300 <= status < 400:
                            reason = "The service returned a redirect. Enter the final API URL; credentials were not forwarded."
                        raise ConnectorConnectionError(reason or f"The vendor service is unavailable (HTTP {status}).")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        raw.extend(chunk)
                        if len(raw) > _MAX_RESPONSE:
                            raise ConnectorConnectionError("The probe response exceeds the 1 MB limit.")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError, RecursionError) as exc:
                        raise ConnectorConnectionError("The endpoint did not return valid JSON. Check the API URL.") from exc
                    if not isinstance(payload, dict):
                        raise ConnectorConnectionError("The endpoint did not return a JSON object.")
                    return payload
            except httpx.ConnectError as exc:
                if index == len(addresses) - 1:
                    raise ConnectorConnectionError("Could not connect securely. Check the service address and TLS certificate.") from exc
            except httpx.HTTPError as exc:
                raise ConnectorConnectionError("The vendor request failed or timed out. Check availability and try again.") from exc
    raise ConnectorConnectionError("The service has no public address.")


async def probe_product_api(connector_id: str, base_url: str, auth_type: str, secret: dict[str, Any]) -> int:
    """Read at most one product; return only its count, never raw vendor data.

    SAP: API_PRODUCT_SRV/A_Product (OData v2). Windchill: ProdMgmt/Parts
    (OData v4). This establishes product-read access, not BOM import proof.
    """
    url = _url(base_url)
    service_path = _PRODUCT_PATHS.get(connector_id)
    if service_path is None:
        raise ConnectorConnectionError("This connector has no product-read endpoint.")
    path = url.path.rstrip("/") or service_path
    if path.rsplit("/", 1)[-1].lower() != service_path.rsplit("/", 1)[-1].lower():
        raise ConnectorConnectionError(f"Use the {service_path.rsplit('/', 1)[-1]} service root URL.")
    headers: dict[str, str] = {}
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {_secret_text(secret, 'token')}"
    elif auth_type == "basic":
        headers["Authorization"] = _basic(_secret_text(secret, "username"), _secret_text(secret, "password"))
    elif auth_type == "api_key":
        name = _secret_text(secret, "header_name")
        if (secret.get("query_param") or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", name)
                or name.lower() in {"host", "authorization", "cookie", "connection", "content-length", "content-type", "transfer-encoding", "accept", "accept-encoding"}):
            raise ConnectorConnectionError("Use a dedicated API-key header, such as APIKey or X-API-Key; query keys are not supported.")
        headers[name] = _secret_text(secret, "api_key")
    elif auth_type == "oauth2_client_credentials":
        token_url = _url(_secret_text(secret, "token_url"))
        data = {"grant_type": "client_credentials"}
        if secret.get("scope"):
            data["scope"] = _secret_text(secret, "scope")
        token_payload = await _request_json(token_url, headers={
            "Authorization": _basic(_secret_text(secret, "client_id"), _secret_text(secret, "client_secret")),
        }, data=data)
        if str(token_payload.get("token_type", "")).lower() != "bearer":
            raise ConnectorConnectionError("The token endpoint did not return a Bearer token.")
        headers["Authorization"] = f"Bearer {_secret_text(token_payload, 'access_token')}"
    else:
        raise ConnectorConnectionError("Unsupported authentication type.")
    entity = "A_Product" if connector_id.startswith("sap_") else "Parts"
    field = "Product" if entity == "A_Product" else "Number"
    url = url.copy_with(path=f"{path}/{entity}", params={"$top": "1", "$select": field, "$format": "json"})
    payload = await _request_json(url, headers=headers)
    rows = payload.get("value")
    if rows is None and isinstance(payload.get("d"), dict):
        rows = payload["d"].get("results")
    if (not isinstance(rows, list) or len(rows) > 1
            or any(not isinstance(row, dict) or not isinstance(row.get(field), str) or not row[field].strip() for row in rows)):
        raise ConnectorConnectionError("The endpoint did not return the expected OData product collection.")
    return len(rows)
