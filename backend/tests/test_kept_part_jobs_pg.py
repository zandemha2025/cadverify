"""A big kept part re-priced or repaired on the worker, from its kept file.

Real Postgres, the real routes, the real worker task and engine:
POST /api/v1/parts/{hash}/recheck (or /repair) on a part whose kept file is
beyond a web request's limits -> 202 with the job, the file not read in the
request -> run_stored_check (which hands a kept-part job to kept_part_tasks) ->
GET /api/v1/checks/{id} with the route's own response as ``result``. Also: the
same ask twice is one job, a part under the limits still answers in the
request, the honest refusal over the worker's memory, and nothing charged.

Skipped unless DATABASE_URL is PostgreSQL at schema head.
"""
from __future__ import annotations

import hashlib
import os
import uuid

import pytest
import pytest_asyncio
import trimesh

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head")]


def _box(extents=(40, 30, 20), *, open_face: bool = False) -> bytes:
    mesh = trimesh.creation.box(extents=extents)
    if open_face:
        mesh.update_faces([i for i in range(len(mesh.faces)) if i not in (0, 1)])
    return mesh.export(file_type="stl")


class _Pool:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args))
        return object()


@pytest_asyncio.fixture
async def world(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    import src.jobs.arq_backend as arq_backend
    from src.api.checks import router as checks_router
    from src.api.part_fixes import router as fixes_router
    from src.api.part_recheck import router as recheck_router
    from src.auth import free_tool_limits
    from src.auth.rate_limit import limiter
    from src.services.source_artifact_service import save_source_artifact

    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("SOURCE_ARTIFACT_BLOB_DIR", str(tmp_path / "sources"))
    monkeypatch.setenv("ADMISSION_DISABLED", "1")
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.delenv("CHECK_MEMORY_BUDGET_MB", raising=False)
    # Every kept file counts as big here (the real threshold is 20 MB).
    monkeypatch.setenv("KEPT_PART_WORKER_FROM_MB", "0.0001")
    pool = _Pool()

    async def _get_pool():
        return pool

    monkeypatch.setattr(arq_backend, "get_arq_pool", _get_pool)
    await eng.dispose_engine()
    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :n, now())"),
                        {"id": org, "n": f"kept-{tag}"})
        uid = (await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider, plan, phone_verified_at, current_org_id) "
            "VALUES (:e, :e, 'analyst', 'password', 'trial', now(), :o) RETURNING id"),
            {"e": f"kept-{tag}@acme-aero.com", "o": org})).scalar_one()
        await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                             "VALUES (:id, :o, :u, 'member', now())"), {"id": str(ULID()), "o": org, "u": uid})
    parts = {}
    for label, raw in (("solid", _box()), ("open", _box((30, 30, 10), open_face=True))):
        digest = hashlib.sha256(raw).hexdigest()
        await save_source_artifact(org, digest, f"{label}-bracket.stl", raw)
        parts[label] = digest

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(recheck_router, prefix="/api/v1/parts")
    app.include_router(fixes_router, prefix="/api/v1/parts")
    app.include_router(checks_router)
    for dependency in free_tool_limits.ALL:
        app.dependency_overrides[dependency] = lambda: None
    try:
        yield {"app": app, "org": org, "uid": uid, "parts": parts, "pool": pool}
    finally:
        async with eng.get_session_factory()() as s, s.begin():
            await s.execute(text("DELETE FROM jobs WHERE user_id = :u"), {"u": uid})
            await s.execute(text("DELETE FROM audit_log WHERE user_id = :u OR org_id = :o"), {"u": uid, "o": org})
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await eng.dispose_engine()


def _client(app, uid: int):
    from httpx import ASGITransport, AsyncClient

    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=uid, api_key_id=0, key_prefix="session", role="analyst")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=600)


def _count_reads(monkeypatch):
    """How many times the kept file's bytes are read (sizing reads only its first bytes)."""
    from src.services import source_artifact_service as sources

    reads = {"n": 0}
    real = sources.read_source_artifact

    async def counted(*args, **kwargs):
        reads["n"] += 1
        return await real(*args, **kwargs)

    monkeypatch.setattr(sources, "read_source_artifact", counted)
    return reads


async def _count(sql: str, **params) -> int:
    from sqlalchemy import text

    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        return int((await s.execute(text(sql), params)).scalar_one())


async def test_a_big_kept_part_is_repriced_on_the_worker(world, monkeypatch):
    from src.jobs.stored_check_tasks import run_stored_check

    app, uid, digest = world["app"], world["uid"], world["parts"]["solid"]
    reads = _count_reads(monkeypatch)
    async with _client(app, uid) as ac:
        r = await ac.post(f"/api/v1/parts/{digest}/recheck?qty=10,1000&material_class=aluminum")
        assert r.status_code == 202, r.text
        job = r.json()
        assert job["source"] == "kept" and job["action"] == "recheck" and job["status"] == "queued"
        assert job["mesh_hash"] == digest and job["filename"] == "part.stl" and job["material_class"] == "aluminum"
        assert reads["n"] == 0, "the web request never reads a big kept file"
        assert world["pool"].jobs == [("run_stored_check", (job["check_id"],))]
        # The same ask while it waits is the same job; another material is its own.
        again = await ac.post(f"/api/v1/parts/{digest}/recheck?qty=10,1000&material_class=aluminum")
        assert again.status_code == 202 and again.json()["check_id"] == job["check_id"]
        other = await ac.post(f"/api/v1/parts/{digest}/recheck?qty=10,1000&material_class=steel")
        assert other.json()["check_id"] != job["check_id"]
        # A bad option is refused in the request, before any job.
        assert (await ac.post(f"/api/v1/parts/{digest}/recheck?material_class=unobtainium")).status_code == 400

        assert (await run_stored_check({}, job["check_id"])) == {"ok": True}
        assert reads["n"] == 1
        done = (await ac.get(f"/api/v1/checks/{job['check_id']}")).json()
        assert done["status"] == "done" and done["stage"] == "done" and done["summary"] == "Re-priced"
        assert done["part_url"] == f"/app/part/{digest}"
        result = done["result"]
        assert result["quantities"] == [10, 1000] and result["material_class"] == "aluminum"
        assert any(e.get("unit_cost_usd") for e in result["estimates"])
        assert result["recheck"]["checks_used"] == 0 and result["recheck"]["source"] == "kept"
        assert done["error"] is None
        # The work bar's list shows it without the heavy result.
        listed = (await ac.get("/api/v1/checks")).json()["checks"]
        row = next(c for c in listed if c["check_id"] == job["check_id"])
        assert row["action"] == "recheck" and "result" not in row
    # Saved like the one-request re-price, and no check used.
    assert await _count("SELECT count(*) FROM cost_decisions WHERE org_id=:o AND mesh_hash=:h",
                        o=world["org"], h=digest) >= 1
    assert await _count("SELECT count(*) FROM trial_checks WHERE user_id=:u", u=uid) == 0


async def test_a_big_kept_part_is_repaired_on_the_worker(world):
    from src.jobs.stored_check_tasks import run_stored_check
    from src.services import cad_fix_service as fx

    app, uid, org, digest = world["app"], world["uid"], world["org"], world["parts"]["open"]
    async with _client(app, uid) as ac:
        r = await ac.post(f"/api/v1/parts/{digest}/repair?qty=10&material_class=polymer")
        assert r.status_code == 202, r.text
        job = r.json()
        assert job["action"] == "repair" and job["source"] == "kept"
        assert (await run_stored_check({}, job["check_id"])) == {"ok": True}
        done = (await ac.get(f"/api/v1/checks/{job['check_id']}")).json()
    assert done["status"] == "done", done
    result = done["result"]
    assert result["outcome"] in ("repaired", "closed_changed"), result.get("summary")
    fixed = result["repaired"]["mesh_hash"]
    assert done["part_url"] == f"/app/part/{fixed}" and done["summary"].startswith("Repaired")
    assert result["repaired_file_b64"] is None and result["download"]["url"] == f"/api/v1/parts/{fixed}/fixed-file"
    assert result["repair_verification"]["checks_used"] == 0
    link = await fx._get_json(fx._record_key(org, fixed, "derived-from.json"))
    assert link["parent_mesh_hash"] == digest
    assert await _count("SELECT count(*) FROM trial_checks WHERE user_id=:u", u=uid) == 0


async def test_over_the_workers_memory_it_says_so_and_charges_nothing(world, monkeypatch):
    from src.jobs.stored_check_tasks import run_stored_check

    app, uid, digest = world["app"], world["uid"], world["parts"]["solid"]
    async with _client(app, uid) as ac:
        job = (await ac.post(f"/api/v1/parts/{digest}/recheck?qty=10")).json()
        monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "64")  # this worker's budget
        assert (await run_stored_check({}, job["check_id"]))["code"] == "CHECK_TOO_LARGE"
        failed = (await ac.get(f"/api/v1/checks/{job['check_id']}")).json()
    assert failed["status"] == "failed" and failed["error"]["code"] == "CHECK_TOO_LARGE"
    assert "Nothing was charged" in failed["error"]["message"] and failed["error"]["charged"] is False
    assert "result" not in failed and failed["part_url"] is None
    assert await _count("SELECT count(*) FROM cost_decisions WHERE org_id=:o", o=world["org"]) == 0


async def test_a_kept_part_within_the_web_limits_still_answers_in_the_request(world, monkeypatch):
    monkeypatch.delenv("KEPT_PART_WORKER_FROM_MB")
    app, uid, digest = world["app"], world["uid"], world["parts"]["solid"]
    async with _client(app, uid) as ac:
        r = await ac.post(f"/api/v1/parts/{digest}/recheck?qty=10")
        assert r.status_code == 200, r.text
        assert r.json()["recheck"]["checks_used"] == 0
        # Over the request's memory budget it goes to the worker even under 20 MB.
        monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "64")
        r = await ac.post(f"/api/v1/parts/{digest}/recheck?qty=10")
        assert r.status_code == 202 and r.json()["action"] == "recheck"
    assert world["pool"].jobs and world["pool"].jobs[-1][0] == "run_stored_check"
