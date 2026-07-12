"""End-to-end org-scoped RBAC matrix for admin_routes, against real Postgres.

W1 step 2's load-bearing proof: that the org boundary in ``admin_routes`` is
*real*, not stubbed. Two orgs (A, B) are seeded with real ``organizations`` /
``users`` / ``memberships`` / ``audit_log`` rows; the admin endpoints are driven
through an ASGI client with only ``require_api_key`` overridden (to name the
acting principal). Everything else — ``require_org_role`` -> the real
``lookup_org_membership`` -> the JOIN/filter queries in the handlers — runs
against the live DB. So a passing run means an org-admin genuinely cannot see or
touch another org's users, and a superadmin genuinely can.

Skipped automatically unless DATABASE_URL is a Postgres URL. Run it against a
migrated scratch DB (schema at head, i.e. through 0010 so the 'superadmin'
platform role is permitted):

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/w1s2_rbac \\
        .venv/bin/python -m pytest tests/test_admin_org_rbac.py -q
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.auth.require_api_key import AuthedUser, require_api_key

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _build_app():
    from fastapi import FastAPI

    from src.api.admin_routes import router as admin_router

    app = FastAPI()
    app.include_router(admin_router)
    return app


def _act_as(app, user_id: int, role: str) -> None:
    """Point the app's auth at a specific seeded principal."""
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role=role
    )


@_requires_pg
@pytest.mark.asyncio
async def test_admin_org_rbac_matrix():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_a = str(ULID())
    org_b = str(ULID())
    created_users: list[int] = []

    async def _mk_user(s, label: str, role: str = "analyst") -> int:
        email = f"rbac-{tag}-{label}@example.com"
        row = (
            await s.execute(
                text(
                    "INSERT INTO users (email, email_lower, role, auth_provider) "
                    "VALUES (:e, :el, :r, 'password') RETURNING id"
                ),
                {"e": email, "el": email.lower(), "r": role},
            )
        ).first()
        uid = int(row[0])
        created_users.append(uid)
        return uid

    async def _mk_membership(s, org_id: str, user_id: int, org_role: str) -> None:
        await s.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                "VALUES (:id, :o, :u, :r, now())"
            ),
            {"id": str(ULID()), "o": org_id, "u": user_id, "r": org_role},
        )

    async def _mk_audit(s, org_id: str, user_id: int, action: str) -> None:
        await s.execute(
            text(
                "INSERT INTO audit_log (user_id, org_id, user_email, action, "
                "resource_type) VALUES (:u, :o, :e, :a, 'test')"
            ),
            {"u": user_id, "o": org_id, "e": f"rbac-{tag}@x.com", "a": action},
        )

    # ---- seed ---------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        for oid, name in ((org_a, f"Org A {tag}"), (org_b, f"Org B {tag}")):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": name, "sl": f"{name.lower().replace(' ', '-')}"},
            )
        a_admin = await _mk_user(s, "a-admin")
        a_member = await _mk_user(s, "a-member")
        a_viewer = await _mk_user(s, "a-viewer")
        b_admin = await _mk_user(s, "b-admin")
        # Platform staff: superadmin role, deliberately NO membership — proves the
        # bypass path resolves through a real (empty) membership query.
        superadmin = await _mk_user(s, "super", role="superadmin")

        await _mk_membership(s, org_a, a_admin, "admin")
        await _mk_membership(s, org_a, a_member, "member")
        await _mk_membership(s, org_a, a_viewer, "viewer")
        await _mk_membership(s, org_b, b_admin, "admin")

        await _mk_audit(s, org_a, a_admin, "test.a.event")
        await _mk_audit(s, org_b, b_admin, "test.b.event")
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).isoformat()
    end = (now + timedelta(days=1)).isoformat()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # === list /users ===============================================
            # org-admin A sees exactly org A's members, each stamped with org A.
            _act_as(app, a_admin, "analyst")
            r = await ac.get("/api/v1/admin/users?limit=100")
            assert r.status_code == 200, r.text
            got = {u["id"] for u in r.json()["users"]}
            assert {a_admin, a_member, a_viewer} <= got
            assert b_admin not in got          # cross-org isolation
            assert superadmin not in got       # no A membership
            for u in r.json()["users"]:
                assert u["org_id"] == org_a
            roles = {u["id"]: u["org_role"] for u in r.json()["users"]}
            assert roles[a_admin] == "admin"
            assert roles[a_member] == "member"
            assert roles[a_viewer] == "viewer"

            # org-admin B sees only org B.
            _act_as(app, b_admin, "analyst")
            r = await ac.get("/api/v1/admin/users?limit=100")
            got = {u["id"] for u in r.json()["users"]}
            assert b_admin in got
            assert not ({a_admin, a_member, a_viewer} & got)

            # superadmin sees across BOTH orgs.
            _act_as(app, superadmin, "superadmin")
            r = await ac.get("/api/v1/admin/users?limit=100")
            assert r.status_code == 200
            got = {u["id"] for u in r.json()["users"]}
            assert {a_admin, b_admin} <= got

            # member / viewer are denied the admin surface entirely.
            for uid in (a_member, a_viewer):
                _act_as(app, uid, "analyst")
                r = await ac.get("/api/v1/admin/users")
                assert r.status_code == 403
                assert r.json()["detail"]["code"] == "insufficient_org_role"

            # === detail /users/{id} ========================================
            _act_as(app, a_admin, "analyst")
            r = await ac.get(f"/api/v1/admin/users/{a_member}")
            assert r.status_code == 200
            assert r.json()["org_id"] == org_a
            assert r.json()["org_role"] == "member"

            # A-admin cannot see B's user -> 404 (no existence leak).
            r = await ac.get(f"/api/v1/admin/users/{b_admin}")
            assert r.status_code == 404

            # superadmin can see B's user.
            _act_as(app, superadmin, "superadmin")
            r = await ac.get(f"/api/v1/admin/users/{b_admin}")
            assert r.status_code == 200
            assert r.json()["org_role"] == "admin"

            # === PATCH /users/{id}/role ====================================
            _act_as(app, a_admin, "analyst")
            # cross-org write is blocked (404) and does NOT mutate B's user.
            r = await ac.patch(
                f"/api/v1/admin/users/{b_admin}/role", json={"role": "viewer"}
            )
            assert r.status_code == 404
            # in-org role change succeeds and persists.
            r = await ac.patch(
                f"/api/v1/admin/users/{a_member}/role", json={"role": "viewer"}
            )
            assert r.status_code == 200
            assert r.json()["role"] == "viewer"
            # cannot grant superadmin through the self-service endpoint.
            r = await ac.patch(
                f"/api/v1/admin/users/{a_viewer}/role", json={"role": "superadmin"}
            )
            assert r.status_code == 400
            # cannot change own role.
            r = await ac.patch(
                f"/api/v1/admin/users/{a_admin}/role", json={"role": "viewer"}
            )
            assert r.status_code == 400

            # Verify persistence + that B was untouched.
            async with eng.get_session_factory()() as s2:
                a_member_role = (
                    await s2.execute(
                        text("SELECT role FROM users WHERE id = :u"), {"u": a_member}
                    )
                ).first()[0]
                b_admin_role = (
                    await s2.execute(
                        text("SELECT role FROM users WHERE id = :u"), {"u": b_admin}
                    )
                ).first()[0]
            assert a_member_role == "viewer"
            assert b_admin_role == "analyst"   # never mutated cross-org

            # === audit-log =================================================
            audit_params_a = {
                "start": start,
                "end": end,
                "limit": 10,
                "action": "test.a.event",
            }
            audit_params_b = {
                "start": start,
                "end": end,
                "limit": 10,
                "action": "test.b.event",
            }
            _act_as(app, a_admin, "analyst")
            r = await ac.get("/api/v1/admin/audit-log", params=audit_params_a)
            assert r.status_code == 200, r.text
            actions = {e["action"] for e in r.json()["entries"]}
            assert "test.a.event" in actions

            r = await ac.get("/api/v1/admin/audit-log", params=audit_params_b)
            assert r.status_code == 200, r.text
            actions = {e["action"] for e in r.json()["entries"]}
            assert "test.b.event" not in actions   # org-scoped

            _act_as(app, superadmin, "superadmin")
            r = await ac.get("/api/v1/admin/audit-log", params=audit_params_a)
            assert r.status_code == 200, r.text
            actions = {e["action"] for e in r.json()["entries"]}
            assert "test.a.event" in actions

            r = await ac.get("/api/v1/admin/audit-log", params=audit_params_b)
            assert r.status_code == 200, r.text
            actions = {e["action"] for e in r.json()["entries"]}
            assert "test.b.event" in actions
    finally:
        # ---- teardown (FK-safe, no leaks) ----------------------------------
        async with eng.get_session_factory()() as s:
            await s.execute(
                text("DELETE FROM audit_log WHERE org_id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
            if created_users:
                await s.execute(
                    text("DELETE FROM memberships WHERE user_id = ANY(:ids)"),
                    {"ids": created_users},
                )
                await s.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": created_users},
                )
            await s.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
            await s.commit()
        await eng.dispose_engine()
