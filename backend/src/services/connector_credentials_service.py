"""Encrypted connector credential profiles for enterprise integrations."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import ConnectorCredentialProfile, IntegrationRun
from src.services.connector_adapters import (
    ConnectorAdapterSettings,
    SapS4ProductBomReadOnlyAdapter,
    WindchillPartBomReadOnlyAdapter,
)
from src.services.integration_service import get_connector
from src.services.connector_transport import ConnectorConnectionError, probe_product_api, read_sap_bom_preview, read_windchill_bom

AUTH_TYPES = {"bearer", "basic", "oauth2_client_credentials", "api_key"}
FINGERPRINT_ALGORITHM = "hmac_sha256"
_DEV_CONNECTOR_SECRET = base64.urlsafe_b64encode(
    hashlib.sha256(b"cadverify-dev-only-connector-secret-key").digest()
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _production_like() -> bool:
    return bool(os.getenv("RELEASE") or os.getenv("FLY_APP_NAME") or os.getenv("ENV") == "production")


def _connector_secret_key() -> bytes:
    raw = os.getenv("CONNECTOR_SECRET_KEY")
    if raw:
        key = raw.encode("utf-8")
    elif _production_like():
        raise RuntimeError("CONNECTOR_SECRET_KEY is required for connector credentials")
    else:
        key = _DEV_CONNECTOR_SECRET
    try:
        Fernet(key)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("CONNECTOR_SECRET_KEY must be a valid Fernet key") from exc
    return key


def _fernet() -> Fernet:
    return Fernet(_connector_secret_key())


def _fingerprint_key() -> bytes:
    raw = os.getenv("CONNECTOR_FINGERPRINT_KEY")
    if raw:
        return raw.encode("utf-8")
    return _connector_secret_key()


def _canonical_secret(secret: dict[str, Any]) -> str:
    return json.dumps(secret, sort_keys=True, separators=(",", ":"))


def _fingerprint_secret(canonical: str) -> str:
    return hmac.new(
        _fingerprint_key(),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def encrypt_secret(secret: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(secret, dict) or not secret:
        raise HTTPException(status_code=400, detail="connector secret must be a non-empty object")
    canonical = _canonical_secret(secret)
    try:
        fingerprint = _fingerprint_secret(canonical)
        token = _fernet().encrypt(canonical.encode("utf-8")).decode("utf-8")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Connector credential storage is not configured. Ask the workspace operator to enable it.") from exc
    return token, fingerprint


def decrypt_secret(encrypted: str) -> dict[str, Any]:
    try:
        raw = _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
        payload = json.loads(raw)
    except (InvalidToken, json.JSONDecodeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail="connector credential cannot be decrypted") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="connector credential payload is invalid")
    return payload


def _clean_text(value: str | None, field: str, *, max_len: int = 300) -> str:
    clean = (value or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    if len(clean) > max_len:
        raise HTTPException(status_code=400, detail=f"{field} is too long")
    return clean


def _clean_base_url(value: str | None) -> str:
    clean = _clean_text(value, "base_url", max_len=500).rstrip("/")
    try:
        parsed = urlparse(clean)
        parsed.port  # Validate a malformed or out-of-range port before saving.
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="base_url is not a valid URL") from exc
    if not parsed.scheme or not parsed.hostname:
        raise HTTPException(status_code=400, detail="base_url must be an absolute URL")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="base_url must not contain credentials")
    if parsed.query or parsed.fragment or "\\" in clean or any(c.isspace() for c in clean):
        raise HTTPException(status_code=400, detail="base_url must not contain a query, fragment, whitespace or backslash")
    hostname = (parsed.hostname or "").lower()
    local_http = parsed.scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (local_http and not _production_like()):
        raise HTTPException(status_code=400, detail="base_url must use https")
    return clean


def _require_secret_text(secret: dict[str, Any], field: str, auth_type: str) -> None:
    value = secret.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=400,
            detail=f"{auth_type} connector secret requires {field}",
        )


def _validate_secret(auth_type: str, secret: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(secret, dict) or not secret:
        raise HTTPException(status_code=400, detail="connector secret must be a non-empty object")
    if auth_type == "bearer":
        _require_secret_text(secret, "token", auth_type)
    elif auth_type == "basic":
        _require_secret_text(secret, "username", auth_type)
        _require_secret_text(secret, "password", auth_type)
    elif auth_type == "oauth2_client_credentials":
        _require_secret_text(secret, "client_id", auth_type)
        _require_secret_text(secret, "client_secret", auth_type)
        _require_secret_text(secret, "token_url", auth_type)
    elif auth_type == "api_key":
        _require_secret_text(secret, "api_key", auth_type)
        has_location = bool(str(secret.get("header_name") or "").strip()) or bool(
            str(secret.get("query_param") or "").strip()
        )
        if not has_location:
            raise HTTPException(
                status_code=400,
                detail="api_key connector secret requires header_name or query_param",
            )
    else:
        raise HTTPException(status_code=400, detail="unsupported connector auth_type")
    return secret


async def create_profile(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: int | None,
    connector_id: str,
    label: str,
    base_url: str,
    auth_type: str,
    secret: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> ConnectorCredentialProfile:
    connector = get_connector(connector_id)
    if not connector.live_credentials_required:
        raise HTTPException(
            status_code=400,
            detail="credential profiles are only valid for credential-required connectors",
        )
    clean_auth_type = _clean_text(auth_type, "auth_type", max_len=80)
    if clean_auth_type not in AUTH_TYPES:
        raise HTTPException(status_code=400, detail="unsupported connector auth_type")
    validated_secret = _validate_secret(clean_auth_type, secret)
    encrypted, fingerprint = encrypt_secret(validated_secret)
    profile = ConnectorCredentialProfile(
        ulid=str(ULID()),
        org_id=org_id,
        connector_id=connector.id,
        label=_clean_text(label, "label", max_len=120),
        base_url=_clean_base_url(base_url),
        auth_type=clean_auth_type,
        encrypted_secret_json=encrypted,
        secret_fingerprint=fingerprint,
        created_by=user_id,
        metadata_json=metadata or {},
    )
    session.add(profile)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="connector credential profile label already exists for this connector",
        ) from exc
    return profile


async def list_profiles(
    session: AsyncSession,
    *,
    org_id: str,
    connector_id: str | None = None,
) -> list[ConnectorCredentialProfile]:
    stmt = select(ConnectorCredentialProfile).where(
        ConnectorCredentialProfile.org_id == org_id
    )
    if connector_id:
        stmt = stmt.where(ConnectorCredentialProfile.connector_id == connector_id)
    stmt = stmt.order_by(
        ConnectorCredentialProfile.created_at.desc(),
        ConnectorCredentialProfile.id.desc(),
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_profile(
    session: AsyncSession,
    *,
    org_id: str,
    profile_id: str,
) -> ConnectorCredentialProfile:
    row = (
        await session.execute(
            select(ConnectorCredentialProfile).where(
                ConnectorCredentialProfile.org_id == org_id,
                ConnectorCredentialProfile.ulid == profile_id,
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="connector credential profile not found")
    return row


async def revoke_profile(
    session: AsyncSession,
    *,
    org_id: str,
    profile_id: str,
) -> ConnectorCredentialProfile:
    profile = await get_profile(session, org_id=org_id, profile_id=profile_id)
    if profile.revoked_at is None:
        profile.revoked_at = _now()
        await session.flush()
        await session.refresh(profile)
    return profile


def serialize_profile(row: ConnectorCredentialProfile) -> dict[str, Any]:
    return {
        "id": row.ulid,
        "connector_id": row.connector_id,
        "label": row.label,
        "base_url": row.base_url,
        "auth_type": row.auth_type,
        "secret_fingerprint": row.secret_fingerprint,
        "secret_fingerprint_algorithm": FINGERPRINT_ALGORITHM,
        "configured": row.revoked_at is None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _adapter_for(row: ConnectorCredentialProfile):
    settings = ConnectorAdapterSettings(
        connector_id=row.connector_id,
        base_url=row.base_url,
        credential_profile_id=row.ulid,
    )
    if row.connector_id == "sap_s4hana_product_bom_readonly":
        return SapS4ProductBomReadOnlyAdapter(settings)
    if row.connector_id == "windchill_part_bom_readonly":
        return WindchillPartBomReadOnlyAdapter(settings)
    raise HTTPException(status_code=400, detail="connector has no probe adapter")


async def probe_profile(row: ConnectorCredentialProfile) -> dict[str, Any]:
    adapter = _adapter_for(row)
    probe = adapter.probe_credentials()
    result = {
        "connector_id": row.connector_id,
        "credential_profile_id": row.ulid,
        "configured": row.revoked_at is None and probe.configured,
        "connected": False,
        "capability": "product_read",
        "records_read": 0,
        "checked_at": _now().isoformat(),
        "read_only": probe.read_only,
        "mode": probe.mode,
        "boundary_label": probe.boundary_label,
        "base_url": row.base_url,
        "auth_type": row.auth_type,
        "secret_fingerprint": row.secret_fingerprint,
        "secret_fingerprint_algorithm": FINGERPRINT_ALGORITHM,
        "reason": None,
    }
    if row.revoked_at is not None:
        result["reason"] = "credential profile is revoked"
        return result
    if not probe.configured:
        result["reason"] = probe.reason
        return result
    secret = decrypt_secret(row.encrypted_secret_json)
    try:
        async with asyncio.timeout(25):
            result["records_read"] = await probe_product_api(row.connector_id, row.base_url, row.auth_type, secret)
        result["connected"] = True
    except ConnectorConnectionError as exc:
        result["reason"] = str(exc)
    except TimeoutError:
        result["reason"] = "The connection test timed out. Check availability and try again."
    return result


async def run_bom_profile(
    session: AsyncSession, row: ConnectorCredentialProfile, *, user_id: int,
    part_id: str, assembly_key: str, mode: str, navigation_id: str | None = None,
    expected_sha256: str | None = None,
    sap_selection: dict[str, Any] | None = None,
) -> IntegrationRun:
    """Read vendor BOM, preview or atomically import normalized whole-part edges."""
    from src.services import bom_service

    sap = row.connector_id == "sap_s4hana_product_bom_readonly"
    if not sap and row.connector_id != "windchill_part_bom_readonly":
        raise HTTPException(status_code=400, detail="This connector has no BOM reader yet.")
    if row.revoked_at is not None:
        raise HTTPException(status_code=409, detail="This connection is revoked. Choose an active connection.")
    if mode not in {"dry_run", "import"}:
        raise HTTPException(status_code=400, detail="mode must be dry_run or import")
    if sap and mode == "import":
        raise HTTPException(status_code=400, detail="SAP supports BOM read previews only. Assembly import requires verified hierarchy and quantity semantics.")
    if sap and (not sap_selection or navigation_id):
        raise HTTPException(status_code=400, detail="Provide SAP BOM selectors; Windchill navigation criteria do not apply.")
    if not sap and sap_selection is not None:
        raise HTTPException(status_code=400, detail="SAP BOM selectors do not apply to Windchill.")
    key = _clean_text(assembly_key, "assembly_key", max_len=120)
    if mode == "import" and (not expected_sha256 or len(expected_sha256) != 64):
        raise HTTPException(status_code=400, detail="Preview the BOM before importing it.")
    rows: list[dict] = []
    source_count = 0
    error = None
    try:
        secret = decrypt_secret(row.encrypted_secret_json)
        if sap:
            assert sap_selection is not None  # Required before decrypting credentials.
            rows, source_count = await read_sap_bom_preview(row.base_url, row.auth_type, secret, part_id=part_id, selection=sap_selection)
        else:
            rows, source_count = await read_windchill_bom(row.base_url, row.auth_type, secret, part_id=part_id, navigation_id=navigation_id)
    except ConnectorConnectionError as exc:
        error = str(exc)
    except TimeoutError:
        error = "The BOM read timed out. No assembly was replaced; try again."
    normalized = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(normalized).hexdigest()
    if not error and mode == "import" and not hmac.compare_digest(digest, expected_sha256 or ""):
        error = "The BOM changed since its preview. Preview it again before importing; the saved assembly was kept."
    imported = 0
    if not error and mode == "import":
        summary = await bom_service.ingest_bom_rows(session, row.org_id, key, rows, source="windchill_api")
        imported = summary["edges"]
    run = IntegrationRun(
        ulid=str(ULID()), org_id=row.org_id, user_id=user_id, connector_id=row.connector_id,
        connector_mode="live_readonly", boundary_label="live_readonly", source_system="SAP S/4HANA" if sap else "PTC Windchill",
        source_kind="bom", api_name="API_BILL_OF_MATERIAL_SRV;v=2/ExplodeBOM" if sap else "ProdMgmt.GetPartStructure", mode=mode,
        status="failed" if error else "passed", filename=None, file_sha256=digest,
        file_size_bytes=len(normalized), source_record_count=source_count, normalized_record_count=len(rows),
        rows_total=len(rows), rows_valid=len(rows), rows_invalid=0, imported_count=imported,
        updated_count=0, skipped_count=len(rows) if error else 0, raw_stored=False,
        errors_json=[{"reason": error}] if error else [],
        metadata_json={
            "credential_profile_id": row.ulid, "assembly_key": key, "root_part_id": part_id,
            "navigation_criteria_id": navigation_id, "hash_scope": "BOM preview values" if sap else "normalized BOM edges",
            "read_completed": bool(rows), "replaces_existing_tree": mode == "import" and not error,
            "preview_edges": [] if sap else rows[:20], "preview_truncated": len(rows) > 20,
            "quantity_unit": None if sap else "ea", "vendor_writes": False,
            "import_supported": not sap,
            **({"preview_components": rows[:20], "sap_selection": sap_selection,
                "required_quantity": "1", "complete_structure_verified": False,
                "proof_scope": "ExplodeBOM read at the requested depth; no hierarchy or manufacturing quantity validation"} if sap else {}),
        }, completed_at=_now(),
    )
    session.add(run)
    await session.flush()
    return run
