"""Re-sharing never switches off someone else's live link (security review R2 F2).

Only the person who made a link, or an org admin, may switch it off; DELETE
.../share enforces it (403 share_not_yours). POST .../share with a body makes a
new short id and the old one stops resolving, so it must apply the same rule:
otherwise any org member could kill a colleague's live supplier link. The same
holds for POST /rfq-packages/{id}/share.

Skipped unless DATABASE_URL points at Postgres migrated to head.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").startswith("postgresql"), reason="needs Postgres"
    ),
]


def _app():
    from fastapi import FastAPI

    from src.api import rfq_packages
    from src.api.cost_decisions import public_cost_share_router
    from src.api.cost_decisions import router as cost_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(cost_router, prefix="/api/v1/cost-decisions")
    app.include_router(rfq_packages.router, prefix="/api/v1/rfq-packages")
    app.include_router(public_cost_share_router, prefix="/s")
    if hasattr(rfq_packages, "public_package_router"):
        app.include_router(rfq_packages.public_package_router, prefix="/s")
    return app


def _act_as(app, uid: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=uid, api_key_id=0, key_prefix="session", role="analyst"
    )


async def _add_user(s, org: str, label: str, role: str, tag: str) -> int:
    from sqlalchemy import text
    from ulid import ULID

    e = f"share-{tag}-{label}@example.com"
    uid = int((await s.execute(text(
        "INSERT INTO users (email, email_lower, role, auth_provider, current_org_id, plan) "
        "VALUES (:e, :e, 'analyst', 'password', :o, 'pilot') RETURNING id"), {"e": e, "o": org})).first()[0])
    await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                         "VALUES (:i, :o, :u, :r, now())"),
                    {"i": str(ULID()), "o": org, "u": uid, "r": role})
    return uid


async def test_member_cannot_replace_a_colleagues_live_cost_link():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:8]
    org = str(ULID())
    dec = str(ULID())
    async with eng.get_session_factory()() as s:
        await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:i, :n, :s, now())"),
                        {"i": org, "n": f"Share {tag}", "s": f"share-{tag}"})
        maker = await _add_user(s, org, "maker", "member", tag)
        other = await _add_user(s, org, "other", "member", tag)
        admin = await _add_user(s, org, "admin", "admin", tag)
        await s.execute(text(
            "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, params_hash, engine_version, "
            "filename, file_type, result_json) VALUES (:u, :uid, :o, :mh, 'p', 'e', 'bracket.step', 'step', "
            "CAST(:rj AS jsonb))"),
            {"u": dec, "uid": maker, "o": org, "mh": "a" * 64, "rj": json.dumps({"geometry": {}})})
        await s.commit()

    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            _act_as(app, maker)
            r = await ac.post(f"/api/v1/cost-decisions/{dec}/share",
                              json={"expires_in_days": 30, "note": "Quote 250 please"})
            assert r.status_code == 200, r.text
            makers_link = r.json()["share_short_id"]
            assert (await ac.get(f"/s/cost/{makers_link}")).status_code == 200

            _act_as(app, other)
            r = await ac.delete(f"/api/v1/cost-decisions/{dec}/share")
            assert r.status_code == 403 and r.json()["detail"]["code"] == "share_not_yours", r.text
            # Re-sharing with a body would switch the maker's link off: the same 403.
            r = await ac.post(f"/api/v1/cost-decisions/{dec}/share", json={"expires_in_days": 1})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "share_not_yours", r.text
            assert (await ac.get(f"/s/cost/{makers_link}")).status_code == 200
            # A bare POST (no body) still hands back the live link, unchanged.
            r = await ac.post(f"/api/v1/cost-decisions/{dec}/share")
            assert r.status_code == 200 and r.json()["share_short_id"] == makers_link, r.text

            # The maker may replace their own link; an admin may replace anyone's.
            _act_as(app, maker)
            r = await ac.post(f"/api/v1/cost-decisions/{dec}/share", json={"expires_in_days": 7})
            assert r.status_code == 200, r.text
            second = r.json()["share_short_id"]
            assert second != makers_link
            _act_as(app, admin)
            r = await ac.post(f"/api/v1/cost-decisions/{dec}/share", json={"expires_in_days": 7})
            assert r.status_code == 200 and r.json()["share_short_id"] != second, r.text
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.commit()
        await eng.dispose_engine()


@pytest.fixture
def kept(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("SOURCE_ARTIFACT_BLOB_DIR", str(tmp_path / "kept"))
    monkeypatch.delenv("OBJECT_STORE_LOCAL_ROOT", raising=False)
    monkeypatch.delenv("OBJECT_STORE_BACKEND", raising=False)


async def test_member_cannot_replace_a_colleagues_live_package_link(kept):
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng
    from tests.test_rfq_supplier_copy_pg import _cleanup, _seed

    w = await _seed()  # its user is the org's admin
    async with eng.get_session_factory()() as s:
        maker = await _add_user(s, w["org"], "pkgmaker", "member", w["tag"])
        other = await _add_user(s, w["org"], "pkgother", "member", w["tag"])
        await s.commit()
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            _act_as(app, maker)
            made = await ac.post("/api/v1/rfq-packages", json={
                "decision_ids": [w["single"]], "title": "RFQ-77", "supplier_name": "Midway"})
            assert made.status_code in (200, 201), made.text
            pkg = made.json()["package"]["id"]
            r = await ac.post(f"/api/v1/rfq-packages/{pkg}/share", json={"expires_in_days": 30})
            assert r.status_code == 200, r.text
            link = r.json()["share_url"]
            assert (await ac.get(link)).status_code == 200

            _act_as(app, other)
            r = await ac.post(f"/api/v1/rfq-packages/{pkg}/share", json={"expires_in_days": 1})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "share_not_yours", r.text
            assert (await ac.get(link)).status_code == 200

            _act_as(app, w["user"])  # an org admin may replace it
            r = await ac.post(f"/api/v1/rfq-packages/{pkg}/share", json={"expires_in_days": 7})
            assert r.status_code == 200 and r.json()["share_url"] != link, r.text
    finally:
        from sqlalchemy import text

        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM audit_log WHERE user_id IN (:a, :b)"), {"a": maker, "b": other})
            await s.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": maker, "b": other})
            await s.commit()
        await _cleanup(w)
