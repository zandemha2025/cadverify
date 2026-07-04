"""Analogy k-NN live-endpoint integration (P1) against live Postgres.

Proves the analogy-to-quote member goes from DORMANT to CONTRIBUTING through the
real ``POST /validate/cost`` path once an org has REAL ground-truth records that
carry geometry:

  * ingest a few REAL cnc_3axis records WITH resolvable meshes for org A (ingest
    computes + stores geometry), then POST an aluminum box with
    ``COST_ENSEMBLE_ENABLED=1`` -> the ``uncertainty`` block has a band with
    ``has_real_member=True`` (the analogy fired), while ``validated`` stays False.
  * a different org B with no records gets NO band with ``has_real_member`` True
    (cross-tenant isolation — one org's quotes never enter another's band).

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``).
Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/analogy_test \\
        .venv/bin/python -m pytest tests/test_analogy_live_api.py -q
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)

PROC = "cnc_3axis"
QTY = 100


def _build_app():
    from fastapi import FastAPI

    from src.api.routes import router as api_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api_router, prefix="/api/v1")
    return app


def _act_as(app, user_id: int, session_factory) -> None:
    """Override the analyst-role auth (composes with require_api_key) and the DB
    session dependency with a REAL Postgres session."""
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )

    async def _session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db_session] = _session


def _write_boxes(dirpath, n):
    import trimesh

    paths = []
    for i in range(n):
        m = trimesh.creation.box(extents=[38.0 + i, 28.0 + i, 22.0 + i])
        p = os.path.join(dirpath, f"gt_box_{i}.stl")
        m.export(p)
        paths.append(p)
    return paths


def _box_stl_bytes():
    import io

    import trimesh

    m = trimesh.creation.box(extents=[40.0, 30.0, 25.0])
    buf = io.BytesIO()
    m.export(buf, file_type="stl")
    return buf.getvalue()


@_requires_pg
@pytest.mark.asyncio
async def test_analogy_member_activates_live_and_is_org_isolated(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.services.groundtruth_service import ingest_record

    monkeypatch.setenv("COST_ENSEMBLE_ENABLED", "1")

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())
    sf = eng.get_session_factory()

    async def _mk_user(s, label):
        email = f"al-{tag}-{label}@example.com"
        return int(
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

    async with sf() as s:
        for oid, nm in ((org_a, f"A {tag}"), (org_b, f"B {tag}")):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": nm, "sl": f"{oid[-8:].lower()}"},
            )
        uid_a = await _mk_user(s, "a")
        uid_b = await _mk_user(s, "b")
        for oid, uid in ((org_a, uid_a), (org_b, uid_b)):
            await s.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                    "VALUES (:id, :o, :u, 'admin', now())"
                ),
                {"id": str(ULID()), "o": oid, "u": uid},
            )
        await s.commit()

    # ── ingest REAL cnc_3axis records WITH resolvable meshes for org A ────────
    # ingest_record resolves each part_path to a mesh and stores the MEASURED
    # geometry, so these records can be analogy neighbours.
    tmpdir = tempfile.mkdtemp()
    box_paths = _write_boxes(tmpdir, 4)
    async with sf() as s:
        for i, p in enumerate(box_paths):
            row = await ingest_record(
                s, org_a, uid_a,
                {
                    "part_id": f"gt_box_{i}.stl",
                    "process": PROC,
                    "quantity": QTY,
                    "actual_unit_cost_usd": 120.0 + 5 * i,
                    "material_class": "aluminum",
                    # secure resolution: the mesh lives in a trusted server
                    # corpus (parts_dir) and resolves by part_id — NOT via a
                    # network-supplied absolute part_path (now rejected).
                    "source": "PO-real",
                    "stand_in": False,
                },
                parts_dir=tmpdir,
            )
            # geometry was populated best-effort at ingest
            assert row.volume_cm3 is not None and row.face_count is not None
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    box = _box_stl_bytes()

    def _has_real_band(body):
        assert "uncertainty" in body, body
        bands = body["uncertainty"]["bands"]
        return [b for b in bands if b.get("has_real_member")]

    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # ── org A: the analogy member fires on the cnc_3axis band ────────────
        _act_as(app, uid_a, sf)
        r = await c.post(
            "/api/v1/validate/cost",
            files={"file": ("box.stl", box, "application/octet-stream")},
            data={"qty": str(QTY), "material_class": "aluminum", "region": "US"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        real_bands = _has_real_band(body)
        assert real_bands, body["uncertainty"]["bands"]
        rb = next(b for b in real_bands if b["process"] == PROC)
        assert rb["n_real_neighbors"] >= 3
        assert rb["combined_usd"] is not None
        # honesty: a contributing analogy member is NOT a measured-accuracy claim
        assert rb["validated"] is False
        assert body["uncertainty"]["validated"] is False

        # ── org B: no records -> analogy never fires (cross-tenant isolation) ─
        _act_as(app, uid_b, sf)
        r = await c.post(
            "/api/v1/validate/cost",
            files={"file": ("box.stl", box, "application/octet-stream")},
            data={"qty": str(QTY), "material_class": "aluminum", "region": "US"},
        )
        assert r.status_code == 200, r.text
        body_b = r.json()
        assert not _has_real_band(body_b)  # no band claims a real member
        for b in body_b["uncertainty"]["bands"]:
            assert b.get("has_real_member", False) is False
            assert b["validated"] is False

    # ── cleanup ──────────────────────────────────────────────────────────────
    async with sf() as s:
        await s.execute(
            text("DELETE FROM ground_truth_records WHERE org_id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.execute(
            text("DELETE FROM memberships WHERE org_id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.execute(
            text("DELETE FROM users WHERE id IN (:a, :b)"),
            {"a": uid_a, "b": uid_b},
        )
        await s.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.commit()
    # Release the async engine bound to THIS test's event loop (repo convention —
    # asyncpg pools are loop-bound; the next PG test rebuilds on its own loop).
    await eng.dispose_engine()
