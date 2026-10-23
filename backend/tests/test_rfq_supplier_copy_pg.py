"""RFQ packages against real Postgres and the kept-file store (buyer-09, buyer-18, buyer-08).

Two parts in one organization, each with the source file ScaleCAD kept:

* a single-part check (no batch), with a declared yearly volume and specs;
* a part from a catalog run of 250, re-checked afterwards with specs, so the
  record the buyer packages (the newest) is not the one the run's ZIP holds.

A package of both, built and downloaded through the API, carries both CAD files
byte for byte, asks for 1,200 and 250, names who asks, and holds none of our
cost or review state. Skipped unless DATABASE_URL is PostgreSQL at schema head.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import pytest


def shows(word: bytes, body: bytes) -> bool:
    """Whether ``body`` carries ``word``. A number counts only as a value of its
    own: our 241 (the crossover quantity) is caught as ``:241,``, but the same
    digits inside a ULID or a timestamp's microseconds are not a leak."""
    if word.replace(b".", b"").isdigit():
        return re.search(rb"(?<![0-9A-Za-z.])" + re.escape(word) + rb"(?![0-9A-Za-z])", body) is not None
    return word in body


_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires live Postgres")]

SINGLE = b"solid single\n  facet normal 0 0 1\nendsolid single\n"
PLATE = b"ISO-10303-21;\nHEADER;\nFILE_NAME('plate-with-boss.step');\nENDSEC;\nEND-ISO-10303-21;\n"
RESULT = {
    "material_class": "aluminum", "quantities": [1, 250, 1000],
    "geometry": {"bbox_mm": [300, 200, 10.8]},
    "estimates": [{"process": "cnc_3axis", "material": "6061-T6 Aluminum", "quantity": 250,
                   "unit_cost_usd": 193.18, "dfm_ready": True,
                   "confidence": {"validated": False, "method": "assumption-band"}}],
    "decision": {"make_now_process": "cnc_3axis", "crossover_qty": 241,
                 "recommendation": {"250": {"process": "cnc_3axis", "unit_cost_usd": 193.18}}},
}


def _app():
    from fastapi import FastAPI

    from src.api.rfq_packages import router as rfq_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(rfq_router, prefix="/api/v1/rfq-packages")
    return app


async def _seed():
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.db.models import Batch, BatchItem, CostDecision, PartContext
    from src.services.source_artifact_service import save_source_artifact

    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    h_single, h_plate = hashlib.sha256(SINGLE).hexdigest(), hashlib.sha256(PLATE).hexdigest()
    await save_source_artifact(org, h_single, "single.stl", SINGLE)
    await save_source_artifact(org, h_plate, "plate-with-boss.step", PLATE)
    async with eng.get_session_factory()() as s:
        await s.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :s)"),
                        {"id": org, "n": "Kestrel Contract Manufacturing", "s": f"kcm-{tag}"})
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider, current_org_id, plan, full_name) "
            "VALUES (:e, :e, 'analyst', 'password', :o, 'pilot', 'Marcus Bell') RETURNING id"),
            {"e": f"buyer-{tag}@example.com", "o": org})).scalar_one())
        await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role) VALUES (:id, :o, :u, 'admin')"),
                        {"id": str(ULID()), "o": org, "u": uid})

        def record(h, name, ftype, when):
            return CostDecision(user_id=uid, org_id=org, mesh_hash=h, params_hash=f"p-{uuid.uuid4().hex}",
                                engine_version="t", filename=name, file_type=ftype, result_json=RESULT,
                                make_now_process="cnc_3axis", crossover_qty=241, quantities=[1, 100, 1000],
                                approval_status="unreviewed", created_at=when)

        now = datetime.now(timezone.utc)
        single = record(h_single, "single.stl", "stl", now)
        in_run = record(h_plate, "plate-with-boss.step", "step", now - timedelta(minutes=10))
        rechecked = record(h_plate, "plate-with-boss.step", "step", now)
        s.add_all([single, in_run, rechecked,
                   PartContext(org_id=org, mesh_hash=h_single, annual_volume=1200,
                               part_specs={"inspection": ["fai_as9102"], "certifications": ["as9100"]})])
        await s.flush()
        batch = Batch(user_id=uid, org_id=org, status="completed", job_type="catalog", input_mode="zip",
                      manifest_json={"catalog": {"quantity": 250, "items": {}}})
        s.add(batch)
        await s.flush()
        s.add(BatchItem(batch_id=batch.id, org_id=org, filename="plate-with-boss.step", status="completed",
                        cost_decision_id=in_run.id))
        await s.commit()
        return {"org": org, "user": uid, "single": single.ulid, "rechecked": rechecked.ulid, "tag": tag}


async def _cleanup(w):
    from sqlalchemy import text

    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(text("DELETE FROM audit_log WHERE user_id = :u OR org_id = :o"), {"u": w["user"], "o": w["org"]})
        await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": w["org"]})
        await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": w["user"]})
        await s.commit()
    await eng.dispose_engine()


async def test_a_package_carries_the_kept_cad_of_a_single_check_and_of_a_rechecked_catalog_part(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from src.auth.require_api_key import AuthedUser, require_api_key

    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("SOURCE_ARTIFACT_BLOB_DIR", str(tmp_path / "kept"))
    monkeypatch.delenv("OBJECT_STORE_LOCAL_ROOT", raising=False)
    monkeypatch.delenv("OBJECT_STORE_BACKEND", raising=False)
    w = await _seed()
    app = _app()
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=w["user"], api_key_id=0, key_prefix="session", role="analyst")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            ids = [w["single"], w["rechecked"]]
            made = await client.post("/api/v1/rfq-packages", json={
                "decision_ids": ids, "title": "RFQ-1022", "supplier_name": "Midway Machining",
                "include_raw_cad": True, "reply_by": (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()})
            assert made.status_code == 201, made.text
            pkg = made.json()["package"]
            assert not [x for x in pkg["warnings"] if x["code"] == "raw_cad_unavailable"], pkg["warnings"]
            assert pkg["raw_cad_included"] is True
            assert pkg["metadata"]["requested_by"]["company"] == "Kestrel Contract Manufacturing"
            zipped = await client.get(f"/api/v1/rfq-packages/{pkg['id']}/download.zip")
            assert zipped.status_code == 200
        with zipfile.ZipFile(io.BytesIO(zipped.content)) as zf:
            files = {n: zf.read(n) for n in zf.namelist()}
        assert files.get("parts/01-single/single.stl") == SINGLE, sorted(files)
        assert files.get("parts/02-plate-with-boss/plate-with-boss.step") == PLATE, sorted(files)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            # The builder shows each part's quantity before the package is built.
            preview = await client.post("/api/v1/rfq-packages/preview", json={"decision_ids": ids})
            assert preview.status_code == 200, preview.text
            rows = {r["id"]: r for r in preview.json()["items"]}
            assert (rows[w["single"]]["quantity"], rows[w["single"]]["quantity_source"]) == (1200, "yearly_volume")
            assert (rows[w["rechecked"]]["quantity"], rows[w["rechecked"]]["quantity_source"]) == (250, "run")
            assert rows[w["single"]]["cad_kept"] is True and rows[w["rechecked"]]["cad_kept"] is True
            assert "Inspection: First article inspection, AS9102" in rows[w["single"]]["specs"]
            # buyer-11: the picker's price is at that quantity, with the engine's pick there.
            assert rows[w["rechecked"]]["price"] == {"quantity": 250, "unit_cost_usd": 193.18,
                                                     "process": "cnc_3axis", "dfm_ready": None, "basis": "asked"}
            assert rows[w["single"]]["price"] is None  # 1,200 wasn't priced: no price, never another quantity's
            assert preview.json()["requested_by"] == {"name": "Marcus Bell", "company": "Kestrel Contract Manufacturing",
                                                      "email": f"buyer-{w['tag']}@example.com"}
            light = await client.post("/api/v1/rfq-packages/preview", json={"decision_ids": ids, "cad": False})
            assert [r["cad_kept"] for r in light.json()["items"]] == [None, None]

        lines = list(csv.DictReader(io.StringIO(files["line-items.csv"].decode())))
        assert [(r["part"], r["quantity"], r["yearly_volume"]) for r in lines] == [
            ("single.stl", "1200", "1200"), ("plate-with-boss.step", "250", "")]
        brief = files["supplier-brief.md"].decode()
        assert "- Requested by: Marcus Bell, Kestrel Contract Manufacturing, buyer-" in brief
        for name, body in files.items():
            for word in (b"193.18", b"241", b"approval", b"unreviewed", b"Unvalidated", b"should-cost"):
                assert not shows(word, body), (name, word)
    finally:
        await _cleanup(w)
