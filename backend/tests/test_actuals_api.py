"""Your actuals end to end on Postgres: import, accuracy, org scoping, calibration
apply / undo with audit, the overlay on a real estimate, and the pilot report.

Skipped unless DATABASE_URL is Postgres at schema head (>= migration 0054).
"""
from __future__ import annotations

import json
import os

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)")

N_PARTS = 9          # one more than the 8-part floor
ENGINE_HOURS = 4.0   # ScaleCAD's machine hours per part on every seeded record
TRUE_RATIO = 0.88    # the shop really runs 12% faster


def _build_app():
    from fastapi import FastAPI

    from src.api.actuals import router as actuals_router
    from src.api.routes import router as core_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(core_router, prefix="/api/v1")
    app.include_router(actuals_router, prefix="/api/v1/actuals")
    return app


def _act_as(app, user_id: int, role: str = "analyst") -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role=role
    )


def _result(hours: float, unit: float) -> dict:
    est = lambda q, u: {  # noqa: E731
        "process": "cnc_3axis", "material": "Aluminum 6061", "quantity": q, "unit_cost_usd": u,
        "est_error_band_pct": 50.0,
        "drivers": [
            {"name": "cycle_time", "value": hours, "unit": "hr", "provenance": "DEFAULT", "source": "s", "error_band_pct": 50.0},
            {"name": "machine_cost", "value": hours * 75, "unit": "$", "provenance": "DEFAULT", "source": "s"},
        ],
        "confidence": {"low_usd": u * 0.5, "high_usd": u * 1.5, "point_usd": u, "validated": False},
        "line_items": {"machine": hours * 75},
    }
    return {"status": "OK", "material_class": "aluminum", "estimates": [est(1, unit * 3), est(100, unit)],
            "verification": {"verdict": "makeable_in_house", "inventory_declared": True,
                             "resource": {"process": "cnc_3axis", "machine": "Haas VF-2"}},
            "decision": {"make_now_process": "cnc_3axis", "recommendation": {"100": {"process": "cnc_3axis", "unit_cost_usd": unit}},
                         "options": {"100": {"in_house": {"process": "cnc_3axis", "unit_cost_usd": unit},
                                             "outside": {"process": "fdm", "unit_cost_usd": unit * 1.4}}}},
            "geometry": {"volume_cm3": 20.0}}


def _cube_bytes(i: int) -> bytes:
    import trimesh

    return trimesh.creation.box(extents=(30 + 2 * i, 20 + i, 10 + i)).export(file_type="stl")


@_requires_pg
@pytest.mark.asyncio
async def test_import_compare_calibrate_undo_report_and_org_scoping(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select, text
    from ulid import ULID

    import src.db.engine as eng
    from src.db.models import AuditLog, Batch, BatchItem, CostDecision, GroundTruthRecordRow, OrgCalibration, PartSignature

    monkeypatch.setenv("CADVERIFY_CALIBRATION_DIR", str(tmp_path / "cal"))
    monkeypatch.setenv("PDF_CACHE_DIR", str(tmp_path / "pdf"))
    org_a, org_b = str(ULID()), str(ULID())
    users: list[int] = []

    async def mk_user(s, label, plan):
        email = f"act-{org_a[:6]}-{label}@example.com"
        uid = (await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider, plan) "
            "VALUES (:e, :el, 'analyst', 'password', :p) RETURNING id"), {"e": email, "el": email, "p": plan})).first()[0]
        users.append(int(uid))
        return int(uid)

    hashes = [f"{i:02d}" + "a" * 62 for i in range(N_PARTS)]
    async with eng.get_session_factory()() as s:
        for oid, name in ((org_a, "Acme"), (org_b, "Other")):
            await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:i, :n, :s, now())"),
                            {"i": oid, "n": f"{name} {oid[:6]}", "s": f"{name.lower()}-{oid[:8].lower()}"})
        a1 = await mk_user(s, "a1", "pilot")
        a2 = await mk_user(s, "a2", "free")
        b1 = await mk_user(s, "b1", "pilot")
        for oid, uid in ((org_a, a1), (org_a, a2), (org_b, b1)):
            await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:i, :o, :u, 'admin', now())"),
                            {"i": str(ULID()), "o": oid, "u": uid})
        decisions = []
        for i, h in enumerate(hashes):
            d = CostDecision(user_id=a1, org_id=org_a, mesh_hash=h, params_hash="p", engine_version="t",
                             filename=f"part-{i:02d}.step", file_type="step", result_json=_result(ENGINE_HOURS, 40.0))
            s.add(d)
            decisions.append(d)
        await s.flush()
        # A catalog run of three of the parts; its parts list names part-02 "PN-RUN-2".
        run = Batch(user_id=a1, org_id=org_a, status="completed", job_type="catalog", input_mode="zip", total_items=3,
                    manifest_json={"catalog": {"quantity": 100, "items": {"part-02.step": {"part_number": "PN-RUN-2", "quantity": 100}}}})
        s.add(run)
        await s.flush()
        for d in decisions[2:5]:
            s.add(BatchItem(batch_id=run.id, org_id=org_a, filename=d.filename, status="completed", cost_decision_id=d.id))
        run_id = run.ulid
        # Two revisions with the same file name: a row naming it is asked about.
        s.add(CostDecision(user_id=a1, org_id=org_a, mesh_hash="ff" + "b" * 62, params_hash="p", engine_version="t",
                           filename="part-00.step", file_type="step", result_json=_result(ENGINE_HOURS, 40.0)))
        s.add(PartSignature(org_id=org_a, mesh_hash=hashes[1], signature=[0.0] * 18, declared_part_id="PN-0001"))
        # Org B has a part with the same file name: it must never match A's rows, nor see them.
        s.add(CostDecision(user_id=b1, org_id=org_b, mesh_hash="ee" + "c" * 62, params_hash="p", engine_version="t",
                           filename="part-03.step", file_type="step", result_json=_result(ENGINE_HOURS, 40.0)))
        await s.commit()

    lines = ["Part No,File,Qty,Machine hrs each,Cost each,Process,Date"]
    lines.append(f"PN-0001,,100,{ENGINE_HOURS * TRUE_RATIO:.4f},36.00,3-axis mill,2026-09-01")     # by declared part number
    lines.append(f"PN-RUN-2,,100,{ENGINE_HOURS * TRUE_RATIO:.4f},36.00,3-axis mill,2026-09-02")         # by a run's parts list
    for i in range(3, N_PARTS):
        lines.append(f",part-{i:02d}.step,100,{ENGINE_HOURS * TRUE_RATIO:.4f},36.00,3-axis mill,2026-09-0{(i % 9) + 1}")
    lines.append(",part-00.step,100,3.5,36,3-axis mill,")                                          # ambiguous
    lines.append(",nope.step,100,3.5,36,3-axis mill,")                                              # unmatched
    lines.append(",,100,3.5,36,3-axis mill,")                                                       # no identity
    csv_bytes = ("\n".join(lines) + "\n").encode()

    app = _build_app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            _act_as(app, a1)
            files = {"file": ("jobs.csv", csv_bytes, "text/csv")}
            r = await ac.post("/api/v1/actuals/preview", files=files)
            assert r.status_code == 200, r.text
            p = r.json()
            assert p["summary"]["matched"] == N_PARTS - 1
            assert p["summary"]["ambiguous"] == 1 and p["summary"]["unmatched"] == 2
            amb = next(x for x in p["rows"] if x["status"] == "ambiguous")
            assert {c["key"] for c in amb["candidates"]} == {hashes[0], "ff" + "b" * 62}
            assert all(c["key"] != "ee" + "c" * 62 for x in p["rows"] for c in x["candidates"])
            assert len(p["parts"]) == N_PARTS + 1 and all(x["key"] != "ee" + "c" * 62 for x in p["parts"])
            pn_row = next(x for x in p["rows"] if x["values"]["part_number"] == "PN-0001")
            assert pn_row["part"]["key"] == hashes[1] and pn_row["basis"] == "part_number"

            choices = json.dumps({str(amb["line"]): hashes[0]})
            r = await ac.post("/api/v1/actuals/import", files={"file": ("jobs.csv", csv_bytes, "text/csv")},
                              data={"mapping": json.dumps(p["mapping"]), "choices": choices})
            assert r.status_code == 200, r.text
            imp = r.json()
            assert imp["imported"] == N_PARTS and imp["parts"] == N_PARTS
            assert len(imp["not_imported"]) == 2

            r = await ac.get("/api/v1/actuals/accuracy")
            assert r.status_code == 200, r.text
            a = r.json()
            assert a["summary"]["parts"] == N_PARTS and a["summary"]["enough"] is True
            assert a["summary"]["hours"]["median_abs_pct"] == pytest.approx(13.6, abs=0.1)   # 4.0 vs 3.52
            assert a["calibration"] is None

            # One catalog run's parts: too few to say much, and said so.
            r = await ac.get(f"/api/v1/actuals/accuracy?run={run_id}")
            assert r.status_code == 200, r.text
            assert r.json()["summary"]["parts"] == 3 and r.json()["summary"]["enough"] is False

            r = await ac.get(f"/api/v1/actuals/accuracy?part={hashes[1]}")
            one = r.json()["rows"]
            assert len(one) == 1 and one[0]["hours"]["error_pct"] == pytest.approx(13.64, abs=0.01)

            # ---- org B sees none of it, and its part never matched A's rows
            _act_as(app, b1)
            r = await ac.get("/api/v1/actuals/accuracy")
            assert r.json()["summary"]["actuals"] == 0
            assert (await ac.get(f"/api/v1/actuals/accuracy?run={run_id}")).status_code == 404
            assert (await ac.get(f"/api/v1/actuals/report?run={run_id}")).status_code == 404
            assert (await ac.get("/api/v1/actuals/calibration")).json()["history"] == []

            # ---- the proposal is on every plan; applying it is the pilot's
            _act_as(app, a2)
            r = await ac.get("/api/v1/actuals/calibration")
            body = r.json()
            assert body["can_apply"] is False
            h = body["proposal"]["processes"][0]["hours"]
            assert h["offer"] is True and h["factor"] == pytest.approx(TRUE_RATIO, abs=1e-3)
            r = await ac.post("/api/v1/actuals/calibration/apply", json={})
            assert r.status_code == 403

            _act_as(app, a1)
            r = await ac.post("/api/v1/actuals/calibration/apply", json={"processes": ["cnc_3axis"]})
            assert r.status_code == 200, r.text
            applied = r.json()["applied"]
            # The same factors again: nothing new, nothing recorded.
            r2 = await ac.post("/api/v1/actuals/calibration/apply", json={"processes": ["cnc_3axis"]})
            assert r2.status_code == 422 and "Nothing new" in r2.json()["detail"]["message"]
            assert applied["factors"]["cnc_3axis"]["hours"] == pytest.approx(TRUE_RATIO, abs=1e-3)
            assert applied["applied_by"].startswith("act-") and applied["applied_at"]

            # ---- the next estimate for org A carries it; org B's doesn't
            r = await ac.post("/api/v1/validate/cost", data={"qty": "1,100"},
                              files={"file": ("cube.stl", _cube_bytes(1), "application/octet-stream")})
            assert r.status_code == 200, r.text
            est = next(e for e in r.json()["estimates"] if e["process"] == "cnc_3axis")
            cyc = next(d for d in est["drivers"] if d["name"] == "cycle_time")
            assert est["calibration"]["hours_factor"] == pytest.approx(TRUE_RATIO, abs=1e-3)
            assert cyc["value"] == pytest.approx(est["calibration"]["before"]["cycle_time_hr"] * TRUE_RATIO, rel=1e-3)
            _act_as(app, b1)
            r = await ac.post("/api/v1/validate/cost", data={"qty": "1,100"},
                              files={"file": ("cube.stl", _cube_bytes(1), "application/octet-stream")})
            assert all("calibration" not in e for e in r.json()["estimates"])

            # ---- accuracy still compares against the engine's own numbers
            _act_as(app, a1)
            assert (await ac.get("/api/v1/actuals/accuracy")).json()["summary"]["hours"]["median_abs_pct"] == pytest.approx(13.6, abs=0.1)

            # ---- the pilot report
            r = await ac.get("/api/v1/actuals/report")
            assert r.status_code == 200, r.text
            rep = r.json()
            # The seeded parts, the second revision, and the cube just checked (no machines: not sorted).
            assert rep["parts"] == N_PARTS + 2
            assert rep["other"] == {"not_sorted": 1}
            in_house = next(b for b in rep["buckets"] if b["key"] == "in_house")
            assert in_house["parts"] == N_PARTS + 1
            assert rep["in_house"]["hours"] == pytest.approx((N_PARTS + 1) * ENGINE_HOURS * 100, rel=1e-6)
            assert rep["wins"] and rep["wins"][0]["saving_total"] == pytest.approx(16.0 * 100)
            assert rep["accuracy"]["parts"] == N_PARTS
            assert rep["calibration"]["applied_by"].startswith("act-")
            assert any("before any calibration" in c for c in rep["caveats"])
            r = await ac.get("/api/v1/actuals/report.pdf")
            assert r.status_code == 200 and r.content[:4] == b"%PDF"
            # The run's report: its three parts, its own records' prices, its actuals.
            r = await ac.get(f"/api/v1/actuals/report?run={run_id}")
            assert r.status_code == 200, r.text
            rr = r.json()
            assert rr["scope"]["kind"] == "run" and rr["parts"] == 3
            assert rr["accuracy"]["parts"] == 3
            assert any("3 parts with actuals: not enough to say" in c for c in rr["caveats"])
            assert {w["part_number"] for w in rr["wins"]} >= {"PN-RUN-2"}

            # ---- undo: who and when, and the next estimate is the engine's again
            r = await ac.post("/api/v1/actuals/calibration/undo")
            assert r.status_code == 200, r.text
            assert r.json()["in_effect"] is None
            hist = r.json()["history"]
            assert hist[0]["status"] == "undone" and hist[0]["undone_by"].startswith("act-") and hist[0]["undone_at"]
            assert (await ac.post("/api/v1/actuals/calibration/undo")).status_code == 409
            r = await ac.post("/api/v1/validate/cost", data={"qty": "1,100"},
                              files={"file": ("cube.stl", _cube_bytes(2), "application/octet-stream")})
            assert all("calibration" not in e for e in r.json()["estimates"])

        async with eng.get_session_factory()() as s:
            acts = (await s.execute(select(AuditLog.action).where(AuditLog.org_id == org_a))).scalars().all()
            assert {"actuals.imported", "calibration.applied", "calibration.undone"} <= set(acts)
            rows = (await s.execute(select(GroundTruthRecordRow).where(GroundTruthRecordRow.org_id == org_a))).scalars().all()
            assert {r.match_basis for r in rows} == {"part_number", "file_name", "chosen"}
            assert all(r.evidence_sha256 in hashes for r in rows)
            assert (await s.execute(select(OrgCalibration).where(OrgCalibration.org_id == org_b))).first() is None
    finally:
        async with eng.get_session_factory()() as s:
            for t in ("ground_truth_records", "org_calibrations", "part_signatures", "batch_items", "batches", "cost_decisions", "audit_log", "analyses"):
                await s.execute(text(f"DELETE FROM {t} WHERE org_id IN (:a, :b)"), {"a": org_a, "b": org_b})
            if users:
                await s.execute(text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": users})
                await s.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": users})
            await s.execute(text("DELETE FROM organizations WHERE id IN (:a, :b)"), {"a": org_a, "b": org_b})
            await s.commit()
        await eng.dispose_engine()
