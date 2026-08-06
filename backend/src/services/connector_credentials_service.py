"""Encrypted connector credential profiles for enterprise integrations."""
from __future__ import annotations

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

from src.db.models import ConnectorCredentialProfile
from src.services.connector_adapters import (
    ConnectorAdapterSettings,
    SapS4ProductBomReadOnlyAdapter,
    WindchillPartBomReadOnlyAdapter,
)
from src.services.integration_service import get_connector

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
    fingerprint = _fingerprint_secret(canonical)
    token = _fernet().encrypt(canonical.encode("utf-8")).decode("utf-8")
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
    parsed = urlparse(clean)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="base_url must be an absolute URL")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="base_url must not contain credentials")
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


def probe_profile(row: ConnectorCredentialProfile) -> dict[str, Any]:
    adapter = _adapter_for(row)
    if row.revoked_at is not None:
        probe = adapter.probe_credentials()
        return {
            "connector_id": row.connector_id,
            "credential_profile_id": row.ulid,
            "configured": False,
            "read_only": probe.read_only,
            "mode": probe.mode,
            "boundary_label": probe.boundary_label,
            "base_url": row.base_url,
            "auth_type": row.auth_type,
            "secret_fingerprint": row.secret_fingerprint,
            "secret_fingerprint_algorithm": FINGERPRINT_ALGORITHM,
            "reason": "credential profile is revoked",
        }
    secret = decrypt_secret(row.encrypted_secret_json)
    probe = adapter.probe_credentials()
    has_required_secret = bool(secret)
    configured = row.revoked_at is None and probe.configured and has_required_secret
    return {
        "connector_id": row.connector_id,
        "credential_profile_id": row.ulid,
        "configured": configured,
        "read_only": probe.read_only,
        "mode": probe.mode,
        "boundary_label": probe.boundary_label,
        "base_url": row.base_url,
        "auth_type": row.auth_type,
        "secret_fingerprint": row.secret_fingerprint,
        "secret_fingerprint_algorithm": FINGERPRINT_ALGORITHM,
        "reason": None if configured else probe.reason or "credential profile is revoked or incomplete",
    }
