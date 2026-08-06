"""Parts-master feeder (identity Slice 2) — the cold-start bulk-onboard, live-PG.

Drives POST /identity/library/onboard through an ASGI client (only the auth
principal + DB session overridden — the real router, resolve_org, the mesh parse,
``upsert_signature``, and ``import_manifest`` all run against the live DB), then
asserts the corpus + declared master + retrieval behave honestly:

  * ONBOARD — a small library (cube.step + trimesh STL primitives) + an identity CSV
    → ``part_signatures`` rows carry the DECLARED identity (source parts_master),
    ``manifest_parts`` rows exist for every declared part_id, and ``library_size`` is
    exact.
  * HONEST SKIPS — a garbage file is skipped (parse), an unknown material_class is
    skipped (never coerced), a nameless part onboards UNNAMED (never guessed), a bad
    mapping row is reported — and the batch still succeeds.
  * COLD-START PAYOFF — retrieve a near-duplicate of an onboarded part → grounded,
    top match carries the part's DECLARED name. An unrelated shape → honest no-match.
  * TENANCY — org B onboards; org A's retrieval never surfaces B's identities.

Skipped unless DATABASE_URL is Postgres at schema head.
"""
from __future__ import annotations

import os
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)

_ASSETS = os.path.join(os.path.dirname(__file__), "assets")


def _build_app():
    from fastapi import FastAPI

    from src.api.identity import router as identity_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(identity_router, prefix="/api/v1/identity")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


async def _mk_org_user(s, org_id, tag, label):
    from sqlalchemy import text
    from ulid import ULID

    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ),
        {"id": org_id, "n": f"{label} {tag}", "sl": f"{org_id[-8:].lower()}"},
    )
    email = f"pm-{tag}-{label}@example.com"
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
    await s.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, 'admin', now())"
        ),
        {"id": str(ULID()), "o": org_id, "u": uid},
    )
    return uid


@_requires_pg
@pytest.mark.asyncio
async def test_onboard_cold_start_and_isolation():
    import trimesh
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.services import identity_retrieval_service as ir
    from src.services import parts_master_service as pmsvc

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())

    # A real STEP asset + geometrically-distinct STL primitives (the library).
    with open(os.path.join(_ASSETS, "cube.step"), "rb") as fh:
        cube_step = fh.read()
    plate_stl = trimesh.creation.box(extents=[120, 80, 4]).export(file_type="stl")
    rod_stl = trimesh.creation.cylinder(
        radius=6, height=120, sections=64
    ).export(file_type="stl")
    disc_stl = trimesh.creation.cylinder(
        radius=45, height=8, sections=96
    ).export(file_type="stl")
    junk = b"this is not a mesh file at all -- unparseable garbage"

    # Identity mapping: rod has NO name (onboards UNNAMED), disc has an UNKNOWN
    # material (skipped), the final row has NO filename (a reported mapping error).
    mapping_csv = (
        "filename,part_id,name,program,material_class\n"
        "cube.step,PN-CUBE,Calibration cube,Metrology,steel\n"
        "plate.stl,PN-PLATE,Mounting plate,Chassis,aluminum\n"
        "rod.stl,PN-ROD,,Drivetrain,\n"
        "disc.stl,PN-DISC,Sensor disc,Sensors,unobtanium\n"
        ",PN-ORPHAN,row with no filename,,\n"
    ).encode()

    async with eng.get_session_factory()() as s:
        uid_a = await _mk_org_user(s, org_a, tag, "a")
        uid_b = await _mk_org_user(s, org_b, tag, "b")
        await s.commit()

    async def _real_session():
        async with eng.get_session_factory()() as s:
            yield s

    from src.db.engine import get_db_session

    app = _build_app()
    app.dependency_overrides[get_db_session] = _real_session
    transport = ASGITransport(app=app)

    onboard_files = [
        ("files", ("cube.step", cube_step, "application/octet-stream")),
        ("files", ("plate.stl", plate_stl, "application/octet-stream")),
        ("files", ("rod.stl", rod_stl, "application/octet-stream")),
        ("files", ("disc.stl", disc_stl, "application/octet-stream")),
        ("files", ("junk.stl", junk, "application/octet-stream")),
        ("mapping", ("identity.csv", mapping_csv, "text/csv")),
    ]

    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # ── ONBOARD (org A) ─────────────────────────────────────────────────
        _act_as(app, uid_a)
        r = await c.post("/api/v1/identity/library/onboard", files=onboard_files)
        assert r.status_code == 200, r.text
        summary = r.json()
        # 3 parts onboarded (cube, plate, rod); disc (bad material) + junk (parse)
        # skipped; rod is unnamed. Manifest registered for the 3 declared part_ids.
        assert summary["onboarded"] == 3, summary
        assert summary["unnamed"] == 1, summary
        assert summary["library_size"] == 3, summary
        assert summary["manifest_registered"] == 3, summary
        skip_names = {sk["filename"] for sk in summary["skipped"]}
        assert "junk.stl" in skip_names and "disc.stl" in skip_names, summary
        disc_reason = next(sk["reason"] for sk in summary["skipped"] if sk["filename"] == "disc.stl")
        assert "material_class" in disc_reason
        # the no-filename mapping row is reported honestly, never fabricated.
        assert any("filename" in e.get("reason", "") for e in summary["mapping_errors"]), summary

        # ── GET /library reflects the corpus size ───────────────────────────
        r = await c.get("/api/v1/identity/library")
        assert r.status_code == 200, r.text
        lib = r.json()
        assert lib["library_size"] == 3
        assert len(lib["recent"]) == 3
        recent_names = {row["declared_name"] for row in lib["recent"]}
        assert "Mounting plate" in recent_names
        assert None in recent_names  # the nameless rod is honestly unnamed

    # ── the corpus rows carry the DECLARED identity + source parts_master ────
    from src.services import part_signature_service as sigsvc

    async with eng.get_session_factory()() as s:
        rows = await sigsvc.list_signatures(s, org_a)
        assert len(rows) == 3
        by_pn = {r.declared_part_id: r for r in rows}
        assert set(by_pn) == {"PN-CUBE", "PN-PLATE", "PN-ROD"}
        assert by_pn["PN-PLATE"].declared_name == "Mounting plate"
        assert by_pn["PN-PLATE"].program == "Chassis"
        assert by_pn["PN-ROD"].declared_name is None  # unnamed, not guessed
        assert all(r.source == pmsvc.SOURCE_PARTS_MASTER for r in rows)

        # declared master (ManifestPart) rows exist for the 3 declared part_ids.
        mrows = (
            await s.execute(
                text("SELECT part_id, description, program FROM manifest_parts WHERE org_id = :o"),
                {"o": org_a},
            )
        ).all()
        m_by_pn = {row[0]: row for row in mrows}
        assert set(m_by_pn) == {"PN-CUBE", "PN-PLATE", "PN-ROD"}
        assert m_by_pn["PN-PLATE"][1] == "Mounting plate"  # name → description

        # ── COLD-START PAYOFF: a near-duplicate plate retrieves the DECLARED name.
        near_dup = trimesh.creation.box(extents=[122, 81, 4.1])
        res = await ir.retrieve_identity(s, org_a, near_dup, name_hint="mounting plate", k=3)
        assert res.grounded is True, res.to_dict()
        assert res.matches[0].declared_part_id == "PN-PLATE"
        assert res.matches[0].declared_name == "Mounting plate"

        # ── HONEST NO-MATCH: an unrelated torus grounds nothing.
        weird = trimesh.creation.torus(major_radius=30, minor_radius=6)
        miss = await ir.retrieve_identity(s, org_a, weird, name_hint="gizmo", k=3)
        assert miss.grounded is False, miss.to_dict()

    # ── TENANCY: org B onboards its OWN part; org A never sees it ────────────
    b_stl = trimesh.creation.box(extents=[121, 79, 4.05]).export(file_type="stl")
    b_files = [
        ("files", ("bpart.stl", b_stl, "application/octet-stream")),
        (
            "mapping",
            (
                "b.csv",
                b"filename,part_id,name,program\nbpart.stl,PN-B,Secret B plate,Skunkworks\n",
                "text/csv",
            ),
        ),
    ]
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        _act_as(app, uid_b)
        r = await c.post("/api/v1/identity/library/onboard", files=b_files)
        assert r.status_code == 200, r.text
        assert r.json()["onboarded"] == 1

    async with eng.get_session_factory()() as s:
        # org A corpus is unchanged (still 3) and never carries B's identity.
        a_rows = await sigsvc.list_signatures(s, org_a)
        assert len(a_rows) == 3
        assert all(r.declared_part_id != "PN-B" for r in a_rows)
        near_dup = trimesh.creation.box(extents=[121, 79, 4.05])
        res_a = await ir.retrieve_identity(s, org_a, near_dup, name_hint="plate", k=5)
        assert all(m.declared_part_id != "PN-B" for m in res_a.matches)
        # org B sees only its own single part.
        b_rows = await sigsvc.list_signatures(s, org_b)
        assert len(b_rows) == 1 and b_rows[0].declared_part_id == "PN-B"

    # ── cleanup ─────────────────────────────────────────────────────────────
    async with eng.get_session_factory()() as s:
        for tbl in ("part_signatures", "manifest_parts"):
            await s.execute(
                text(f"DELETE FROM {tbl} WHERE org_id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
        await s.execute(
            text("DELETE FROM memberships WHERE org_id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.execute(
            text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": uid_a, "b": uid_b}
        )
        await s.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.commit()
    await eng.dispose_engine()
