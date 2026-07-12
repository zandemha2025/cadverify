from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from src.db.models import ConnectorCredentialProfile
from src.services import connector_credentials_service as svc


def _profile(**overrides):
    data = {
        "ulid": "01CRED",
        "org_id": "org_1",
        "connector_id": "sap_s4hana_product_bom_readonly",
        "label": "SAP sandbox",
        "base_url": "https://sap.example",
        "auth_type": "bearer",
        "encrypted_secret_json": svc.encrypt_secret({"token": "secret-token"})[0],
        "secret_fingerprint": "f" * 64,
        "revoked_at": None,
        "metadata_json": {"tenant": "sandbox"},
        "created_at": datetime(2026, 7, 8, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 8, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return ConnectorCredentialProfile(**data)


def test_encrypt_decrypt_secret_round_trips_without_plaintext_token():
    encrypted, fingerprint = svc.encrypt_secret({"token": "secret-token"})
    raw_sha = hashlib.sha256(
        json.dumps({"token": "secret-token"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert "secret-token" not in encrypted
    assert len(fingerprint) == 64
    assert fingerprint != raw_sha
    assert svc.decrypt_secret(encrypted) == {"token": "secret-token"}


def test_serialize_profile_redacts_encrypted_secret_material():
    profile = _profile(secret_fingerprint="abc123")

    body = svc.serialize_profile(profile)

    assert body["id"] == "01CRED"
    assert body["connector_id"] == "sap_s4hana_product_bom_readonly"
    assert body["secret_fingerprint"] == "abc123"
    assert body["secret_fingerprint_algorithm"] == "hmac_sha256"
    assert "encrypted_secret_json" not in body
    assert "secret-token" not in str(body)


def test_probe_profile_uses_readonly_adapter_and_redacts_secret():
    profile = _profile(secret_fingerprint="abc123")

    probe = svc.probe_profile(profile)

    assert probe["configured"] is True
    assert probe["read_only"] is True
    assert probe["mode"] == "sandbox_api"
    assert probe["boundary_label"] == "sandbox"
    assert probe["secret_fingerprint"] == "abc123"
    assert probe["secret_fingerprint_algorithm"] == "hmac_sha256"
    assert "secret-token" not in str(probe)


def test_probe_revoked_profile_does_not_decrypt_secret(monkeypatch):
    profile = _profile(revoked_at=datetime(2026, 7, 8, tzinfo=timezone.utc))
    monkeypatch.setattr(
        svc,
        "decrypt_secret",
        lambda encrypted: pytest.fail("revoked probes must not decrypt secret material"),
    )

    probe = svc.probe_profile(profile)

    assert probe["configured"] is False
    assert probe["reason"] == "credential profile is revoked"


@pytest.mark.asyncio
async def test_create_profile_requires_credential_required_connector():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    with pytest.raises(Exception) as exc:
        await svc.create_profile(
            session,
            org_id="org_1",
            user_id=1,
            connector_id="sap_manifest_csv",
            label="bad",
            base_url="https://sap.example",
            auth_type="bearer",
            secret={"token": "x"},
        )

    assert getattr(exc.value, "status_code", None) == 400
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_profile_encrypts_secret_and_tracks_fingerprint():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    profile = await svc.create_profile(
        session,
        org_id="org_1",
        user_id=1,
        connector_id="sap_s4hana_product_bom_readonly",
        label="SAP sandbox",
        base_url="https://sap.example/",
        auth_type="bearer",
        secret={"token": "secret-token"},
    )

    assert profile.connector_id == "sap_s4hana_product_bom_readonly"
    assert profile.base_url == "https://sap.example"
    assert profile.secret_fingerprint
    assert "secret-token" not in profile.encrypted_secret_json
    assert svc.decrypt_secret(profile.encrypted_secret_json) == {"token": "secret-token"}
    session.add.assert_called_once_with(profile)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_profile_rejects_insecure_nonlocal_base_url():
    session = AsyncMock()
    session.add = MagicMock()

    with pytest.raises(Exception) as exc:
        await svc.create_profile(
            session,
            org_id="org_1",
            user_id=1,
            connector_id="sap_s4hana_product_bom_readonly",
            label="SAP sandbox",
            base_url="http://sap.example",
            auth_type="bearer",
            secret={"token": "secret-token"},
        )

    assert getattr(exc.value, "status_code", None) == 400
    assert "https" in exc.value.detail
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_profile_validates_auth_secret_shape():
    session = AsyncMock()
    session.add = MagicMock()

    with pytest.raises(Exception) as exc:
        await svc.create_profile(
            session,
            org_id="org_1",
            user_id=1,
            connector_id="sap_s4hana_product_bom_readonly",
            label="SAP sandbox",
            base_url="https://sap.example",
            auth_type="basic",
            secret={"token": "wrong-shape"},
        )

    assert getattr(exc.value, "status_code", None) == 400
    assert "username" in exc.value.detail
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_profile_maps_duplicate_label_to_conflict():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock(
        side_effect=IntegrityError("duplicate", params=None, orig=Exception("duplicate"))
    )

    with pytest.raises(Exception) as exc:
        await svc.create_profile(
            session,
            org_id="org_1",
            user_id=1,
            connector_id="sap_s4hana_product_bom_readonly",
            label="SAP sandbox",
            base_url="https://sap.example",
            auth_type="bearer",
            secret={"token": "secret-token"},
        )

    assert getattr(exc.value, "status_code", None) == 409
    assert "already exists" in exc.value.detail


@pytest.mark.asyncio
async def test_revoke_profile_refreshes_updated_fields_before_serialization(monkeypatch):
    session = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    profile = _profile()

    async def _get_profile(session_arg, *, org_id, profile_id):
        assert session_arg is session
        assert org_id == "org_1"
        assert profile_id == "01CRED"
        return profile

    monkeypatch.setattr(svc, "get_profile", _get_profile)

    row = await svc.revoke_profile(session, org_id="org_1", profile_id="01CRED")

    assert row.revoked_at is not None
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(profile)
    body = svc.serialize_profile(row)
    assert body["configured"] is False
    assert body["revoked_at"]
