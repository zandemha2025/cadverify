"""Aramco GAP 3 — parts-manifest bulk onboarding.

Two layers, mirroring ``test_groundtruth_import.py``:

  * **parser** (``parse_manifest_csv``) — pure, no DB/IO: a good CSV yields N
    declared rows with no errors; a mixed CSV yields the valid rows + precise
    per-line errors; an all-bad / bad-header / empty file yields 0 rows + errors.
    Malformed rows are REPORTED, never silently coerced or dropped.
  * **Postgres** (skipped unless DATABASE_URL is Postgres): import UPSERT +
    org isolation, geometry coverage (normalized-stem match), and keyset paging.
"""
from __future__ import annotations

import os

import pytest

from src.services import manifest_service as svc


# ── pure parser ──────────────────────────────────────────────────────────────
GOOD_CSV = (
    "part_id,description,material_class,program,parent_assembly,units_per_parent,"
    "annual_volume,quantity,region,source,notes\n"
    "AR-1,impeller,steel,GF-Phase1,ASSY-1,2,120,240,SA,SAP,critical\n"
    "AR-2,housing,aluminum,GF-Phase1,ASSY-1,1,,10,,,\n"
    "AR-3,seal,,GF-Phase2,,,,, ,,\n"
)


def test_good_csv_yields_all_declared_rows():
    rows, errors = svc.parse_manifest_csv(GOOD_CSV)
    assert errors == []
    assert len(rows) == 3
    a = rows[0]
    assert a["part_id"] == "AR-1"
    assert a["description"] == "impeller"
    assert a["material_class"] == "steel"
    assert a["program"] == "GF-Phase1"
    assert a["parent_assembly"] == "ASSY-1"
    assert a["units_per_parent"] == 2
    assert a["annual_volume"] == 120
    assert a["quantity"] == 240
    assert a["region"] == "SA"
    # blank optional columns normalise to None — nothing fabricated
    b = rows[1]
    assert b["annual_volume"] is None
    assert b["region"] is None
    c = rows[2]
    assert c["material_class"] is None  # blank material_class allowed -> None
    assert c["program"] == "GF-Phase2"
    assert c["parent_assembly"] is None


def test_mixed_csv_reports_precise_per_line_errors():
    csv_text = (
        "part_id,material_class,units_per_parent,annual_volume,quantity\n"
        "ok-1,steel,2,10,5\n"            # line 2 valid
        ",steel,2,10,5\n"                # line 3 missing part_id
        "bad-qty,steel,2,10,zero\n"      # line 4 non-integer quantity
        "bad-mat,unobtainium,2,10,5\n"   # line 5 unknown material
        "ok-2,,1,,\n"                    # line 6 valid (blank material/qty ok)
        "bad-upp,steel,0,10,5\n"         # line 7 units_per_parent not > 0
    )
    rows, errors = svc.parse_manifest_csv(csv_text)
    assert [r["part_id"] for r in rows] == ["ok-1", "ok-2"]

    by_line = {e["line"]: e["reason"] for e in errors}
    assert set(by_line) == {3, 4, 5, 7}
    assert "missing part_id" in by_line[3]
    assert "integer" in by_line[4]
    assert "unknown material_class" in by_line[5]
    assert "must be > 0" in by_line[7]


def test_missing_required_column_is_a_header_error():
    csv_text = "description,program\nsome part,GF\n"  # no part_id column
    rows, errors = svc.parse_manifest_csv(csv_text)
    assert rows == []
    assert len(errors) == 1
    assert errors[0]["line"] == 1
    assert "part_id" in errors[0]["reason"]


def test_all_bad_rows_yield_zero_rows_plus_errors():
    csv_text = (
        "part_id,quantity\n"
        ",5\n"          # missing part_id
        "a,-1\n"        # quantity not > 0
        "b,notint\n"    # quantity non-integer
    )
    rows, errors = svc.parse_manifest_csv(csv_text)
    assert rows == []
    assert {e["line"] for e in errors} == {2, 3, 4}


def test_empty_file_reports_error_not_crash():
    rows, errors = svc.parse_manifest_csv("")
    assert rows == []
    assert len(errors) == 1 and errors[0]["line"] == 0

    rows, errors = svc.parse_manifest_csv("   \n  \n")
    assert rows == []
    assert len(errors) == 1


def test_blank_lines_are_skipped_not_errored():
    csv_text = "part_id\nAR-1\n\nAR-2\n"
    rows, errors = svc.parse_manifest_csv(csv_text)
    assert [r["part_id"] for r in rows] == ["AR-1", "AR-2"]
    assert errors == []


def test_bom_prefixed_header_is_tolerated():
    rows, errors = svc.parse_manifest_csv("﻿" + GOOD_CSV)
    assert errors == []
    assert len(rows) == 3


# ── optional end-to-end (real Postgres) ──────────────────────────────────────
_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


async def _seed_org_user(s, oid: str, label: str) -> int:
    """Insert an org + analyst user + membership; return the user id."""
    from ulid import ULID
    from sqlalchemy import text

    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ),
        {"id": oid, "n": f"Org {label} {oid[-8:]}", "sl": f"org-{oid[-8:].lower()}"},
    )
    email = f"mani-{oid[-8:]}-{label}@example.com"
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
        {"id": str(ULID()), "o": oid, "u": uid},
    )
    return uid


async def _insert_analysis(s, oid: str, uid: int, filename: str) -> None:
    """Minimal analysis row (only the columns the coverage match needs are
    meaningful; the rest satisfy NOT NULL)."""
    from ulid import ULID
    from sqlalchemy import text

    await s.execute(
        text(
            "INSERT INTO analyses (ulid, user_id, org_id, mesh_hash, "
            "process_set_hash, analysis_version, filename, file_type, "
            "file_size_bytes, result_json, verdict, face_count, duration_ms, "
            "created_at) VALUES (:ulid, :uid, :oid, :mh, 'ps', 'v1', :fn, 'stl', "
            "100, '{}', 'ok', 10, 1.0, now())"
        ),
        {
            "ulid": str(ULID()),
            "uid": uid,
            "oid": oid,
            "mh": str(ULID()),
            "fn": filename,
        },
    )


async def _cleanup(oids: list[str], uids: list[int]) -> None:
    from sqlalchemy import text

    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(
            text("DELETE FROM manifest_parts WHERE org_id = ANY(:o)"), {"o": oids}
        )
        await s.execute(
            text("DELETE FROM analyses WHERE org_id = ANY(:o)"), {"o": oids}
        )
        if uids:
            await s.execute(
                text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": uids}
            )
            await s.execute(
                text("DELETE FROM users WHERE id = ANY(:i)"), {"i": uids}
            )
        await s.execute(
            text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": oids}
        )
        await s.commit()


def _build_app():
    from fastapi import FastAPI

    from src.api.manifest import router as mani_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(mani_router, prefix="/api/v1/manifest")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


@_requires_pg
@pytest.mark.asyncio
async def test_import_upsert_and_org_isolation():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID

    import src.db.engine as eng

    org_a, org_b = str(ULID()), str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        b1 = await _seed_org_user(s, org_b, "B")
        uids += [a1, b1]
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            csv1 = (
                "part_id,program,quantity\n"
                "AR-1,GF-Phase1,10\n"
                "AR-2,GF-Phase1,20\n"
                "AR-bad,GF,notint\n"  # reported, skipped
            )
            r = await ac.post(
                "/api/v1/manifest/import",
                files={"file": ("m.csv", csv1.encode(), "text/csv")},
            )
            assert r.status_code == 200, r.text
            summ = r.json()
            assert summ["imported"] == 2
            assert summ["updated"] == 0
            assert summ["skipped"] == 1
            assert summ["total"] == 3
            assert summ["errors"][0]["line"] == 4

            # re-import the SAME part_ids with changed values -> UPDATE, not dup
            csv2 = "part_id,program,quantity\nAR-1,GF-Phase2,99\nAR-9,GF-Phase2,1\n"
            r2 = await ac.post(
                "/api/v1/manifest/import",
                files={"file": ("m.csv", csv2.encode(), "text/csv")},
            )
            summ2 = r2.json()
            assert summ2["imported"] == 1  # AR-9 new
            assert summ2["updated"] == 1   # AR-1 updated
            assert summ2["skipped"] == 0

            body = (await ac.get("/api/v1/manifest")).json()
            parts = {p["part_id"]: p for p in body["parts"]}
            assert set(parts) == {"AR-1", "AR-2", "AR-9"}  # no duplicate AR-1
            assert parts["AR-1"]["program"] == "GF-Phase2"  # last write wins
            assert parts["AR-1"]["quantity"] == 99

            # cross-tenant: org B sees NONE of A's parts
            _act_as(app, b1)
            assert (await ac.get("/api/v1/manifest")).json()["parts"] == []
    finally:
        await _cleanup([org_a, org_b], uids)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_coverage_geometry_and_by_program():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID

    import src.db.engine as eng

    org_a, org_empty = str(ULID()), str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        e1 = await _seed_org_user(s, org_empty, "E")
        uids += [a1, e1]
        # analyses: AR-1 <-> AR-1.stl (bare-id vs .stl); AR-2.step <-> AR-2.stp
        await _insert_analysis(s, org_a, a1, "AR-1.stl")
        await _insert_analysis(s, org_a, a1, "AR-2.stp")
        await _insert_analysis(s, org_a, a1, "UNRELATED.stl")  # matches nothing
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            csv1 = (
                "part_id,program\n"
                "AR-1,Alpha\n"        # matches AR-1.stl (bare <-> .stl)
                "AR-2.step,Alpha\n"   # matches AR-2.stp (.step <-> .stp)
                "AR-3,Beta\n"         # no geometry
                "AR-4,\n"             # no program, no geometry
            )
            await ac.post(
                "/api/v1/manifest/import",
                files={"file": ("m.csv", csv1.encode(), "text/csv")},
            )
            cov = (await ac.get("/api/v1/manifest/coverage")).json()
            assert cov["total_declared"] == 4
            assert cov["geometry"]["with_geometry"] == 2
            assert cov["geometry"]["without_geometry"] == 2
            assert cov["geometry"]["match"] == "normalized-stem, exact"
            by_prog = {d["program"]: d["count"] for d in cov["by_program"]}
            assert by_prog == {"Alpha": 2, "Beta": 1, "(unassigned)": 1}

            # a genuinely empty org -> zeroed
            _act_as(app, e1)
            cov_e = (await ac.get("/api/v1/manifest/coverage")).json()
            assert cov_e["total_declared"] == 0
            assert cov_e["by_program"] == []
            assert cov_e["geometry"]["with_geometry"] == 0
            assert cov_e["geometry"]["without_geometry"] == 0
    finally:
        await _cleanup([org_a, org_empty], uids)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_keyset_list_walks_every_part_once():
    from httpx import ASGITransport, AsyncClient
    from ulid import ULID

    import src.db.engine as eng

    org_a = str(ULID())
    uids: list[int] = []
    async with eng.get_session_factory()() as s:
        a1 = await _seed_org_user(s, org_a, "A")
        uids.append(a1)
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            n = 25
            body_csv = "part_id\n" + "".join(f"P-{i:03d}\n" for i in range(n))
            await ac.post(
                "/api/v1/manifest/import",
                files={"file": ("m.csv", body_csv.encode(), "text/csv")},
            )
            seen: list[str] = []
            cursor = None
            pages = 0
            while True:
                url = "/api/v1/manifest?limit=10"
                if cursor:
                    url += f"&cursor={cursor}"
                page = (await ac.get(url)).json()
                pages += 1
                seen += [p["part_id"] for p in page["parts"]]
                cursor = page["next_cursor"]
                if cursor is None:
                    break
                assert pages < 10  # guard against a paging loop
            # every part exactly once, in ascending order, no overlap/skip
            assert len(seen) == n
            assert seen == sorted(seen)
            assert len(set(seen)) == n
            assert pages == 3  # 10 + 10 + 5
    finally:
        await _cleanup([org_a], uids)
        await eng.dispose_engine()
