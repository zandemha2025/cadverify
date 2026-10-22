"""The catalog run end to end against live Postgres and the real engine.

POST /api/v1/catalog-runs (ZIP + parts list) -> the free allowance reserves
the new parts in the batch's own transaction -> each item runs in the worker
(the DFM analysis and the cost decision with the org's machines, the single
check's own code paths) -> GET /batch/{id}/catalog sorts the parts, resources
first -> the CSV. Also: the 51st part refused, a re-run free, a broken file
giving its slot back, personal email refused, pilot unlimited.

Skipped unless DATABASE_URL is PostgreSQL at schema head (0052+).
"""
from __future__ import annotations

import io
import os
import uuid
import zipfile

import pytest
import pytest_asyncio
import trimesh

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (DATABASE_URL=postgresql://...)")

HAAS = {
    "name": "Haas VF-2", "process": "cnc_3axis", "count": 1, "max_workpiece_kg": 1361.0,
    "capabilities": {"x": 762.0, "y": 406.0, "z": 508.0, "axes": 3,
                     "maker_spec": {"catalog": "Haas VF-2", "fields": ["max_workpiece_kg", "materials"]}},
    "materials": ["aluminum", "steel"],
}
BAMBU = {
    "name": "Bambu Lab X1C", "process": "fdm", "count": 1,
    "capabilities": {"x": 256.0, "y": 256.0, "z": 256.0, "min_layer_um": 40.0, "max_layer_um": 400.0,
                     "min_feature_mm": 0.4, "maker_spec": {"catalog": "Bambu Lab X1C", "fields": ["materials"]}},
    "materials": ["PLA", "PETG", "ABS", "Nylon (PA6)", "TPU 95A"],
}


def _stl(extents, *, seed: int = 0) -> bytes:
    mesh = trimesh.creation.box(extents=extents)
    # A distinct file per seed: same shape, a slightly different size.
    mesh.apply_scale(1.0 + seed * 1e-4)
    return mesh.export(file_type="stl")


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class _Pool:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args))


@pytest_asyncio.fixture
async def world(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.api.batch_router import router as batch_router
    from src.auth.rate_limit import limiter
    from src.services import machine_inventory_service as machines

    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BATCH_BLOB_DIR", str(tmp_path / "batch"))
    monkeypatch.delenv("SMS_VERIFICATION_REQUIRED", raising=False)
    monkeypatch.delenv("FREE_CATALOG_PARTS", raising=False)
    pool = _Pool()

    async def _get_pool():
        return pool

    import src.jobs.arq_backend as arq_backend
    monkeypatch.setattr(arq_backend, "get_arq_pool", _get_pool)

    await eng.dispose_engine()  # a pool left by another test's event loop
    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    users: dict[str, int] = {}
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :n, now())"),
                        {"id": org, "n": f"catalog-{tag}"})
        for label, email, plan in (("work", f"ops-{tag}@acme-aero.com", "trial"),
                                   ("personal", f"cat-{tag}@gmail.com", "trial"),
                                   ("pilot", f"pilot-{tag}@acme-aero.com", "pilot")):
            uid = (await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider, plan, phone_verified_at, current_org_id) "
                "VALUES (:e, :e, 'analyst', 'password', :p, now(), :o) RETURNING id"
            ), {"e": email, "p": plan, "o": org})).scalar_one()
            await s.execute(text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:id, :o, :u, 'admin', now())"
            ), {"id": str(ULID()), "o": org, "u": uid})
            users[label] = uid
        await machines.create_machine(s, org, dict(HAAS), created_by=users["work"])
        await machines.create_machine(s, org, dict(BAMBU), created_by=users["work"])

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(batch_router)
    try:
        yield {"app": app, "org": org, "users": users, "pool": pool}
    finally:
        async with eng.get_session_factory()() as s, s.begin():
            ids = list(users.values())
            await s.execute(text("DELETE FROM catalog_parts WHERE user_id = ANY(:u)"), {"u": ids})
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": ids})
        # The engine's pool belongs to this test's event loop.
        await eng.dispose_engine()


def _as(app, uid: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=uid, api_key_id=0, key_prefix="session", role="analyst"
    )


async def _post(app, files: dict[str, bytes], *, parts_list: str | None = None, **form):
    from httpx import ASGITransport, AsyncClient

    upload = {"file": ("catalog.zip", _zip(files), "application/zip")}
    if parts_list is not None:
        upload["manifest"] = ("parts.csv", parts_list.encode(), "text/csv")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post("/api/v1/catalog-runs", files=upload, data={k: str(v) for k, v in form.items()})


async def _get(app, path: str):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.get(path)


async def _run_all(batch_id: str) -> None:
    """Run every item through the real worker task, as the coordinator would."""
    from sqlalchemy import text

    import src.db.engine as eng
    from src.jobs.batch_tasks import run_batch_item

    async with eng.get_session_factory()() as s, s.begin():
        rows = (await s.execute(text(
            "UPDATE batch_items SET status = 'queued' FROM batches b "
            "WHERE batch_items.batch_id = b.id AND b.ulid = :b AND batch_items.status = 'pending' "
            "RETURNING batch_items.ulid"
        ), {"b": batch_id})).scalars().all()
        await s.execute(text("UPDATE batches SET status = 'processing' WHERE ulid = :b"), {"b": batch_id})
    for ulid in rows:
        await run_batch_item({"job_try": 1}, ulid)
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("UPDATE batches SET status = 'completed', completed_at = now() WHERE ulid = :b"), {"b": batch_id})


async def _usage(uid: int) -> dict:
    from src.auth.catalog_allowance import catalog_usage

    return await catalog_usage(uid)


@pytest.mark.asyncio
async def test_catalog_run_sorts_parts_on_the_orgs_machines(world):
    app, uid = world["app"], world["users"]["work"]
    _as(app, uid)
    files = {
        "parts/bracket-pla.stl": _stl((40, 30, 20)),
        "parts/block-al.stl": _stl((60, 40, 30), seed=1),
        "parts/block-ss.stl": _stl((50, 40, 30), seed=2),
        "broken.stl": b"solid nothing\nthis is not an STL\n",
        "notes.txt": b"ignored",
    }
    parts_list = (
        "Part Number,File,Qty,Material\n"
        "BRK-100,bracket-pla.stl,25,PLA\n"
        "BLK-200,block-al,40,6061-T6\n"
        "BLK-304,block-ss.stl,4,304 SS\n"
        "MISSING-1,not-in-the-zip.step,10,304 SS\n"
    )
    r = await _post(app, files, parts_list=parts_list, quantity=10)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["job_type"] == "catalog" and body["parts"] == 4
    assert body["catalog"] == {"free": True, "new": 4, "reruns": 0, "cap": 50, "remaining": 46}
    assert world["pool"].jobs[-1][0] == "run_batch_coordinator"
    usage = await _usage(uid)
    assert (usage["used"], usage["reserved"]) == (0, 4)

    await _run_all(body["batch_id"])
    r = await _get(app, f"/api/v1/batch/{body['batch_id']}/catalog")
    assert r.status_code == 200, r.text
    board = r.json()
    rows = {row["filename"]: row for row in board["rows"]}
    assert board["parts_list"] == {"name": "parts.csv", "rows": 4, "matched": 3, "unmatched": 1}
    assert [u["part_number"] for u in board["unmatched"]] == ["MISSING-1"]

    pla = rows["bracket-pla.stl"]
    assert pla["bucket"] == "in_house", pla
    assert pla["route"] == {"process": "fdm", "machine": "Bambu Lab X1C", "owned": True}
    assert pla["reason"].startswith("On your Bambu Lab X1C")
    assert (pla["part_number"], pla["quantity"], pla["quantity_source"]) == ("BRK-100", 25, "list")
    assert pla["hours_each"] > 0 and pla["hours_total"] == pytest.approx(pla["hours_each"] * 25, rel=1e-3)
    assert pla["material"]["name"] and pla["material"]["mass_kg_each"] > 0
    # The material the engine charges for (filament printed, with infill) next to the part's own mass.
    assert pla["material"]["used_kg_each"] > 0 and pla["used_kg_total"] == pytest.approx(pla["material"]["used_kg_each"] * 25, rel=1e-3)
    assert pla["marginal"] is True and pla["unit_cost_usd"] > 0
    assert pla["part_key"] and pla["analysis_id"] and pla["cost_decision_id"]

    al = rows["block-al.stl"]
    assert al["bucket"] == "in_house", al
    assert al["route"]["machine"] == "Haas VF-2"
    assert "Aluminum" in (al["material"]["name"] or "")

    ss = rows["block-ss.stl"]
    assert ss["bucket"] == "new_machine", ss
    assert ss["capability"]["process"] == "cnc_3axis" and ss["capability"]["gate"] == "material"
    assert ss["reason"].startswith("Haas VF-2: not qualified for")
    assert ss["material"]["declared"] == "304 SS" and ss["material"]["class"] == "stainless"

    broken = rows["broken.stl"]
    assert broken["bucket"] == "not_checked" and broken["status"] == "failed"

    totals = board["totals"]
    assert totals["in_house"]["parts"] == 2 and totals["new_machine"]["parts"] == 1
    assert totals["in_house"]["hours"] == pytest.approx(pla["hours_total"] + al["hours_total"], rel=1e-3)
    # broken.stl isn't on the parts list: kept apart from the list's totals (oo-10).
    assert totals["not_checked"]["parts"] == 0 and board["has_list"] is True
    assert board["unlisted"]["parts"] == 1 and board["unlisted"]["totals"]["not_checked"]["parts"] == 1
    assert broken["listed"] is False and pla["listed"] is True
    # Per bucket, hours by machine and material by grade (resources first).
    by_machine = {m["machine"]: m for m in board["breakdown"]["in_house"]["machines"]}
    assert set(by_machine) == {"Bambu Lab X1C", "Haas VF-2"}
    assert by_machine["Bambu Lab X1C"]["hours"] == pytest.approx(pla["hours_total"], rel=1e-6)
    assert {g["material"] for g in board["breakdown"]["in_house"]["materials"]} == {pla["material"]["name"], al["material"]["name"]}
    assert board["breakdown"]["new_machine"]["missing"][0]["gate"] == "material"

    # The broken file gave its slot back; the three checked parts keep theirs.
    usage = await _usage(uid)
    assert (usage["used"], usage["reserved"], usage["remaining"]) == (3, 0, 47)

    # The same numbers as the part's own record (no second engine path).
    from sqlalchemy import text

    import src.db.engine as eng
    async with eng.get_session_factory()() as s:
        result = (await s.execute(text("SELECT result_json FROM cost_decisions WHERE ulid = :u"),
                                  {"u": pla["cost_decision_id"]})).scalar_one()
    est = next(e for e in result["estimates"] if e["process"] == "fdm" and e["quantity"] == 25)
    assert pla["unit_cost_usd"] == est["unit_cost_usd"]
    assert result["verification"]["best_machine"] == "Bambu Lab X1C"
    assert 25 in result["quantities"]

    # The board reads a slice of each decision in SQL; every row reads exactly as
    # it does from the whole record, and the slice is a small part of it.
    from src.services import catalog_run_service as crs

    async with eng.get_session_factory()() as s:
        full = (await s.execute(text(
            "SELECT bi.ulid, bi.filename, bi.status, bi.error_message, bi.duration_ms, a.ulid, a.mesh_hash, "
            "cost_decisions.ulid, cost_decisions.mesh_hash, cost_decisions.result_json, "
            "length(cost_decisions.result_json::text), "
            f"length(({crs._BOARD_DECISION_SQL})::text) "
            "FROM batch_items bi JOIN batches b ON b.id = bi.batch_id "
            "LEFT JOIN analyses a ON a.id = bi.analysis_id "
            "LEFT JOIN cost_decisions ON cost_decisions.id = bi.cost_decision_id "
            "WHERE b.ulid = :b ORDER BY bi.id"), {"b": body["batch_id"]})).all()
        manifest = (await s.execute(text("SELECT manifest_json FROM batches WHERE ulid = :b"),
                                    {"b": body["batch_id"]})).scalar_one()
    from types import SimpleNamespace

    meta = crs.run_meta(SimpleNamespace(manifest_json=manifest))
    from_full = [crs.derive_part_row(
        item={"ulid": r[0], "filename": r[1], "status": r[2], "error_message": r[3], "duration_ms": r[4]},
        analysis={"ulid": r[5], "mesh_hash": r[6]} if r[5] else None,
        decision={"ulid": r[7], "mesh_hash": r[8], "result_json": r[9] or {}} if r[7] else None,
        meta=(meta.get("items") or {}).get(r[1]), machines=board["machines"],
        default_quantity=int(meta.get("quantity") or crs.DEFAULT_RUN_QUANTITY),
    ) for r in full]
    assert from_full == board["rows"]
    sized = [(r[10], r[11]) for r in full if r[10]]
    assert sized and all(slim < whole / 5 for whole, slim in sized), sized

    csv = await _get(app, f"/api/v1/batch/{body['batch_id']}/catalog.csv")
    assert csv.status_code == 200
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith("file,part_number,bucket,reason")
    assert any(line.startswith("bracket-pla.stl,BRK-100,Make in-house,") for line in lines)
    assert len(lines) == 1 + 4

    # A re-run of the same files is free; a new file takes one slot.
    again = dict(files)
    again["parts/another.stl"] = _stl((20, 20, 20), seed=9)
    r = await _post(app, again, parts_list=parts_list)
    assert r.status_code == 202, r.text
    # broken.stl gave its slot back, so it is new again (and so is another.stl).
    assert r.json()["catalog"]["new"] == 2 and r.json()["catalog"]["reruns"] == 3


@pytest.mark.asyncio
async def test_the_51st_part_is_refused_before_anything_runs(world, monkeypatch):
    app, uid = world["app"], world["users"]["work"]
    _as(app, uid)
    monkeypatch.setenv("FREE_CATALOG_PARTS", "3")
    r = await _post(app, {f"p{n}.stl": _stl((10, 10, 10), seed=n) for n in range(4)})
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "catalog_allowance_exceeded"
    assert (detail["needed"], detail["remaining"], detail["cap"]) == (4, 3, 3)
    assert world["pool"].jobs == []
    assert (await _usage(uid))["remaining"] == 3
    from sqlalchemy import text

    import src.db.engine as eng
    async with eng.get_session_factory()() as s:
        n = (await s.execute(text("SELECT count(*) FROM batches WHERE user_id = :u"), {"u": uid})).scalar_one()
    assert n == 0  # the refused run left no batch behind


@pytest.mark.asyncio
async def test_personal_email_is_refused_and_pilot_runs_unlimited(world, monkeypatch):
    app = world["app"]
    _as(app, world["users"]["personal"])
    r = await _post(app, {"a.stl": _stl((10, 10, 10))})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "catalog_run_work_email"

    monkeypatch.setenv("FREE_CATALOG_PARTS", "1")
    _as(app, world["users"]["pilot"])
    r = await _post(app, {f"p{n}.stl": _stl((10, 10, 10), seed=n) for n in range(3)}, concurrency_limit=12)
    assert r.status_code == 202, r.text
    assert r.json()["catalog"] == {"free": False}
    progress = await _get(app, f"/api/v1/batch/{r.json()['batch_id']}")
    assert progress.json()["job_type"] == "catalog"
    assert progress.json()["concurrency_limit"] == 12


@pytest.mark.asyncio
async def test_a_free_run_is_one_at_a_time_and_limited_in_size(world, monkeypatch):
    app, uid = world["app"], world["users"]["work"]
    _as(app, uid)
    r = await _post(app, {"a.stl": _stl((10, 10, 10))}, concurrency_limit=12)
    assert r.status_code == 202
    progress = await _get(app, f"/api/v1/batch/{r.json()['batch_id']}")
    assert progress.json()["concurrency_limit"] == 4  # free runs check at most 4 at a time
    busy = await _post(app, {"b.stl": _stl((10, 10, 10), seed=1)})
    assert busy.status_code == 409
    assert busy.json()["detail"] == {
        "code": "catalog_run_active",
        "message": "Your free catalog run is still going. Open it to follow it; start the next one when it finishes.",
        "batch_id": r.json()["batch_id"],
    }
    monkeypatch.setenv("FREE_CATALOG_MAX_ZIP_BYTES", str(1024 * 1024))
    big = await _post(app, {"big.stl": os.urandom(2 * 1024 * 1024)})
    assert big.status_code == 413


@pytest.mark.asyncio
async def test_bad_inputs_are_clean_errors(world):
    app = world["app"]
    _as(app, world["users"]["work"])
    r = await _post(app, {"a.stl": _stl((10, 10, 10))}, parts_list="Qty,Material\n1,PLA\n")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_PARTS_LIST"
    r = await _post(app, {"a.stl": _stl((10, 10, 10))}, parts_list="file,qty\na.stl,1.5\n")
    assert r.status_code == 400 and "Row 2" in r.json()["detail"]["message"]
    r = await _post(app, {"a.stl": _stl((10, 10, 10))}, material_class="unobtainium")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_MATERIAL_CLASS"
    # POST /batch never takes a catalog run.
    from httpx import ASGITransport, AsyncClient

    from src.auth.validation_caps import require_paid_access

    app.dependency_overrides[require_paid_access] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/batch", data={"job_type": "catalog"})
    assert r.status_code == 422 and "catalog-runs" in r.json()["detail"]["message"]
    # Another org's run (or no run) is a 404 on the board.
    r = await _get(app, "/api/v1/batch/does-not-exist/catalog")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_a_large_zip_comes_from_a_direct_upload(world, monkeypatch, tmp_path):
    """The ZIP uploaded to storage in parts (resumable) is unpacked on the worker, not in the request.

    The request checks the upload and attaches it to a run that is "preparing";
    the worker's preparation (the real task) downloads it verified, unpacks it
    with the batch extraction limits, gives the parts their quantities and
    reserves the free allowance with the items, or ends the run with the
    refusal kept on it.
    """
    import hashlib
    import io as _io

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng
    from src.jobs.batch_tasks import prepare_direct_upload_batch
    from src.services import direct_upload_service as uploads

    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("DIRECT_UPLOAD_LOCAL_ROOT", str(tmp_path / "incoming"))
    monkeypatch.delenv("RELEASE", raising=False)
    app, uid, pool = world["app"], world["users"]["work"], world["pool"]
    _as(app, uid)
    data = _zip({"a.stl": _stl((20, 20, 20), seed=21), "b.stl": _stl((30, 20, 10), seed=22)})
    reads = {"n": 0}
    real_download = uploads.download_to_bounded_tempfile

    def counted(*args, **kwargs):
        reads["n"] += 1
        return real_download(*args, **kwargs)

    monkeypatch.setattr(uploads, "download_to_bounded_tempfile", counted)

    async def _upload(checksum: str, body: bytes = data) -> str:
        async with eng.get_session_factory()() as s:
            up, parts, _, _ = await uploads.initiate(
                s, user_id=uid, purpose="batch_zip", filename="catalog.zip", content_type="application/zip",
                size_bytes=len(body), checksum_sha256=checksum, idempotency_key=f"cat-{uuid.uuid4().hex}", plan="trial",
            )
            store = uploads._require_s3_store()
            etag, _ = store.put_part(up.object_key, up.multipart_upload_id, 1, _io.BytesIO(body), max_bytes=len(body))
            await uploads.complete(s, user_id=uid, upload_ulid=up.ulid, parts=[{"part_number": 1, "etag": etag}])
            return up.ulid

    async def _post_upload(upload_id: str):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            return await ac.post("/api/v1/catalog-runs", data={"direct_upload_id": upload_id, "quantity": "10"})

    async def _prepare(upload_id: str) -> None:
        await prepare_direct_upload_batch({"job_try": 1, "redis": pool}, upload_id)

    try:
        # A damaged upload is refused on the worker, with its reason on the run; nothing is reserved.
        bad_id = await _upload("0" * 64)
        bad = await _post_upload(bad_id)
        assert bad.status_code == 202, bad.text
        assert bad.json()["preparing"] is True and bad.json()["parts"] is None
        assert reads["n"] == 0, "the request never reads the ZIP"
        await _prepare(bad_id)
        board = (await _get(app, f"/api/v1/batch/{bad.json()['batch_id']}/catalog")).json()
        assert board["status"] == "failed" and board["preparing"] is False
        assert board["failure"]["code"] == "DIRECT_UPLOAD_CHECKSUM_MISMATCH"
        assert (await _usage(uid))["reserved"] == 0

        upload_id = await _upload(hashlib.sha256(data).hexdigest())
        r = await _post_upload(upload_id)
        assert r.status_code == 202, r.text
        run = r.json()
        assert run["preparing"] is True and run["parts"] is None and run["catalog"] == {"free": True, "pending": True}
        assert ("prepare_direct_upload_batch", (upload_id,)) in pool.jobs
        board = (await _get(app, f"/api/v1/batch/{run['batch_id']}/catalog")).json()
        assert board["preparing"] is True and board["rows"] == []
        # A second free run while this one prepares is refused in the request.
        other = await _post_upload(await _upload(hashlib.sha256(data).hexdigest()))
        assert other.status_code == 409 and other.json()["detail"]["code"] == "catalog_run_active"
        # Posting the same upload again is the same run.
        again = await _post_upload(upload_id)
        assert again.status_code == 202 and again.json()["batch_id"] == run["batch_id"]

        await _prepare(upload_id)
        board = (await _get(app, f"/api/v1/batch/{run['batch_id']}/catalog")).json()
        assert board["preparing"] is False and board["status"] == "pending" and board["failure"] is None
        assert board["parts"] == 2 and board["quantity"] == 10
        assert board["reservation"]["new"] == 2 and board["reservation"]["remaining"] == board["reservation"]["cap"] - 2
        assert ("run_batch_coordinator", (run["batch_id"],)) in pool.jobs
        assert (await _usage(uid))["reserved"] == 2
        async with eng.get_session_factory()() as s:
            quantities = (await s.execute(text(
                "SELECT DISTINCT bi.quantities FROM batch_items bi JOIN batches b ON b.id = bi.batch_id "
                "WHERE b.ulid = :b"), {"b": run["batch_id"]})).scalars().all()
            status, cleaned = (await s.execute(text(
                "SELECT status, storage_cleaned_at IS NOT NULL FROM direct_uploads WHERE ulid = :u"), {"u": upload_id})).one()
        assert quantities and all(q and q.split(";")[0] == "1" for q in quantities)
        assert (status, cleaned) == ("consumed", True)
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM direct_uploads WHERE user_id = :u"), {"u": uid})
            await s.commit()


@pytest.mark.asyncio
async def test_a_stored_zip_over_the_free_allowance_is_refused_on_the_worker(world, monkeypatch, tmp_path):
    """The allowance is counted on the worker once the ZIP is unpacked; a refusal ends the run, says why
    in the allowance's own words, reserves nothing and leaves nothing behind."""
    import hashlib
    import io as _io

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng
    from src.jobs.batch_tasks import prepare_direct_upload_batch
    from src.services import direct_upload_service as uploads

    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("DIRECT_UPLOAD_LOCAL_ROOT", str(tmp_path / "incoming"))
    monkeypatch.setenv("FREE_CATALOG_PARTS", "1")
    monkeypatch.delenv("RELEASE", raising=False)
    app, uid, pool = world["app"], world["users"]["work"], world["pool"]
    _as(app, uid)
    data = _zip({"c.stl": _stl((20, 20, 20), seed=31), "d.stl": _stl((30, 20, 10), seed=32)})
    async with eng.get_session_factory()() as s:
        up, _parts, _, _ = await uploads.initiate(
            s, user_id=uid, purpose="batch_zip", filename="catalog.zip", content_type="application/zip",
            size_bytes=len(data), checksum_sha256=hashlib.sha256(data).hexdigest(),
            idempotency_key=f"cat-{uuid.uuid4().hex}", plan="trial",
        )
        store = uploads._require_s3_store()
        etag, _ = store.put_part(up.object_key, up.multipart_upload_id, 1, _io.BytesIO(data), max_bytes=len(data))
        await uploads.complete(s, user_id=uid, upload_ulid=up.ulid, parts=[{"part_number": 1, "etag": etag}])
        upload_id = up.ulid
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/catalog-runs", data={"direct_upload_id": upload_id})
        assert r.status_code == 202, r.text
        await prepare_direct_upload_batch({"job_try": 1, "redis": pool}, upload_id)
        board = (await _get(app, f"/api/v1/batch/{r.json()['batch_id']}/catalog")).json()
        assert board["status"] == "failed" and board["preparing"] is False
        failure = board["failure"]
        assert failure["code"] == "catalog_allowance_exceeded"
        assert "has 2 parts not run before" in failure["message"] and failure["remaining"] == 1 and failure["needed"] == 2
        assert (await _usage(uid))["reserved"] == 0
        async with eng.get_session_factory()() as s:
            items = (await s.execute(text(
                "SELECT count(*) FROM batch_items bi JOIN batches b ON b.id = bi.batch_id WHERE b.ulid = :b"),
                {"b": r.json()["batch_id"]})).scalar_one()
            status = (await s.execute(text("SELECT status FROM direct_uploads WHERE ulid = :u"), {"u": upload_id})).scalar_one()
        assert items == 0 and status == "failed"
        assert not any(name == "run_batch_coordinator" and args == (r.json()["batch_id"],) for name, args in pool.jobs)
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM direct_uploads WHERE user_id = :u"), {"u": uid})
            await s.commit()
