"""W5 ground-truth flywheel — end-to-end on live Postgres + the real engine.

Drives the ingest API, the recalibration trigger, and POST /validate/cost
through an ASGI client with only the auth principal overridden. Everything below
auth (resolve_org, the org-scoped DB writes/reads, run_loop over the REAL cost
engine on REAL generated STL parts, the served ResidualModel) runs for real.

Proves the four asks:

  * **ingest -> persist -> load -> apply** round-trips on Postgres: real records
    land org-scoped, recalibration fits a bundle, and /validate/cost then serves
    a MEASURED, validated band.
  * **zero ground truth => byte-identical**: an org with no calibration gets the
    exact assumption-band CI the residual_model=None path produces (validated
    stays False) — asserted by recomputing that CI and comparing dicts.
  * **seeded real records => MEASURED / validated**: after recalibration the
    served CI for a real-residual process flips validated=True.
  * **cross-tenant isolation**: one org's ground truth never enters another's
    calibration — org B's list is empty, B cannot read A's record (404), and
    B's served CI stays validated=False even after A calibrated.

Skipped unless DATABASE_URL is Postgres at schema head (>= migration 0011). Run:

    DATABASE_URL=postgresql://cadverify@localhost:5432/w5_gt_test \\
        CADVERIFY_CALIBRATION_DIR=/tmp/w5cal \\
        .venv/bin/python -m pytest tests/test_groundtruth_api.py -q
"""
from __future__ import annotations

import os

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)

# Distinct real parts; enough that the 30% by-part held-out split yields
# >= MIN_RESIDUALS(3) real residuals so the served band can be MEASURED.
_N_PARTS = 18
_PROC = "sls"


def _build_app():
    from fastapi import FastAPI

    from src.api.groundtruth import router as gt_router
    from src.api.routes import router as core_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(core_router, prefix="/api/v1")
    app.include_router(gt_router, prefix="/api/v1/ground-truth")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


def _cube_bytes(i: int) -> bytes:
    import trimesh

    m = trimesh.creation.box(extents=(18 + 2 * i, 14 + i, 9 + i))
    return m.export(file_type="stl")


@_requires_pg
@pytest.mark.asyncio
async def test_ingest_persist_recalibrate_serve_and_cross_tenant(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.costing.confidence import confidence_interval

    # Served + recalibrated bundles land in a scratch dir (never the shared tree).
    monkeypatch.setenv("CADVERIFY_CALIBRATION_DIR", str(tmp_path / "cal"))

    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    # Write real STL parts to disk; ingest records point part_path at them so
    # recalibration's engine run resolves them regardless of the configured dir.
    part_files = []
    for i in range(_N_PARTS):
        pid = f"gtcube-{i:02d}.stl"
        p = parts_dir / pid
        import trimesh

        trimesh.creation.box(extents=(18 + 2 * i, 14 + i, 9 + i)).export(str(p))
        part_files.append((pid, str(p)))

    org_a = str(ULID())
    org_b = str(ULID())
    created_users: list[int] = []

    async def _mk_user(s, label: str) -> int:
        email = f"gt-{org_a[:6]}-{label}@example.com"
        uid = int(
            (
                await s.execute(
                    text(
                        "INSERT INTO users (email, email_lower, role, auth_provider) "
                        "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
                    ),
                    {"e": email, "el": email.lower()},
                )
            ).first()[0]
        )
        created_users.append(uid)
        return uid

    async def _mk_org(s, oid, name):
        await s.execute(
            text(
                "INSERT INTO organizations (id, name, slug, created_at) "
                "VALUES (:id, :n, :sl, now())"
            ),
            {"id": oid, "n": name, "sl": name.lower().replace(" ", "-")},
        )

    async def _mk_membership(s, org_id, uid, role="admin"):
        await s.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                "VALUES (:id, :o, :u, :r, now())"
            ),
            {"id": str(ULID()), "o": org_id, "u": uid, "r": role},
        )

    async with eng.get_session_factory()() as s:
        await _mk_org(s, org_a, f"Org A {org_a[:6]}")
        await _mk_org(s, org_b, f"Org B {org_b[:6]}")
        a1 = await _mk_user(s, "a1")
        b1 = await _mk_user(s, "b1")
        await _mk_membership(s, org_a, a1)
        await _mk_membership(s, org_b, b1)
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)

    def _confidence_of(body, process):
        for e in body.get("estimates", []):
            if e["process"] == process:
                return e
        return None

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # ============ ACT AS a1 (org A): INGEST real ground truth ============
            _act_as(app, a1)
            for i, (pid, ppath) in enumerate(part_files):
                r = await ac.post(
                    "/api/v1/ground-truth",
                    json={
                        "part_id": pid, "process": _PROC, "quantity": 100,
                        "actual_unit_cost_usd": round(6.0 + 0.2 * i, 2),
                        "part_path": ppath, "stand_in": False,
                        "source": f"PO-{1000 + i} real quote",
                    },
                )
                assert r.status_code == 200, r.text
                assert r.json()["stand_in"] is False
                assert r.json()["id"]

            # list is org-scoped and complete
            r = await ac.get("/api/v1/ground-truth")
            assert r.status_code == 200
            body = r.json()
            assert body["total"] == _N_PARTS
            a_ids = [row["id"] for row in body["records"]]
            one_id = a_ids[0]
            # dedup: re-ingesting the same (part,process,qty,shop) keeps total flat
            r = await ac.post(
                "/api/v1/ground-truth",
                json={
                    "part_id": part_files[0][0], "process": _PROC, "quantity": 100,
                    "actual_unit_cost_usd": 99.0, "part_path": part_files[0][1],
                    "stand_in": False, "source": "PO-dup",
                },
            )
            assert r.status_code == 200
            assert (await ac.get("/api/v1/ground-truth")).json()["total"] == _N_PARTS

            # bad record (non-positive cost) is a clean 400, not a 500/persist
            r = await ac.post(
                "/api/v1/ground-truth",
                json={"part_id": "x.stl", "process": _PROC, "quantity": 1,
                      "actual_unit_cost_usd": 0},
            )
            assert r.status_code in (400, 422)

            # ============ zero ground truth => BYTE-IDENTICAL (org B) ============
            _act_as(app, b1)
            # B has no records yet
            assert (await ac.get("/api/v1/ground-truth")).json()["total"] == 0
            # B cannot read A's record (cross-tenant 404)
            assert (await ac.get(f"/api/v1/ground-truth/{one_id}")).status_code == 404

            files = {"file": ("cube.stl", _cube_bytes(0), "application/octet-stream")}
            r = await ac.post(
                "/api/v1/validate/cost", data={"qty": "100"}, files=files
            )
            assert r.status_code == 200, r.text
            b_body = r.json()
            b_est = _confidence_of(b_body, _PROC)
            assert b_est is not None, [e["process"] for e in b_body["estimates"]]
            # With NO calibration the served CI is EXACTLY the residual_model=None
            # path: recompute it and assert byte-for-byte equality + validated False.
            ref = confidence_interval(
                b_est["unit_cost_usd"],
                assumption_band_pct=b_est["est_error_band_pct"],
                residual_provider=None, process=_PROC,
            ).to_dict()
            assert b_est["confidence"] == ref
            assert b_est["confidence"]["validated"] is False

            # ============ RECALIBRATE (org A) ============
            _act_as(app, a1)
            r = await ac.post("/api/v1/ground-truth/recalibrate")
            assert r.status_code == 200, r.text
            summ = r.json()
            assert summ["from_real"] is True
            assert summ["validated"] is True
            assert summ["n_real"] >= 3
            assert summ["n_skipped"] == 0
            assert "VALIDATED" in summ["claim"]

            # ============ seeded real records => MEASURED / validated (org A) =====
            files = {"file": ("cube.stl", _cube_bytes(1), "application/octet-stream")}
            r = await ac.post(
                "/api/v1/validate/cost", data={"qty": "100"}, files=files
            )
            assert r.status_code == 200, r.text
            a_est = _confidence_of(r.json(), _PROC)
            assert a_est is not None
            assert a_est["confidence"]["validated"] is True  # MEASURED from real residuals
            assert a_est["confidence"].get("n_samples") or a_est["confidence"].get("n")

            # ============ cross-tenant: A's calibration NEVER leaks into B ========
            _act_as(app, b1)
            files = {"file": ("cube.stl", _cube_bytes(2), "application/octet-stream")}
            r = await ac.post(
                "/api/v1/validate/cost", data={"qty": "100"}, files=files
            )
            assert r.status_code == 200, r.text
            b2_est = _confidence_of(r.json(), _PROC)
            assert b2_est is not None
            # B has no ground truth -> still the assumption band, NOT validated.
            assert b2_est["confidence"]["validated"] is False
            # recalibrating B (zero records) stays honestly un-validated
            r = await ac.post("/api/v1/ground-truth/recalibrate")
            assert r.status_code == 200
            assert r.json()["from_real"] is False
            assert r.json()["validated"] is False
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(
                text("DELETE FROM ground_truth_records WHERE org_id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
            if created_users:
                await s.execute(
                    text("DELETE FROM memberships WHERE user_id = ANY(:i)"),
                    {"i": created_users},
                )
                await s.execute(
                    text("DELETE FROM users WHERE id = ANY(:i)"),
                    {"i": created_users},
                )
            await s.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
            await s.commit()
        await eng.dispose_engine()
