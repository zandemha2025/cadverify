"""SCIM 2.0 PATCH conformance (RFC 7644 §3.5.2).

Two layers:

  * Pure unit tests (no DB): the PatchOp path grammar + value coercion that the
    ``op``-verb branching relies on — bare attributes, value-path filters
    (``members[value eq "123"]``), sub-attributes (``emails[type eq "work"]
    .value``), boolean coercion of Entra's stringy ``"False"``, and the
    malformed forms that must raise a SCIM 400 (never a 500).
  * Live-Postgres replay of REAL Okta- and Entra-shaped PATCH payloads through
    the service layer (``patch_user`` / ``patch_group``) against a migrated
    scratch DB, asserting the resulting membership/identity state — including
    the preserved last-admin protection and deprovision semantics.

Skipped automatically unless DATABASE_URL is a Postgres URL at schema head:

    DATABASE_URL=postgresql://postgres@127.0.0.1:5433/cadverify_identity \\
        .venv/bin/python -m pytest tests/test_scim_patch_conformance.py -q
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from src.services import scim_service as svc

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)

PATCH_SCHEMA = svc.PATCH_SCHEMA


# ══════════════════════════════════════════════════════════════════════════
# Pure unit tests — PatchOp path grammar + value coercion (no DB)
# ══════════════════════════════════════════════════════════════════════════


def test_parse_patch_path_bare_and_empty():
    assert svc._parse_patch_path("active") == ("active", None, None)
    assert svc._parse_patch_path(None) == ("", None, None)
    assert svc._parse_patch_path("   ") == ("", None, None)
    # attribute names are case-folded (Okta/Entra vary the casing)
    assert svc._parse_patch_path("Active") == ("active", None, None)


def test_parse_patch_path_value_filter_okta_member_removal():
    # The exact form Okta sends to remove one group member.
    attr, filt, sub = svc._parse_patch_path('members[value eq "12345"]')
    assert attr == "members"
    assert filt == ("value", "12345")
    assert sub is None


def test_parse_patch_path_value_path_with_subattr():
    attr, filt, sub = svc._parse_patch_path('emails[type eq "work"].value')
    assert attr == "emails"
    assert filt == ("type", "work")
    assert sub == "value"


def test_parse_patch_path_malformed_raises_scim_invalid_path():
    with pytest.raises(HTTPException) as exc:
        svc._parse_patch_path('members[value eq "unterminated]')
    assert exc.value.status_code == 400
    assert exc.value.detail["scimType"] == "invalidPath"


def test_parse_patch_path_unsupported_operator_is_invalid_path():
    with pytest.raises(HTTPException) as exc:
        svc._parse_patch_path('members[value co "12345"]')
    assert exc.value.status_code == 400
    assert exc.value.detail["scimType"] == "invalidPath"


def test_coerce_bool_accepts_json_bool_and_entra_strings():
    assert svc._coerce_bool(True) is True
    assert svc._coerce_bool(False) is False
    assert svc._coerce_bool("True") is True   # Entra sometimes stringifies
    assert svc._coerce_bool("false") is False
    assert svc._coerce_bool("1") is True
    assert svc._coerce_bool("0") is False


def test_coerce_bool_rejects_garbage_as_scim_invalid_value():
    with pytest.raises(HTTPException) as exc:
        svc._coerce_bool("maybe")
    assert exc.value.status_code == 400
    assert exc.value.detail["scimType"] == "invalidValue"


def test_extract_member_ids_from_filter_and_value_list():
    # Okta: id lives in the value-path filter, no value body.
    assert svc._extract_member_ids(None, ("value", "77"), "members") == ["77"]
    # Entra: id lives in a value list of member objects.
    assert svc._extract_member_ids(
        [{"value": "88", "display": "x@y.z"}], None, "members"
    ) == ["88"]


# ══════════════════════════════════════════════════════════════════════════
# Live-PG replay helpers
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _loop_hermetic_engine():
    """Bind the asyncpg pool to each test's own event loop (see
    test_org_membership for the full rationale)."""
    import src.db.engine as _eng

    _eng._ENGINE = None
    _eng._SESSION_FACTORY = None
    try:
        yield
    finally:
        _eng._ENGINE = None
        _eng._SESSION_FACTORY = None


async def _mk_org(s, tag):
    from ulid import ULID

    oid = str(ULID())
    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ),
        {"id": oid, "n": f"Org {tag}", "sl": f"org-{tag}".lower()},
    )
    return oid


async def _provision(s, org_id, email, role="member", active=True):
    """Provision through the REAL SCIM create path (user + membership + identity)."""
    body = await svc.create_or_update_user(
        s,
        org_id=org_id,
        payload={
            "schemas": [svc.CORE_USER_SCHEMA],
            "userName": email,
            "active": active,
            "roles": [{"value": role}],
        },
    )
    return int(body["id"])


async def _teardown(eng, org_ids, user_ids):
    async with eng.get_session_factory()() as s:
        if user_ids:
            await s.execute(
                text("DELETE FROM scim_identities WHERE user_id = ANY(:u)"), {"u": user_ids}
            )
            await s.execute(
                text("DELETE FROM memberships WHERE user_id = ANY(:u)"), {"u": user_ids}
            )
            await s.execute(
                text("DELETE FROM api_keys WHERE user_id = ANY(:u)"), {"u": user_ids}
            )
            await s.execute(
                text("DELETE FROM audit_log WHERE user_id = ANY(:u)"), {"u": user_ids}
            )
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": user_ids})
        if org_ids:
            await s.execute(
                text("DELETE FROM scim_identities WHERE org_id = ANY(:o)"), {"o": org_ids}
            )
            await s.execute(
                text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": org_ids}
            )
        await s.commit()


async def _membership_role(s, org_id, uid):
    r = (
        await s.execute(
            text("SELECT org_role FROM memberships WHERE org_id=:o AND user_id=:u"),
            {"o": org_id, "u": uid},
        )
    ).first()
    return r[0] if r else None


async def _identity_active(s, org_id, uid):
    r = (
        await s.execute(
            text("SELECT active FROM scim_identities WHERE org_id=:o AND user_id=:u"),
            {"o": org_id, "u": uid},
        )
    ).first()
    return None if r is None else bool(r[0])


# ══════════════════════════════════════════════════════════════════════════
# Okta USER PATCH — deactivate via `replace active=false` (pathed)
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_okta_deactivate_user_replace_active_false():
    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_ids: list[str] = []
    user_ids: list[int] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag)
            org_ids.append(org)
            uid = await _provision(s, org, f"okta-{tag}@ex.com", role="member")
            user_ids.append(uid)
            await s.commit()

        # REAL Okta deactivate payload.
        async with eng.get_session_factory()() as s:
            body = await svc.patch_user(
                s,
                org_id=org,
                user_id=str(uid),
                payload={
                    "schemas": [PATCH_SCHEMA],
                    "Operations": [{"op": "replace", "path": "active", "value": False}],
                },
            )
            await s.commit()
            assert body["active"] is False

        async with eng.get_session_factory()() as s:
            # deprovision semantics: membership removed, identity persists inactive
            assert await _membership_role(s, org, uid) is None
            assert await _identity_active(s, org, uid) is False

        # reactivate via pathed replace active=true restores membership
        async with eng.get_session_factory()() as s:
            body = await svc.patch_user(
                s,
                org_id=org,
                user_id=str(uid),
                payload={
                    "schemas": [PATCH_SCHEMA],
                    "Operations": [{"op": "replace", "path": "active", "value": True}],
                },
            )
            await s.commit()
            assert body["active"] is True
        async with eng.get_session_factory()() as s:
            assert await _membership_role(s, org, uid) == "member"
    finally:
        await _teardown(eng, org_ids, user_ids)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Entra USER PATCH — deactivate via `replace` with a value object + stringy bool
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_entra_deactivate_user_replace_value_object_stringy_bool():
    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_ids: list[str] = []
    user_ids: list[int] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag)
            org_ids.append(org)
            uid = await _provision(s, org, f"entra-{tag}@ex.com", role="member")
            user_ids.append(uid)
            await s.commit()

        # REAL Entra deactivate payload: capital "Replace", pathless value object,
        # boolean expressed as the string "False".
        async with eng.get_session_factory()() as s:
            body = await svc.patch_user(
                s,
                org_id=org,
                user_id=str(uid),
                payload={
                    "schemas": [PATCH_SCHEMA],
                    "Operations": [{"op": "Replace", "value": {"active": "False"}}],
                },
            )
            await s.commit()
            assert body["active"] is False
        async with eng.get_session_factory()() as s:
            assert await _membership_role(s, org, uid) is None
            assert await _identity_active(s, org, uid) is False
    finally:
        await _teardown(eng, org_ids, user_ids)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# USER PATCH — role change via `replace roles`
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_patch_user_replace_roles_promotes_member_to_admin():
    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_ids: list[str] = []
    user_ids: list[int] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag)
            org_ids.append(org)
            uid = await _provision(s, org, f"role-{tag}@ex.com", role="member")
            user_ids.append(uid)
            await s.commit()

        async with eng.get_session_factory()() as s:
            await svc.patch_user(
                s,
                org_id=org,
                user_id=str(uid),
                payload={
                    "schemas": [PATCH_SCHEMA],
                    "Operations": [
                        {"op": "replace", "path": "roles", "value": [{"value": "admin"}]}
                    ],
                },
            )
            await s.commit()
        async with eng.get_session_factory()() as s:
            assert await _membership_role(s, org, uid) == "admin"
    finally:
        await _teardown(eng, org_ids, user_ids)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# USER PATCH — value-path email update (emails[type eq "work"].value)
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_patch_user_value_path_email_updates_display():
    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_ids: list[str] = []
    user_ids: list[int] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag)
            org_ids.append(org)
            uid = await _provision(s, org, f"mail-{tag}@ex.com", role="member")
            user_ids.append(uid)
            await s.commit()

        # A case-only change on the SAME identity via the value-path form Okta/
        # Entra emit; must apply to the display email and never 500.
        new_display = f"Mail-{tag}@ex.com"
        async with eng.get_session_factory()() as s:
            body = await svc.patch_user(
                s,
                org_id=org,
                user_id=str(uid),
                payload={
                    "schemas": [PATCH_SCHEMA],
                    "Operations": [
                        {"op": "replace", "path": 'emails[type eq "work"].value', "value": new_display}
                    ],
                },
            )
            await s.commit()
            assert body["userName"] == new_display
        async with eng.get_session_factory()() as s:
            # membership preserved; identity still active
            assert await _membership_role(s, org, uid) == "member"
            r = (
                await s.execute(
                    text("SELECT email FROM users WHERE id=:u"), {"u": uid}
                )
            ).first()
            assert r[0] == new_display
    finally:
        await _teardown(eng, org_ids, user_ids)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# GROUP PATCH — Okta add + Okta filtered remove + Entra value-list remove
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_group_member_add_okta_filtered_remove_and_entra_value_remove():
    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_ids: list[str] = []
    user_ids: list[int] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag)
            org_ids.append(org)
            # Seed two viewers so removing them from 'member' has a base role.
            u1 = await _provision(s, org, f"grp1-{tag}@ex.com", role="viewer")
            u2 = await _provision(s, org, f"grp2-{tag}@ex.com", role="viewer")
            user_ids += [u1, u2]
            await s.commit()

        # Okta add: PATCH role:member group with a value list of members.
        async with eng.get_session_factory()() as s:
            await svc.patch_group(
                s,
                org_id=org,
                group_id="role:member",
                payload={
                    "schemas": [PATCH_SCHEMA],
                    "Operations": [
                        {
                            "op": "add",
                            "path": "members",
                            "value": [
                                {"value": str(u1), "display": f"grp1-{tag}@ex.com"},
                                {"value": str(u2), "display": f"grp2-{tag}@ex.com"},
                            ],
                        }
                    ],
                },
            )
            await s.commit()
        async with eng.get_session_factory()() as s:
            assert await _membership_role(s, org, u1) == "member"
            assert await _membership_role(s, org, u2) == "member"

        # Okta filtered remove: members[value eq "<u1>"] with NO value body.
        async with eng.get_session_factory()() as s:
            await svc.patch_group(
                s,
                org_id=org,
                group_id="role:member",
                payload={
                    "schemas": [PATCH_SCHEMA],
                    "Operations": [{"op": "remove", "path": f'members[value eq "{u1}"]'}],
                },
            )
            await s.commit()
        async with eng.get_session_factory()() as s:
            # demoted to viewer (higher-role removal preserves access)
            assert await _membership_role(s, org, u1) == "viewer"
            assert await _membership_role(s, org, u2) == "member"

        # Entra value-list remove: {"op":"remove","path":"members","value":[{...}]}
        async with eng.get_session_factory()() as s:
            await svc.patch_group(
                s,
                org_id=org,
                group_id="role:member",
                payload={
                    "schemas": [PATCH_SCHEMA],
                    "Operations": [
                        {"op": "remove", "path": "members", "value": [{"value": str(u2)}]}
                    ],
                },
            )
            await s.commit()
        async with eng.get_session_factory()() as s:
            assert await _membership_role(s, org, u2) == "viewer"
    finally:
        await _teardown(eng, org_ids, user_ids)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Malformed PatchOps → SCIM-shaped 400 (never a 500)
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_malformed_patchops_return_scim_400_not_500():
    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_ids: list[str] = []
    user_ids: list[int] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag)
            org_ids.append(org)
            uid = await _provision(s, org, f"bad-{tag}@ex.com", role="member")
            user_ids.append(uid)
            await s.commit()

        async def _expect_scim_400(payload, scim_type, *, group=False):
            async with eng.get_session_factory()() as s:
                with pytest.raises(HTTPException) as exc:
                    if group:
                        await svc.patch_group(
                            s, org_id=org, group_id="role:member", payload=payload
                        )
                    else:
                        await svc.patch_user(
                            s, org_id=org, user_id=str(uid), payload=payload
                        )
                await s.rollback()
            assert exc.value.status_code == 400, exc.value.detail
            assert exc.value.detail.get("scimType") == scim_type
            assert exc.value.detail["schemas"] == [
                "urn:ietf:params:scim:api:messages:2.0:Error"
            ]

        # Unknown op verb → invalidSyntax
        await _expect_scim_400(
            {"schemas": [PATCH_SCHEMA], "Operations": [{"op": "frobnicate", "path": "active", "value": True}]},
            "invalidSyntax",
        )
        # Missing Operations array → invalidSyntax
        await _expect_scim_400({"schemas": [PATCH_SCHEMA]}, "invalidSyntax")
        # Unparseable path → invalidPath
        await _expect_scim_400(
            {"schemas": [PATCH_SCHEMA], "Operations": [{"op": "replace", "path": 'x[bad', "value": 1}]},
            "invalidPath",
        )
        # Non-boolean active value → invalidValue
        await _expect_scim_400(
            {"schemas": [PATCH_SCHEMA], "Operations": [{"op": "replace", "path": "active", "value": "maybe"}]},
            "invalidValue",
        )
        # Unknown user attribute path → invalidPath
        await _expect_scim_400(
            {"schemas": [PATCH_SCHEMA], "Operations": [{"op": "replace", "path": "nickName", "value": "x"}]},
            "invalidPath",
        )
        # Group: non-numeric member id → invalidValue
        await _expect_scim_400(
            {"schemas": [PATCH_SCHEMA], "Operations": [{"op": "add", "path": "members", "value": [{"value": "not-an-int"}]}]},
            "invalidValue",
            group=True,
        )
        # Group: remove with no path (bare) is tolerated? No — bad op verb group
        await _expect_scim_400(
            {"schemas": [PATCH_SCHEMA], "Operations": [{"op": "BOGUS", "path": "members"}]},
            "invalidSyntax",
            group=True,
        )
    finally:
        await _teardown(eng, org_ids, user_ids)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Last-admin protection preserved across the hardened PATCH path
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_last_admin_protection_preserved_on_deactivate():
    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_ids: list[str] = []
    user_ids: list[int] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag)
            org_ids.append(org)
            admin = await _provision(s, org, f"admin-{tag}@ex.com", role="admin")
            user_ids.append(admin)
            await s.commit()

        # Deactivating the SOLE admin must fail closed (409 mutability), exactly
        # as the pre-hardening path did.
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as exc:
                await svc.patch_user(
                    s,
                    org_id=org,
                    user_id=str(admin),
                    payload={
                        "schemas": [PATCH_SCHEMA],
                        "Operations": [{"op": "replace", "path": "active", "value": False}],
                    },
                )
            await s.rollback()
            assert exc.value.status_code == 409
            assert exc.value.detail.get("scimType") == "mutability"

        # And demoting the sole admin via `replace roles=viewer` is equally refused.
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as exc:
                await svc.patch_user(
                    s,
                    org_id=org,
                    user_id=str(admin),
                    payload={
                        "schemas": [PATCH_SCHEMA],
                        "Operations": [
                            {"op": "replace", "path": "roles", "value": [{"value": "viewer"}]}
                        ],
                    },
                )
            await s.rollback()
            assert exc.value.status_code == 409
    finally:
        await _teardown(eng, org_ids, user_ids)
        await eng.dispose_engine()
