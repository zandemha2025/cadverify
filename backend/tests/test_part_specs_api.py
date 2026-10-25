"""Part specs, sign-off and per-user settings through the real routes (live Postgres).

Drives ``/api/v1/part-context``, ``/api/v1/cost-decisions``, ``/api/v1/orgs/signoff``
and ``/api/v1/account/preferences`` with only the auth principal overridden.
Proves:

  * specs are validated (400 on unknown values), stored normalized and read back;
  * changing specs or service conditions marks the part's saved decisions out of
    date (and only that part's), with the reason; an identical PUT marks nothing;
  * the org's sign-off rule: members by default, admins only when set; only an org
    admin changes it; a sign-off carries the signer's name, time and note; an
    out-of-date record can't be signed off, and a signed-off record that goes out
    of date says so;
  * the length unit is remembered per user and validated.

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``).
"""
from __future__ import annotations

import os
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)")


def _build_app():
    from fastapi import FastAPI

    from src.api.cost_decisions import router as cost_router
    from src.api.org_routes import router as org_router
    from src.api.part_context import router as part_context_router
    from src.api.preferences import router as prefs_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(part_context_router, prefix="/api/v1/part-context")
    app.include_router(cost_router, prefix="/api/v1/cost-decisions")
    app.include_router(org_router, prefix="/api/v1/orgs")
    app.include_router(prefs_router, prefix="/api/v1/account/preferences")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


async def _seed(tag: str):
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    org = str(ULID())
    users = {}
    async with eng.get_session_factory()() as s:
        await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :sl, now())"),
                        {"id": org, "n": f"Spec {tag}", "sl": f"spec-{tag}"})
        for label, role, name in (("admin", "admin", "Ada Admin"), ("member", "member", None),
                                  ("viewer", "viewer", None)):
            email = f"spec-{tag}-{label}@example.com"
            uid = int((await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider, full_name) "
                "VALUES (:e, :el, 'analyst', 'password', :fn) RETURNING id"),
                {"e": email, "el": email, "fn": name})).first()[0])
            await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                                 "VALUES (:id, :o, :u, :r, now())"),
                            {"id": str(ULID()), "o": org, "u": uid, "r": role})
            users[label] = (uid, email)
        await s.commit()
    return org, users


async def _decision(org: str, uid: int, mesh: str, tag: str) -> str:
    import json

    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    ulid = str(ULID())
    async with eng.get_session_factory()() as s:
        await s.execute(text(
            "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, params_hash, engine_version, "
            "filename, file_type, result_json, created_at) VALUES (:u, :uid, :o, :m, :p, 'test', 'b.step', "
            "'step', CAST(:r AS jsonb), now() - interval '1 minute')"),
            {"u": ulid, "uid": uid, "o": org, "m": mesh, "p": f"p-{ulid}", "r": json.dumps({"estimates": []})})
        await s.commit()
    return ulid


async def _cleanup(org: str, users: dict):
    from sqlalchemy import text

    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(text("DELETE FROM cost_decisions WHERE org_id = :o"), {"o": org})
        await s.execute(text("DELETE FROM part_contexts WHERE org_id = :o"), {"o": org})
        await s.execute(text("DELETE FROM audit_log WHERE org_id = :o"), {"o": org})
        await s.execute(text("DELETE FROM memberships WHERE org_id = :o"), {"o": org})
        await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
        await s.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [u for u, _ in users.values()]})
        await s.commit()
    # Release the loop-bound async engine (repo convention for live-PG tests).
    await eng.dispose_engine()


@pytest.mark.asyncio
async def test_specs_signoff_and_staleness_end_to_end():
    from httpx import ASGITransport, AsyncClient

    tag = uuid.uuid4().hex[:10]
    org, users = await _seed(tag)
    admin, member, viewer = users["admin"][0], users["member"][0], users["viewer"][0]
    mesh, other = f"mesh-{tag}", f"other-{tag}"
    try:
        d1 = await _decision(org, member, mesh, tag)
        d_other = await _decision(org, member, other, tag)
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            _act_as(app, member)
            # --- specs: invalid is a 400 and stores nothing ----------------------
            r = await c.put(f"/api/v1/part-context/{mesh}", json={"part_specs": {"finishes": ["gold_leaf"]}})
            assert r.status_code == 400 and "unknown finishes value" in r.text

            # --- sign off the record before anything changes --------------------
            r = await c.get("/api/v1/orgs/signoff")
            assert r.status_code == 200
            assert r.json()["signoff_role"] == "member" and r.json()["can_sign_off"] is True
            assert r.json()["can_change"] is False
            r = await c.post(f"/api/v1/cost-decisions/{d1}/approve", json={"note": "Make it on the VF-2"})
            assert r.status_code == 200, r.text
            so = r.json()["signoff"]
            assert so["by"] == users["member"][1] and so["note"] == "Make it on the VF-2"
            assert so["at"] and so["stale"] is False

            # --- declare specs: normalized, read back, the part's records go stale
            specs = {"finishes": ["anodize_iii", "anodize_iii"], "ra_um": 32 * 0.0254, "ra_unit": "uin",
                     "inspection": ["standard", "fai_as9102"], "certifications": ["as9100", "nadcap"]}
            r = await c.put(f"/api/v1/part-context/{mesh}", json={"part_specs": specs})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["part_specs"] == {"finishes": ["anodize_iii"], "inspection": ["fai_as9102"],
                                          "certifications": ["as9100", "nadcap"],
                                          "ra_um": pytest.approx(0.8128), "ra_unit": "uin"}
            assert body["decisions_marked_stale"] == 1
            r = await c.get(f"/api/v1/part-context/{mesh}")
            assert r.json()["part_specs"]["finishes"] == ["anodize_iii"]

            r = await c.get(f"/api/v1/cost-decisions/{d1}")
            got = r.json()
            assert got["is_stale"] is True and got["stale_reason"] == "part_specs_changed"
            assert got["approval_status"] == "approved"
            assert got["signoff"]["stale"] is True and got["signoff"]["stale_reason"] == "part_specs_changed"
            # another part's record is untouched
            r = await c.get(f"/api/v1/cost-decisions/{d_other}")
            assert r.json()["is_stale"] is False

            # an identical PUT changes nothing and marks nothing
            r = await c.put(f"/api/v1/part-context/{mesh}", json={"part_specs": specs})
            assert "decisions_marked_stale" not in r.json()

            # an out-of-date record can't be signed off again
            r = await c.post(f"/api/v1/cost-decisions/{d1}/approve", json={})
            assert r.status_code == 409 and r.json()["detail"]["code"] == "decision_stale"

            # --- conditions change marks a fresh record with its own reason -----
            d2 = await _decision(org, member, mesh, tag)
            r = await c.put(f"/api/v1/part-context/{mesh}", json={"service_environment": {"max_temp_c": 150}})
            assert r.json()["decisions_marked_stale"] == 1
            r = await c.get(f"/api/v1/cost-decisions/{d2}")
            assert r.json()["stale_reason"] == "conditions_changed"

            # --- clearing specs: explicit null ---------------------------------
            r = await c.put(f"/api/v1/part-context/{mesh}", json={"part_specs": None})
            assert "part_specs" not in r.json()

            # --- only an org admin changes who may sign off ---------------------
            r = await c.put("/api/v1/orgs/signoff", json={"signoff_role": "admin"})
            assert r.status_code == 403
            _act_as(app, admin)
            r = await c.put("/api/v1/orgs/signoff", json={"signoff_role": "boss"})
            assert r.status_code == 400
            r = await c.put("/api/v1/orgs/signoff", json={"signoff_role": "admin"})
            assert r.status_code == 200 and r.json()["signoff_role"] == "admin"
            assert r.json()["label"] == "Admins only"

            d3 = await _decision(org, member, other, tag)
            _act_as(app, member)
            r = await c.get("/api/v1/orgs/signoff")
            assert r.json()["can_sign_off"] is False
            r = await c.post(f"/api/v1/cost-decisions/{d3}/approve", json={})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "signoff_role_required"
            _act_as(app, viewer)
            r = await c.post(f"/api/v1/cost-decisions/{d3}/approve", json={})
            assert r.status_code == 403
            _act_as(app, admin)
            r = await c.post(f"/api/v1/cost-decisions/{d3}/approve", json={"note": ""})
            assert r.status_code == 200
            assert r.json()["signoff"]["by"] == "Ada Admin" and r.json()["signoff"]["note"] is None
            # reopening needs the same role
            _act_as(app, member)
            r = await c.delete(f"/api/v1/cost-decisions/{d3}/approve")
            assert r.status_code == 403
            _act_as(app, admin)
            r = await c.delete(f"/api/v1/cost-decisions/{d3}/approve")
            assert r.status_code == 200 and r.json()["signoff"] is None
            r = await c.put("/api/v1/orgs/signoff", json={"signoff_role": None})
            assert r.json()["signoff_role"] == "member"

            # --- per-user length unit -------------------------------------------
            _act_as(app, member)
            r = await c.get("/api/v1/account/preferences")
            assert r.json() == {"length_unit": "mm"}
            r = await c.put("/api/v1/account/preferences", json={"length_unit": "in"})
            assert r.status_code == 200 and r.json() == {"length_unit": "in"}
            r = await c.get("/api/v1/account/preferences")
            assert r.json()["length_unit"] == "in"
            r = await c.put("/api/v1/account/preferences", json={"length_unit": "ft"})
            assert r.status_code == 422
            r = await c.put("/api/v1/account/preferences", json={"theme": "dark"})
            assert r.status_code == 422
            _act_as(app, admin)  # another person keeps their own setting
            assert (await c.get("/api/v1/account/preferences")).json()["length_unit"] == "mm"
    finally:
        await _cleanup(org, users)


def test_signoff_rules_are_pure():
    from src.services import signoff_service as so

    assert so.may_sign_off("member", None) and so.may_sign_off("admin", "member")
    assert not so.may_sign_off("viewer", "member") and not so.may_sign_off(None, None)
    assert not so.may_sign_off("member", "admin") and so.may_sign_off("admin", "admin")
    assert so.may_sign_off(None, "admin", is_superadmin=True)
    gov = {"approval_status": "approved", "approved_by_user_id": 7, "approved_at": "2026-10-22T10:00:00+00:00",
           "approval_note": "ok", "is_stale": True, "stale_reason": "calibration_changed", "stale_at": "x"}
    view = so.signoff_view(gov, {7: "Ada"})
    assert view == {"by_user_id": 7, "by": "Ada", "at": "2026-10-22T10:00:00+00:00", "note": "ok",
                    "stale": True, "stale_reason": "calibration_changed", "stale_at": "x"}
    assert so.signoff_view({"approval_status": "unreviewed"}, {}) is None


@pytest.mark.asyncio
async def test_pilot_report_decisions_carry_the_signoff_and_say_when_it_is_out_of_date():
    from sqlalchemy import text

    import src.db.engine as eng
    from src.services import pilot_report_service as pr

    tag = uuid.uuid4().hex[:10]
    org, users = await _seed(tag)
    admin = users["admin"][0]
    mesh = f"mesh-{tag}"
    try:
        d = await _decision(org, admin, mesh, tag)
        async with eng.get_session_factory()() as s:
            await s.execute(text(
                "UPDATE cost_decisions SET user_disposition = 'inhouse', disposition_updated_at = now(), "
                "approval_status = 'approved', approved_by_user_id = :u, approved_at = now(), "
                "approval_note = 'Run on cell 4', stale_at = now(), stale_reason = 'part_specs_changed' "
                "WHERE ulid = :d"), {"u": admin, "d": d})
            await s.commit()
            rows = await pr._decisions(s, org, {mesh}, {mesh: {"filename": "b.step"}})
        assert len(rows) == 1
        so = rows[0]["signoff"]
        assert so["by"] == "Ada Admin" and so["note"] == "Run on cell 4"
        assert so["stale"] is True and so["stale_reason"] == "part_specs_changed"
        html = pr.render_html({"organization": "Spec", "generated_at": "2026-10-22T00:00:00+00:00",
                               "scope": {"kind": "all", "quantity": 100}, "parts": 1, "buckets": [], "other": {},
                               "in_house": {"parts": 0, "machines": [], "materials": []}, "missing": [],
                               "outside": [], "wins": [], "decisions": rows, "accuracy": {}, "accuracy_rows": [],
                               "calibration": None, "caveats": [],
                               "signoffs": {"signed_off": 1, "out_of_date": 1, "recorded": 1}})
        assert "Ada Admin" in html and "Out of date: the part&#39;s specs changed" in html
    finally:
        await _cleanup(org, users)
