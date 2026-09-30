"""Bounded, authenticated product/BOM reads. No vendor writes or raw records stored."""
from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import date
from decimal import Decimal
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
    json_body: dict[str, Any] | None = None, cookies: httpx.Cookies | None = None,
) -> dict[str, Any]:
    # Pin the validated address for the connection. Re-resolving the hostname
    # inside HTTPX would allow DNS rebinding between validation and connection.
    try:
        addresses = await asyncio.to_thread(resolve_public_host, url.host)
    except UnsafeURLError as exc:
        raise ConnectorConnectionError("The service must resolve to public addresses; check its DNS and URL.") from exc
    host = url.netloc.decode("ascii")
    request_headers = {**headers, "Host": host, "Accept": "application/json", "Accept-Encoding": "identity"}
    if cookies is not None:
        # Cookie scope must use the actual HTTPS origin, not the pinned IP.
        cookie_request = httpx.Request("GET", url)
        cookies.set_cookie_header(cookie_request)
        if "cookie" in cookie_request.headers:
            request_headers["Cookie"] = cookie_request.headers["cookie"]
    # Try the vetted addresses only, preserving certificate verification and SNI.
    async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
        for index, address in enumerate(addresses):
            try:
                async with client.stream(
                    "POST" if data is not None or json_body is not None else "GET", url.copy_with(host=address),
                    headers=request_headers, data=data, json=json_body, extensions={"sni_hostname": url.host},
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
                    if cookies is not None:
                        cookies.extract_cookies(httpx.Response(
                            status, headers=response.headers, request=httpx.Request("GET", url),
                        ))
                    raw = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        raw.extend(chunk)
                        if len(raw) > _MAX_RESPONSE:
                            raise ConnectorConnectionError("The vendor response exceeds the 1 MB limit.")
                    try:
                        payload = json.loads(raw, parse_float=Decimal)
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


async def _auth_headers(auth_type: str, secret: dict[str, Any]) -> dict[str, str]:
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
    return headers


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
    headers = await _auth_headers(auth_type, secret)
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


async def read_windchill_bom(
    base_url: str, auth_type: str, secret: dict[str, Any], *,
    part_id: str, navigation_id: str | None = None,
) -> tuple[list[dict], int]:
    """Read a resolved part structure without expanding individual occurrences.

    Read-only PTC action; the nonce and its session cookie stay inside this call.
    Incomplete, paginated or non-count BOMs never become replacement rows.
    """
    from src.services.connector_adapters import windchill_bom_rows

    if not re.fullmatch(r"OR:wt\.part\.WTPart:[0-9]{1,30}", part_id):
        raise ConnectorConnectionError("Use an exact Windchill part iteration ID (OR:wt.part.WTPart:…).")
    if navigation_id is not None and not re.fullmatch(r"OR:wt\.filter\.NavigationCriteria:[0-9]{1,30}", navigation_id):
        raise ConnectorConnectionError("Use a saved Windchill navigation criteria ID.")
    url = _url(base_url)
    path = url.path.rstrip("/") or _PRODUCT_PATHS["windchill_part_bom_readonly"]
    if path.rsplit("/", 1)[-1] != "ProdMgmt":
        raise ConnectorConnectionError("Use the ProdMgmt service root URL.")
    common_path = re.sub(r"/v[0-9]+$", "", path.rsplit("/", 1)[0])
    cookies = httpx.Cookies()
    async with asyncio.timeout(30):
        headers = await _auth_headers(auth_type, secret)
        nonce = await _request_json(url.copy_with(path=f"{common_path}/PTC/GetCSRFToken()"), headers=headers, cookies=cookies)
        if nonce.get("NonceKey") != "CSRF_NONCE":
            raise ConnectorConnectionError("Windchill did not return the expected CSRF nonce.")
        token = _secret_text(nonce, "NonceValue")
        if not token.isascii():
            raise ConnectorConnectionError("Windchill returned an invalid CSRF nonce.")
        headers["CSRF_NONCE"] = token
        payload = await _request_json(url.copy_with(
            path=f"{path}/Parts('{part_id}')/PTC.ProdMgmt.GetPartStructure",
            params={"$expand": "Part($select=ID,Number,Name),Components($expand=Part($select=ID,Number,Name),PartUse($select=ID,Quantity,Unit);$levels=max)"},
        ), headers=headers, cookies=cookies,
            json_body={"NavigationCriteria": {"ID": navigation_id}} if navigation_id else {})
    try:
        return windchill_bom_rows(payload, part_id)
    except ValueError as exc:
        raise ConnectorConnectionError(str(exc)) from exc


async def read_sap_bom_preview(
    base_url: str, auth_type: str, secret: dict[str, Any], *, part_id: str, selection: dict[str, Any],
) -> tuple[list[dict], int]:
    """Read SAP v2 ExplodeBOM at a requested depth; never infer importable edges."""
    from src.services.connector_adapters import sap_bom_preview_rows

    params = {}
    for field, value, maximum, required in [
        ("Material", part_id, 40, True),
        ("BillOfMaterial", selection.get("bill_of_material"), 8, True),
        ("BillOfMaterialVariant", selection.get("variant"), 2, True),
        ("BillOfMaterialVersion", selection.get("version", ""), 4, False),
        ("EngineeringChangeDocument", selection.get("engineering_change_document", ""), 12, False),
        ("Plant", selection.get("plant"), 4, True),
        ("BOMExplosionApplication", selection.get("application"), 4, True),
    ]:
        if (not isinstance(value, str) or len(value) > maximum or (required and not value.strip())
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ConnectorConnectionError(f"Provide a valid SAP {field} selector (maximum {maximum} characters).")
        params[field] = "'" + value.replace("'", "''") + "'"
    try:
        effective_date = selection["explosion_date"]
        if not isinstance(effective_date, str) or date.fromisoformat(effective_date).isoformat() != effective_date:
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ConnectorConnectionError("Provide a SAP explosion date in YYYY-MM-DD format.") from exc
    level = selection.get("explosion_level")
    if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 99:
        raise ConnectorConnectionError("Choose a SAP preview depth between 1 and 99.")
    params.update({
        "BillOfMaterialCategory": "'M'", "BillOfMaterialItemCategory": "''", "BOMExplosionAssembly": "''",
        "BOMExplosionDate": f"datetime'{effective_date}T00:00:00'", "BOMExplosionIsLimited": "false",
        "BOMExplosionIsMultilevel": "true", "BOMExplosionLevel": f"{level}m", "RequiredQuantity": "1.000m",
        "BOMItmQtyIsScrapRelevant": "''", "MaterialProvisionFltrType": "' '", "SparePartFltrType": "' '", "$format": "json",
    })
    url = _url(base_url)
    product_path = _PRODUCT_PATHS["sap_s4hana_product_bom_readonly"]
    path = url.path.rstrip("/") or product_path
    if path.rsplit("/", 1)[-1].lower() != "api_product_srv":
        raise ConnectorConnectionError("Use the SAP host or API_PRODUCT_SRV service root; the BOM API uses the same service directory.")
    path = path.rsplit("/", 1)[0] + "/API_BILL_OF_MATERIAL_SRV;v=2/ExplodeBOM"
    async with asyncio.timeout(30):
        headers = await _auth_headers(auth_type, secret)
        payload = await _request_json(url.copy_with(path=path, params=params), headers=headers)
    try:
        return sap_bom_preview_rows(payload, part_id, selection)
    except ValueError as exc:
        raise ConnectorConnectionError(str(exc)) from exc
