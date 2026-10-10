#!/usr/bin/env python3
"""Read-only reconciliation of actual local ScaleCad identity and Keycloak.

Run with the backend Python venv; there is no browser/session forgery and no
database mutation. Only the imported synthetic test user's rows are exported.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import asyncpg

from environment import STATE, app_env, bootstrap, now, protected_json, revision, served_revision


async def collect() -> None:
    cfg = bootstrap()
    provider_path = STATE / "evidence/keycloak-provider-receipts.json"
    if not provider_path.exists():
        raise RuntimeError("Capture actual provider-receipts first")
    provider = json.loads(provider_path.read_text())
    source = provider["user"]
    expected_subject = source["id"]
    expected_email = source["email"]
    expected_issuer = provider["issuer"]
    connection = await asyncpg.connect(app_env(cfg)["DATABASE_URL"])
    try:
        async with connection.transaction(readonly=True):
            identities = await connection.fetch(
                "SELECT ai.id, ai.user_id, ai.provider, ai.issuer, ai.subject, ai.created_at, ai.last_login_at, "
                "u.email, u.auth_provider, u.is_active, u.role, u.session_version "
                "FROM auth_identities ai JOIN users u ON u.id = ai.user_id "
                "WHERE ai.provider = 'oidc' AND ai.issuer = $1 AND ai.subject = $2",
                expected_issuer, expected_subject,
            )
            users = await connection.fetch(
                "SELECT id, email, auth_provider, is_active, role, session_version "
                "FROM users WHERE email_lower = $1", expected_email.casefold(),
            )
            user_ids = [row["id"] for row in users]
            memberships = await connection.fetch(
                "SELECT id, org_id, user_id, org_role, created_at FROM memberships WHERE user_id = ANY($1::bigint[])",
                user_ids,
            )
            audits = await connection.fetch(
                "SELECT id, user_id, org_id, action, resource_type, resource_id, detail_json, timestamp "
                "FROM audit_log WHERE user_id = ANY($1::bigint[]) ORDER BY id", user_ids,
            )
    finally:
        await connection.close()
    clean_audits = []
    for row in audits:
        item = dict(row)
        detail = item.pop("detail_json")
        if isinstance(detail, str):
            detail = json.loads(detail)
        item["detail_allowlisted"] = {key: value for key, value in (detail or {}).items()
                                      if key in {"auth_provider", "role", "created", "issuer", "subject", "groups", "session_version"}}
        clean_audits.append(item)
    identity_rows = [dict(row) for row in identities]
    user_rows = [dict(row) for row in users]
    proof = {
        "captured_at": now(), "source_revision": served_revision(), "repository_revision": revision(), "database_read_only": True,
        "provider_receipt_artifact": str(provider_path),
        "provider_receipt_sha256": hashlib.sha256(provider_path.read_bytes()).hexdigest(),
        "source_identity": {"issuer": expected_issuer, "subject": expected_subject, "email": expected_email,
                            "email_verified": source["emailVerified"], "groups": [item["path"] for item in provider["groups"]]},
        "identities": identity_rows, "users": user_rows,
        "memberships": [dict(row) for row in memberships], "audit_events": clean_audits,
        "reconciliation": {
            "exactly_one_identity": len(identity_rows) == 1,
            "exactly_one_email_account": len(user_rows) == 1,
            "issuer_subject_email_match": len(identity_rows) == 1 and identity_rows[0]["issuer"] == expected_issuer
                 and identity_rows[0]["subject"] == expected_subject and identity_rows[0]["email"] == expected_email,
            "provider_login_receipt_count": sum(item.get("type") == "LOGIN" and item.get("clientId") == "scalecad-integration"
                 and item.get("userId") == expected_subject for item in provider["events"]),
            "provider_wrong_password_receipt_count": sum(item.get("type") == "LOGIN_ERROR" and item.get("clientId") == "scalecad-integration"
                 for item in provider["events"]),
            "group_mapping_claim": "not tested; no group-to-role mapping was created",
        },
    }
    # Datetimes are safe source metadata, represented in UTC ISO form.
    proof = json.loads(json.dumps(proof, default=lambda value: value.isoformat()))
    destination = STATE / "evidence/scalecad-identity-reconciliation.json"
    protected_json(destination, proof)
    print(f"Read-only actual identity reconciliation saved to {destination}")
    print(json.dumps(proof["reconciliation"], indent=2))


if __name__ == "__main__":
    asyncio.run(collect())
