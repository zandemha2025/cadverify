"""The org a role gate checked is the org the request uses (security review R2 F1).

``require_org_writer`` (and ``require_org_role``) check the caller's role in the
org that is active WHEN THE GATE RUNS. The route used to work the org out again
from ``users.current_org_id`` (``resolve_org`` / ``caller_org_subquery``), so the
same person's own ``POST /api/v1/orgs/switch``, landing between the two, moved a
write into an org where they are only a viewer. Every account is the admin of
its own personal org, so any org viewer could do this.

The gate now binds the org it checked for the rest of the request
(``src.auth.org_binding``); these tests prove the write lands in the checked org
or nowhere, and that the binding ends with the request.

Skipped unless DATABASE_URL points at Postgres migrated to head.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(not _PG, reason="needs Postgres")


def _app():
    from fastapi import FastAPI

    from src.api.machine_inventory import router as machine_router
    from src.api.org_routes import router as org_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(machine_router, prefix="/api/v1/machine-inventory")
    app.include_router(org_router, prefix="/api/v1/orgs")
    return app


async def _seed():
    """u: admin of org A (active), viewer of org B; B has its own admin."""
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:8]
    org_a, org_b = str(ULID()), str(ULID())
    async with eng.get_session_factory()() as s:
        for oid, name in ((org_a, f"Own {tag}"), (org_b, f"Viewed {tag}")):
            await s.execute(
                text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:i, :n, :s, now())"),
                {"i": oid, "n": name, "s": f"org-{oid.lower()}"},
            )
        ids = []
        for label in ("u", "badmin"):
            email = f"toctou-{tag}-{label}@example.com"
            ids.append(int((await s.execute(
                text("INSERT INTO users (email, email_lower, role, auth_provider) "
                     "VALUES (:e, :e, 'analyst', 'password') RETURNING id"),
                {"e": email},
            )).first()[0]))
        u, b_admin = ids
        for org, uid, role in ((org_a, u, "admin"), (org_b, u, "viewer"), (org_b, b_admin, "admin")):
            await s.execute(
                text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                     "VALUES (:i, :o, :u, :r, now())"),
                {"i": str(ULID()), "o": org, "u": uid, "r": role},
            )
        await s.execute(text("UPDATE users SET current_org_id = :o WHERE id = :u"), {"o": org_a, "u": u})
        await s.commit()
    return u, org_a, org_b


async def _machines_in(org_id: str) -> list[str]:
    from sqlalchemy import text

    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        return list((await s.execute(
            text("SELECT name FROM machine_instances WHERE org_id = :o"), {"o": org_id}
        )).scalars().all())


def _act_as(app, uid: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    # A dashboard session (api_key_id=0, key_prefix "session"), platform analyst.
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=uid, api_key_id=0, key_prefix="session", role="analyst"
    )


@pytest.fixture
def real_membership_lookup(monkeypatch):
    """Use the real ``lookup_org_membership`` (conftest swaps in a test double)."""
    import src.auth.models as models
    import src.auth.rbac as rbac

    monkeypatch.setattr(rbac, "lookup_org_membership", models.lookup_org_membership)
    return models.lookup_org_membership


@pytest.mark.asyncio
async def test_viewer_is_refused_without_a_switch(real_membership_lookup):
    """With org B active, the viewer's write is a 403 and nothing is saved."""
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng

    u, org_a, org_b = await _seed()
    app = _app()
    _act_as(app, u)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            assert (await ac.post("/api/v1/orgs/switch", json={"org_id": org_b})).status_code == 200
            r = await ac.post("/api/v1/machine-inventory", json={"name": "VIEWER-WRITE", "process": "cnc_3axis"})
            assert r.status_code == 403, r.text
        assert await _machines_in(org_b) == []
    finally:
        await eng.dispose_engine()


@pytest.mark.asyncio
async def test_switch_between_gate_and_route_lands_in_the_checked_org(monkeypatch, real_membership_lookup):
    """The switch lands right after the gate read the membership (what a
    concurrent POST /orgs/switch does). The write goes to org A, the org the
    gate checked, never to org B where the caller only views."""
    from httpx import ASGITransport, AsyncClient

    import src.auth.rbac as rbac
    import src.db.engine as eng

    u, org_a, org_b = await _seed()
    app = _app()
    _act_as(app, u)
    switched = {"done": False}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:

        async def lookup_then_switch(user_id: int):
            membership = await real_membership_lookup(user_id)  # the gate's read: (org A, admin)
            if not switched["done"]:
                switched["done"] = True
                # The person's own concurrent request, through the real route.
                r = await ac.post("/api/v1/orgs/switch", json={"org_id": org_b})
                assert r.status_code == 200 and r.json()["org_role"] == "viewer", r.text
            return membership

        monkeypatch.setattr(rbac, "lookup_org_membership", lookup_then_switch)
        r = await ac.post("/api/v1/machine-inventory", json={"name": "VIEWER-WRITE", "process": "cnc_3axis"})
    try:
        assert switched["done"]
        in_a, in_b = await _machines_in(org_a), await _machines_in(org_b)
        assert "VIEWER-WRITE" not in in_b, f"viewer wrote into org B: status={r.status_code}, org B={in_b}"
        assert r.status_code == 403 or (r.status_code == 201 and in_a == ["VIEWER-WRITE"]), (r.status_code, r.text)
    finally:
        await eng.dispose_engine()


@pytest.mark.asyncio
async def test_real_concurrent_switch_race(real_membership_lookup):
    """No patching: fire the write and the switch together, a few times. Any
    machine that lands in org B is a viewer write."""
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng

    u, org_a, org_b = await _seed()
    app = _app()
    _act_as(app, u)
    attempts = 40
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            for i in range(attempts):
                assert (await ac.post("/api/v1/orgs/switch", json={"org_id": org_a})).status_code == 200

                async def write():
                    return await ac.post("/api/v1/machine-inventory",
                                         json={"name": f"RACE-{i}", "process": "cnc_3axis"})

                async def switch():
                    await asyncio.sleep(0.0005 * (i % 10))
                    return await ac.post("/api/v1/orgs/switch", json={"org_id": org_b})

                await asyncio.gather(write(), switch())
        in_b = await _machines_in(org_b)
        assert in_b == [], f"{len(in_b)}/{attempts} viewer writes landed in org B: {in_b[:5]}"
    finally:
        await eng.dispose_engine()


@pytest.mark.asyncio
async def test_org_role_gate_binds_its_org_for_the_route(monkeypatch, real_membership_lookup):
    """``require_org_role`` (the admin/member/viewer gate) binds too: after a
    switch mid-request, ``resolve_org`` and ``caller_org_subquery`` in the route
    still answer the org the gate checked."""
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    import src.auth.rbac as rbac
    import src.db.engine as eng
    from src.api.org_routes import router as org_router
    from src.auth.org_context import caller_org_subquery, resolve_org
    from src.auth.rate_limit import limiter
    from src.db.engine import get_db_session

    u, org_a, org_b = await _seed()
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(org_router, prefix="/api/v1/orgs")

    @app.post("/probe")
    async def probe(
        ctx: rbac.OrgAuthContext = Depends(rbac.require_org_role(rbac.OrgRole.admin)),
        session=Depends(get_db_session),
    ):
        return {
            "gate": ctx.org_id,
            "resolve_org": await resolve_org(session, ctx.user_id),
            "subquery": (await session.execute(select(caller_org_subquery(ctx.user_id)))).scalar_one_or_none(),
            "membership": list(await rbac.lookup_org_membership(ctx.user_id) or ()),
        }

    _act_as(app, u)
    switched = {"done": False}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:

            async def lookup_then_switch(user_id: int):
                membership = await real_membership_lookup(user_id)
                if not switched["done"]:
                    switched["done"] = True
                    assert (await ac.post("/api/v1/orgs/switch", json={"org_id": org_b})).status_code == 200
                return membership

            monkeypatch.setattr(rbac, "lookup_org_membership", lookup_then_switch)
            r = await ac.post("/probe")
        assert r.status_code == 200, r.text
        assert r.json() == {"gate": org_a, "resolve_org": org_a, "subquery": org_a,
                            "membership": [org_a, "admin"]}
    finally:
        await eng.dispose_engine()


@pytest.mark.asyncio
async def test_binding_does_not_leak_between_requests(real_membership_lookup):
    """Two requests on the same worker, awaited in the same task (the in-process
    client): the first write's binding is gone when it returns, so after a real
    switch the next request reads and writes the newly active org."""
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng
    from src.auth.org_binding import gate_org

    u, org_a, org_b = await _seed()
    app = _app()
    _act_as(app, u)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post("/api/v1/machine-inventory", json={"name": "IN-A", "process": "cnc_3axis"})
            assert r.status_code == 201, r.text
            assert gate_org(u) is None  # released with the request

            assert (await ac.post("/api/v1/orgs/switch", json={"org_id": org_b})).status_code == 200
            listed = await ac.get("/api/v1/machine-inventory")
            assert listed.status_code == 200, listed.text
            names = [m["name"] for m in listed.json()["machines"]] if isinstance(listed.json(), dict) else [
                m["name"] for m in listed.json()]
            assert "IN-A" not in names  # org B's list, not the last write's org

            # A leaked (u, A) binding would let this through into org A.
            r = await ac.post("/api/v1/machine-inventory", json={"name": "SECOND", "process": "cnc_3axis"})
            assert r.status_code == 403, r.text
            assert gate_org(u) is None
        assert await _machines_in(org_a) == ["IN-A"]
        assert await _machines_in(org_b) == []
    finally:
        await eng.dispose_engine()


@pytest.mark.asyncio
async def test_bound_resolvers_follow_only_a_live_membership():
    """Unit level: a bound org answers for its own user only, and only while the
    membership is live (removed mid-request: no org, never a fallback)."""
    from sqlalchemy import select, text

    import src.db.engine as eng
    from src.auth.models import lookup_org_membership
    from src.auth.org_binding import bind_gate_org, gate_org, release_gate_org
    from src.auth.org_context import caller_org_subquery, resolve_org

    u, org_a, org_b = await _seed()
    try:
        async with eng.get_session_factory()() as s:
            await s.execute(text("UPDATE users SET current_org_id = :o WHERE id = :u"), {"o": org_b, "u": u})
            await s.commit()
            assert await resolve_org(s, u) == org_b

            token = bind_gate_org(u, org_a)
            try:
                assert gate_org(u) == org_a and gate_org(u + 1) is None
                assert await resolve_org(s, u) == org_a
                assert (await s.execute(select(caller_org_subquery(u)))).scalar_one_or_none() == org_a
                assert await lookup_org_membership(u) == (org_a, "admin")

                await s.execute(text("DELETE FROM memberships WHERE user_id = :u AND org_id = :o"),
                                {"u": u, "o": org_a})
                await s.commit()
                assert await resolve_org(s, u) is None
                assert await lookup_org_membership(u) is None
            finally:
                release_gate_org(token)
            assert gate_org(u) is None
            assert await resolve_org(s, u) == org_b
    finally:
        await eng.dispose_engine()
