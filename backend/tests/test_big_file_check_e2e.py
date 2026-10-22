"""Big files end to end: a part uploaded in parts, resumed, checked on the worker.

Real Postgres, the real router stack and the real worker task and engine:
POST /api/v1/uploads/multipart (purpose 'part') -> PUT each part through the
API (the local backend's relay) -> GET parts (resume) -> complete ->
POST /api/v1/checks -> run_stored_check -> GET /api/v1/checks/{id}. Also the
compressed forms, the honest refusal over the memory budget, the allowance,
the free plan's upload admission, who may upload a batch ZIP, and org scoping.

Skipped unless DATABASE_URL is PostgreSQL at schema head (0055+).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import os
import uuid
import zipfile

import pytest
import pytest_asyncio
import trimesh

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (DATABASE_URL=postgresql://...)")

BAMBU = {
    "name": "Bambu Lab X1C", "process": "fdm", "count": 1,
    "capabilities": {"x": 256.0, "y": 256.0, "z": 256.0, "min_layer_um": 40.0, "max_layer_um": 400.0,
                     "min_feature_mm": 0.4, "maker_spec": {"catalog": "Bambu Lab X1C", "fields": ["materials"]}},
    "materials": ["PLA", "PETG", "ABS"],
}


def _stl(extents=(40, 30, 20), seed: int = 0) -> bytes:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_scale(1.0 + seed * 1e-4)
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
    from src.api.uploads import router as uploads_router
    from src.auth.rate_limit import limiter
    from src.services import machine_inventory_service as machines

    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("DIRECT_UPLOAD_LOCAL_ROOT", str(tmp_path / "incoming"))
    monkeypatch.setenv("SOURCE_ARTIFACT_BLOB_DIR", str(tmp_path / "sources"))
    monkeypatch.setenv("RELEASE", "dev")
    monkeypatch.setenv("DIRECT_UPLOAD_PART_SIZE_BYTES", str(5 * 1024 * 1024))
    monkeypatch.delenv("SMS_VERIFICATION_REQUIRED", raising=False)
    monkeypatch.delenv("CHECK_MEMORY_BUDGET_MB", raising=False)
    pool = _Pool()

    async def _get_pool():
        return pool

    monkeypatch.setattr(arq_backend, "get_arq_pool", _get_pool)

    await eng.dispose_engine()
    tag = uuid.uuid4().hex[:10]
    orgs = {"main": str(ULID()), "other": str(ULID())}
    users: dict[str, int] = {}
    async with eng.get_session_factory()() as s, s.begin():
        for k, org in orgs.items():
            await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :n, now())"),
                            {"id": org, "n": f"big-{k}-{tag}"})
        for label, email, plan, org in (("work", f"eng-{tag}@acme-aero.com", "trial", orgs["main"]),
                                        ("personal", f"me-{tag}@gmail.com", "trial", orgs["main"]),
                                        ("pilot", f"pilot-{tag}@acme-aero.com", "pilot", orgs["main"]),
                                        ("stranger", f"x-{tag}@other-co.com", "pilot", orgs["other"])):
            uid = (await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider, plan, phone_verified_at, current_org_id) "
                "VALUES (:e, :e, 'analyst', 'password', :p, now(), :o) RETURNING id"
            ), {"e": email, "p": plan, "o": org})).scalar_one()
            await s.execute(text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:id, :o, :u, 'admin', now())"
            ), {"id": str(ULID()), "o": org, "u": uid})
            users[label] = uid
        await machines.create_machine(s, orgs["main"], dict(BAMBU), created_by=users["work"])

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(uploads_router)
    app.include_router(checks_router)
    try:
        yield {"app": app, "orgs": orgs, "users": users, "pool": pool, "tmp": tmp_path}
    finally:
        async with eng.get_session_factory()() as s, s.begin():
            ids = list(users.values())
            await s.execute(text("DELETE FROM jobs WHERE user_id = ANY(:u)"), {"u": ids})
            await s.execute(text("DELETE FROM direct_uploads WHERE user_id = ANY(:u)"), {"u": ids})
            await s.execute(text("DELETE FROM trial_checks WHERE user_id = ANY(:u)"), {"u": ids})
            await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": list(orgs.values())})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": ids})
        await eng.dispose_engine()


def _client(app, uid: int):
    from httpx import ASGITransport, AsyncClient

    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=uid, api_key_id=0, key_prefix="session", role="analyst"
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _initiate(ac, name: str, data: bytes, *, key: str | None = None, checksum: str | None = None, purpose="part"):
    return await ac.post(
        "/api/v1/uploads/multipart",
        headers={"Idempotency-Key": key or f"test-{uuid.uuid4().hex}"},
        json={"purpose": purpose, "filename": name, "content_type": "",
              "size_bytes": len(data), "checksum_sha256": checksum or hashlib.sha256(data).hexdigest()},
    )


async def _put_parts(ac, up: dict, data: bytes, numbers=None) -> dict[int, str]:
    size = up["part_size_bytes"]
    etags = {}
    for p in up["parts"]:
        n = p["part_number"]
        if numbers is not None and n not in numbers:
            continue
        r = await ac.put(p["url"], content=data[(n - 1) * size: n * size])
        assert r.status_code == 200, r.text
        assert r.headers["etag"] == r.json()["etag"]
        etags[n] = r.headers["etag"]
    return etags


async def _upload(ac, name: str, data: bytes, **kw) -> dict:
    r = await _initiate(ac, name, data, **kw)
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["transport"] == "relay"
    etags = await _put_parts(ac, up, data)
    r = await ac.post(up["complete_url"], json={"parts": [{"part_number": n, "etag": e} for n, e in sorted(etags.items())]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
    return up


async def _check(world, ac, upload_id: str, **options) -> dict:
    from src.jobs.stored_check_tasks import run_stored_check

    r = await ac.post("/api/v1/checks", json={"direct_upload_id": upload_id, **options})
    assert r.status_code == 202, r.text
    started = r.json()
    assert started["status"] == "queued" and started["stage"] == "queued"
    assert world["pool"].jobs[-1] == ("run_stored_check", (started["check_id"],))
    await run_stored_check({}, started["check_id"])
    r = await ac.get(f"/api/v1/checks/{started['check_id']}")
    assert r.status_code == 200, r.text
    return r.json()


async def _upload_row(upload_id: str):
    from sqlalchemy import select

    import src.db.engine as eng
    from src.db.models import DirectUpload

    async with eng.get_session_factory()() as s:
        return (await s.execute(select(DirectUpload).where(DirectUpload.ulid == upload_id))).scalar_one()


async def _usage(uid: int) -> dict:
    from src.auth.validation_caps import user_trial_usage

    return await user_trial_usage(uid)


@pytest.mark.asyncio
async def test_a_part_is_uploaded_checked_on_the_worker_and_kept(world):
    uid = world["users"]["work"]
    data = _stl()
    async with _client(world["app"], uid) as ac:
        caps = (await ac.get("/api/v1/uploads/capabilities?purpose=part")).json()
        assert caps["available"] and caps["transport"] == "relay" and caps["max_size_bytes"] == 2 * 1024**3
        assert caps["max_active_uploads_per_org"] == 2  # a free account's organization
        up = await _upload(ac, "bracket.stl", data)
        done = await _check(world, ac, up["upload_id"], material_class="polymer", qty="10,100")

    assert done["status"] == "done", done
    key = hashlib.sha256(data).hexdigest()
    assert done["mesh_hash"] == key and done["part_url"] == f"/app/part/{key}"
    assert done["analysis_id"] and done["cost_decision_id"]
    assert set(done["timings_ms"]) >= {"verifying", "sizing", "measuring", "pricing"}
    assert done["memory"]["need_bytes"] < done["memory"]["budget_bytes"]

    # The org keeps the part's source; the incoming copy is gone.
    from src.services.source_artifact_service import find_source_artifact_suffix

    assert await find_source_artifact_suffix(world["orgs"]["main"], key) == ".stl"
    row = await _upload_row(up["upload_id"])
    assert row.status == "consumed" and row.storage_cleaned_at is not None
    assert not (world["tmp"] / "incoming" / row.object_key).exists()

    # One check used, as an upload of the same file would.
    usage = await _usage(uid)
    assert usage["used"] == 1 and usage["reserved"] == 0

    # Starting again on the same upload is the same check.
    async with _client(world["app"], uid) as ac:
        r = await ac.post("/api/v1/checks", json={"direct_upload_id": up["upload_id"]})
        assert r.status_code == 200 and r.json()["check_id"] == done["check_id"]
        listed = (await ac.get("/api/v1/checks")).json()["checks"]
        assert [c["check_id"] for c in listed] == [done["check_id"]]


@pytest.mark.asyncio
async def test_an_interrupted_upload_resumes_with_only_the_missing_parts(world):
    uid = world["users"]["pilot"]
    data = os.urandom(11 * 1024 * 1024)  # three 5 MiB parts
    key = f"resume-{uuid.uuid4().hex}"
    async with _client(world["app"], uid) as ac:
        r = await _initiate(ac, "assembly.step", data, key=key)
        up = r.json()
        assert up["part_count"] == 3 and up["part_size_bytes"] == 5 * 1024 * 1024
        first = await _put_parts(ac, up, data, numbers={1, 3})
        # The connection drops; a reload asks what arrived.
        got = (await ac.get(f"/api/v1/uploads/{up['upload_id']}/parts")).json()
        assert [p["part_number"] for p in got["parts"]] == [1, 3]
        assert [p["etag"] for p in got["parts"]] == [first[1], first[3]]
        # Re-initiating with the same key is the same upload, with every part URL.
        again = (await _initiate(ac, "assembly.step", data, key=key)).json()
        assert again["upload_id"] == up["upload_id"] and again["idempotent_replay"] is True
        rest = await _put_parts(ac, again, data, numbers={2})
        # A wrong-sized part and a part out of range are refused.
        bad = await ac.put(f"/api/v1/uploads/{up['upload_id']}/parts/2", content=b"short")
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "DIRECT_UPLOAD_PART_SIZE"
        out = await ac.put(f"/api/v1/uploads/{up['upload_id']}/parts/4", content=b"x")
        assert out.status_code == 422
        etags = {**first, **rest}
        r = await ac.post(up["complete_url"], json={"parts": [{"part_number": n, "etag": e} for n, e in sorted(etags.items())]})
        assert r.status_code == 200 and r.json()["status"] == "completed"
        late = await ac.put(f"/api/v1/uploads/{up['upload_id']}/parts/1", content=data[: 5 * 1024 * 1024])
        assert late.status_code == 409

    import src.services.direct_upload_service as svc

    row = await _upload_row(up["upload_id"])
    path = svc.download_to_bounded_tempfile(row)
    try:
        assert hashlib.sha256(open(path, "rb").read()).hexdigest() == hashlib.sha256(data).hexdigest()
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_a_damaged_upload_fails_its_checksum_and_charges_nothing(world):
    uid = world["users"]["work"]
    data = _stl(seed=3)
    async with _client(world["app"], uid) as ac:
        up = await _upload(ac, "bracket.stl", data, checksum="0" * 64)
        done = await _check(world, ac, up["upload_id"])
    assert done["status"] == "failed" and done["error"]["code"] == "DIRECT_UPLOAD_CHECKSUM_MISMATCH"
    assert done["error"]["charged"] is False
    assert (await _usage(uid))["used"] == 0
    row = await _upload_row(up["upload_id"])
    assert row.status == "failed" and row.storage_cleaned_at is not None


@pytest.mark.asyncio
async def test_gzipped_and_zipped_parts_unpack_on_the_worker(world):
    uid = world["users"]["pilot"]
    data = _stl(seed=5)
    one = io.BytesIO()
    with zipfile.ZipFile(one, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Bracket/bracket.stl", data)
        z.writestr("__MACOSX/._bracket.stl", b"junk")
    two = io.BytesIO()
    with zipfile.ZipFile(two, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.stl", data)
        z.writestr("b.stl", _stl(seed=6))
    async with _client(world["app"], uid) as ac:
        gz = await _check(world, ac, (await _upload(ac, "bracket.stl.gz", gzip.compress(data)))["upload_id"])
        zp = await _check(world, ac, (await _upload(ac, "bracket.zip", one.getvalue()))["upload_id"])
        many = await _check(world, ac, (await _upload(ac, "two-parts.zip", two.getvalue()))["upload_id"])
    key = hashlib.sha256(data).hexdigest()
    for done in (gz, zp):
        assert done["status"] == "done", done
        assert done["mesh_hash"] == key and done["part_filename"] == "bracket.stl" and done["part_bytes"] == len(data)
        assert "unpacking" in done["timings_ms"]
    assert many["status"] == "failed" and many["error"]["code"] == "ARCHIVE_MANY_PARTS"
    assert "catalog run" in many["error"]["message"]


@pytest.mark.asyncio
async def test_a_file_over_the_memory_budget_is_refused_with_how_much_it_needs(world, monkeypatch):
    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "64")
    uid = world["users"]["work"]
    async with _client(world["app"], uid) as ac:
        done = await _check(world, ac, (await _upload(ac, "huge.stl", _stl(seed=7)))["upload_id"])
    assert done["status"] == "failed" and done["error"]["code"] == "CHECK_TOO_LARGE"
    message = done["error"]["message"]
    assert message.startswith("This file needs about ") and "the largest STL file ScaleCAD checks today is about" in message
    assert "Nothing was charged" in message
    assert done["memory"]["need_bytes"] > done["memory"]["budget_bytes"] == 64 * 1024 * 1024
    assert (await _usage(uid))["used"] == 0


@pytest.mark.asyncio
async def test_the_check_uses_the_allowance_like_an_upload(world):
    from sqlalchemy import text

    import src.db.engine as eng

    uid = world["users"]["work"]
    async with eng.get_session_factory()() as s, s.begin():
        for i in range(15):
            await s.execute(text(
                "INSERT INTO trial_checks (user_id, check_id, file_hash, created_at, completed, operations) "
                "VALUES (:u, :c, :h, now(), true, '{}'::jsonb)"
            ), {"u": uid, "c": str(uuid.uuid4()), "h": hashlib.sha256(f"used-{i}".encode()).hexdigest()})
    async with _client(world["app"], uid) as ac:
        done = await _check(world, ac, (await _upload(ac, "one-more.stl", _stl(seed=8)))["upload_id"])
    assert done["status"] == "failed" and done["error"]["code"] == "user_validation_cap_exceeded"
    assert "free checks" in done["error"]["message"]


@pytest.mark.asyncio
async def test_free_organizations_upload_two_at_a_time_and_batch_zips_need_a_catalog_run(world):
    data = b"solid x\nendsolid x\n" * 10
    async with _client(world["app"], world["users"]["work"]) as ac:
        assert (await _initiate(ac, "a.stl", data)).status_code == 201
        assert (await _initiate(ac, "b.stl", data)).status_code == 201
        third = await _initiate(ac, "c.stl", data)
        assert third.status_code == 429 and third.json()["detail"]["code"] == "DIRECT_UPLOAD_ADMISSION_LIMIT"
    async with _client(world["app"], world["users"]["personal"]) as ac:
        zip_refused = await _initiate(ac, "parts.zip", b"PK\x05\x06" + b"\0" * 18, purpose="batch_zip")
        assert zip_refused.status_code == 403 and zip_refused.json()["detail"]["code"] == "paid_access_required"
        bad = await _initiate(ac, "notes.txt", data)
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "DIRECT_UPLOAD_INVALID_FILENAME"
        huge = await ac.post("/api/v1/uploads/multipart", headers={"Idempotency-Key": f"huge-{uuid.uuid4().hex}"}, json={
            "purpose": "part", "filename": "huge.step", "content_type": "", "size_bytes": 2 * 1024**3 + 1,
            "checksum_sha256": "a" * 64})
        assert huge.status_code == 413 and "the largest single file ScaleCAD takes is 2 GB" in huge.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_uploads_and_checks_belong_to_their_organization(world):
    data = _stl(seed=9)
    async with _client(world["app"], world["users"]["pilot"]) as ac:
        up = await _upload(ac, "mine.stl", data)
        mine = await _check(world, ac, up["upload_id"])
    async with _client(world["app"], world["users"]["stranger"]) as ac:
        assert (await ac.get(f"/api/v1/checks/{mine['check_id']}")).status_code == 404
        assert (await ac.get(f"/api/v1/uploads/{up['upload_id']}/parts")).status_code == 404
        assert (await ac.post("/api/v1/checks", json={"direct_upload_id": up["upload_id"]})).status_code == 404
        assert (await ac.get("/api/v1/checks")).json()["checks"] == []
