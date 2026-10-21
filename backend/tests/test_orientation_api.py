"""Re-checking a part in another orientation, through the real routes and Postgres.

* ``POST /validate?orientation=…`` and ``POST /validate/cost`` with an
  ``orientation`` field turn the part before the check; the result and the
  saved records say which orientation they used, and read back the same.
* The same file in another orientation is the same part: it uses no check,
  even when the allowance is spent (a different file is still refused).
* ``GET /parts/{hash}/orientations`` compares ways to lay the kept file down
  and never counts as a check.

Skipped unless DATABASE_URL is Postgres at schema head.
"""
from __future__ import annotations

import io
import os
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(not _PG, reason="requires Postgres (DATABASE_URL=postgresql://...)")


def _gamma_stl() -> bytes:
    import trimesh

    column = trimesh.creation.box((10, 20, 40))
    column.apply_translation((5, 10, 20))
    arm = trimesh.creation.box((40, 20, 10))
    arm.apply_translation((20, 10, 35))
    mesh = trimesh.boolean.union([column, arm])
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    return buf.getvalue()


def _app(user_id: int):
    from fastapi import FastAPI

    from src.api.cost_decisions import router as decisions_router
    from src.api.part_orientation import router as orientation_router
    from src.api.routes import router as api_router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(decisions_router, prefix="/api/v1/cost-decisions")
    app.include_router(orientation_router, prefix="/api/v1/parts")
    # Real sessions (get_db_session commits before the response), real allowance.
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst")
    return app


def _fdm_codes(result: dict) -> set[str]:
    ps = next(p for p in result["process_scores"] if p["process"] == "fdm")
    return {i["code"] for i in ps["issues"]}


@_requires_pg
@pytest.mark.asyncio
async def test_a_turned_recheck_is_recorded_and_uses_no_check():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select, text
    from ulid import ULID

    import src.db.engine as eng
    from src.auth import validation_caps as vc
    from src.db.models import Analysis, CostDecision
    from src.services.analysis_service import compute_mesh_hash

    tag = uuid.uuid4().hex[:10]
    sf = eng.get_session_factory()
    org = str(ULID())
    async with sf() as s:
        await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:i, :n, :s, now())"),
                        {"i": org, "n": f"Orient {tag}", "s": f"orient-{tag}"})
        email = f"orient-{tag}@gmail.com"
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider, plan) "
            "VALUES (:e, :e, 'analyst', 'password', 'trial') RETURNING id"), {"e": email})).first()[0])
        await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                             "VALUES (:i, :o, :u, 'admin', now())"), {"i": str(ULID()), "o": org, "u": uid})
        await s.commit()

    data = _gamma_stl()
    digest = compute_mesh_hash(data)
    files = lambda: {"file": ("gamma.stl", data, "model/stl")}  # noqa: E731
    run = lambda: {"x-part-check-id": str(uuid.uuid4())}  # noqa: E731
    app = _app(uid)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # The first check of the part, in the file's own orientation.
        first_run = run()
        v0 = await client.post("/api/v1/validate", files=files(), headers=first_run)
        assert v0.status_code == 200, v0.text
        v0 = v0.json()
        assert "orientation" not in v0
        assert "OVERHANG" in _fdm_codes(v0)
        assert v0["geometry"]["bounding_box_mm"] == [40.0, 20.0, 40.0]
        c0 = await client.post("/api/v1/validate/cost", files=files(), headers=first_run,
                               data={"qty": "1,100", "material_class": "polymer"})
        assert c0.status_code == 200, c0.text
        c0 = c0.json()
        usage = await vc.user_trial_usage(uid)
        assert usage["used"] == 1
        # Spend the rest of the allowance on other files.
        for _ in range(usage["remaining"]):
            other = str(uuid.uuid4())
            assert await vc.reserve_check(uid, other, f"other-{uuid.uuid4().hex}", "analysis")
            await vc.finish_check(uid, other, "analysis", True)
        assert (await vc.user_trial_usage(uid))["remaining"] == 0

        # Laid on its side: the same file, a new browser run, no check left.
        turned_run = run()
        v1 = await client.post("/api/v1/validate", params={"orientation": "down:0,-1,0"},
                               files=files(), headers=turned_run)
        assert v1.status_code == 200, v1.text
        v1 = v1.json()
        o = v1["orientation"]
        assert (o["label"], o["exact"], o["key"]) == ("File +Y up", True, "rotation:1,0,0,0,0,-1,0,1,0")
        assert o["up_in_file"] == [0.0, 1.0, 0.0]
        assert "OVERHANG" not in _fdm_codes(v1)
        assert v1["geometry"]["bounding_box_mm"] == [40.0, 40.0, 20.0]
        assert v1["geometry"]["volume_mm3"] == v0["geometry"]["volume_mm3"]
        # Same faces in the same order: the file's own 3D view still lines up.
        assert v1["analysis_mesh_hash"] == v0["analysis_mesh_hash"] == o["file_face_hash"]
        assert v1["geometry"]["center_of_mass"] == pytest.approx(v0["geometry"]["center_of_mass"], abs=0.02)
        c1 = await client.post("/api/v1/validate/cost", files=files(), headers=turned_run,
                               data={"qty": "1,100", "material_class": "polymer", "orientation": "down:0,-1,0"})
        assert c1.status_code == 200, c1.text
        c1 = c1.json()
        assert c1["orientation"]["key"] == o["key"]
        price = lambda c: sorted((e["process"], e["quantity"], e["unit_cost_usd"]) for e in c["estimates"])  # noqa: E731
        assert price(c1) == price(c0)
        assert c1["saved"]["id"] != c0["saved"]["id"]
        # Asking again in that orientation is the saved answer.
        v2 = await client.post("/api/v1/validate", params={"orientation": "turns:x90"}, files=files(), headers=run())
        assert v2.status_code == 200
        assert {**v2.json(), "analysis_time_ms": 0} == {**v1, "analysis_time_ms": 0}

        usage = await vc.user_trial_usage(uid)
        assert (usage["used"], usage["remaining"]) == (1 + _filled(usage), 0)
        refused = await client.post("/api/v1/validate", files={"file": ("new.stl", data + b" ", "model/stl")}, headers=run())
        assert refused.status_code == 403

        # The records say which orientation they used, and read back the same.
        record = await client.get(f"/api/v1/cost-decisions/{c1['saved']['id']}")
        assert record.status_code == 200, record.text
        assert record.json()["result"]["orientation"] == c1["orientation"]
        async with sf() as s:
            rows = (await s.execute(select(Analysis).where(Analysis.org_id == org, Analysis.mesh_hash == digest)
                                    .order_by(Analysis.id))).scalars().all()
            assert [r.result_json.get("orientation", {}).get("key") for r in rows] == [None, o["key"]]
            decisions = (await s.execute(select(CostDecision).where(CostDecision.org_id == org)
                                         .order_by(CostDecision.created_at))).scalars().all()
            assert [d.result_json.get("orientation", {}).get("label") for d in decisions] == [None, "File +Y up"]

        # Bad input is a plain 400.
        bad = await client.post("/api/v1/validate", params={"orientation": "rotation:1,0,0,0,1,0,0,0,-1"},
                                files=files(), headers=run())
        assert bad.status_code == 400 and "mirrors" in bad.text

        # Comparing ways to lay the kept file down: never a check.
        before = await vc.user_trial_usage(uid)
        cmp = await client.get(f"/api/v1/parts/{digest}/orientations")
        assert cmp.status_code == 200, cmp.text
        cmp = cmp.json()
        assert cmp["best"]["fdm"] == "down-y"
        side = {c["id"]: c for c in cmp["candidates"]}
        assert side["down-z"]["support"]["fdm"]["area_mm2"] == pytest.approx(600.0)
        assert side["down-y"]["orientation"] == o["key"]
        assert await vc.user_trial_usage(uid) == before
        assert (await client.get(f"/api/v1/parts/{'0' * 64}/orientations")).status_code == 404


def _filled(usage: dict) -> int:
    """Files counted besides the part itself (the allowance spent on other files)."""
    return usage["used"] - 1
