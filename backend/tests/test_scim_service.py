from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.services import scim_service as svc


def test_scim_discovery_declares_real_user_group_patch_filter_contract():
    config = svc.service_provider_config()
    schemas = svc.schemas()
    resource_types = svc.resource_types()

    assert config["patch"]["supported"] is True
    assert config["filter"]["supported"] is True
    assert config["bulk"]["supported"] is False
    assert {item["id"] for item in resource_types["Resources"]} == {"User", "Group"}
    assert {item["id"] for item in schemas["Resources"]} == {
        svc.CORE_USER_SCHEMA,
        svc.CORE_GROUP_SCHEMA,
    }


def test_scim_user_serialization_marks_org_membership_as_active_boundary():
    user = SimpleNamespace(
        id=7,
        email="engineer@example.com",
        is_active=True,
        created_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )
    membership = SimpleNamespace(org_id="org_1", org_role="member")
    identity = SimpleNamespace(
        org_id="org_1",
        org_role="member",
        external_id="okta-123",
        active=True,
    )

    body = svc.serialize_user(user, membership, identity, base_url="https://api.example")

    assert body["id"] == "7"
    assert body["externalId"] == "okta-123"
    assert body["userName"] == "engineer@example.com"
    assert body["active"] is True
    assert body["roles"][0]["value"] == "member"
    assert body["urn:cadverify:params:scim:schemas:extension:2.0:User"] == {
        "orgRole": "member",
        "orgId": "org_1",
    }
    assert body["meta"]["location"] == "https://api.example/scim/v2/Users/7"


def test_scim_user_without_membership_is_inactive_for_this_org():
    user = SimpleNamespace(
        id=8,
        email="former@example.com",
        is_active=True,
        created_at=None,
    )

    identity = SimpleNamespace(
        org_id="org_1",
        org_role="viewer",
        external_id="entra-456",
        active=False,
    )

    body = svc.serialize_user(user, None, identity)

    assert body["active"] is False
    assert body["externalId"] == "entra-456"
    assert body["roles"][0]["value"] == "viewer"


def test_scim_role_groups_are_stable_virtual_ids():
    body = svc.serialize_group(
        "admin",
        [(7, "admin@example.com")],
        base_url="https://api.example",
    )

    assert body["id"] == "role:admin"
    assert body["displayName"] == "ProofShape admin"
    assert body["members"][0]["value"] == "7"
    assert body["members"][0]["$ref"] == "https://api.example/scim/v2/Users/7"
