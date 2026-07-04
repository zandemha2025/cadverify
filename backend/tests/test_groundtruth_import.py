"""W5 flywheel — historical-cost CSV bulk import.

Two layers, both runnable without Postgres:

  * **parser** (``parse_ground_truth_csv``) — pure, no DB/IO: a good CSV yields N
    valid REAL rows; a mixed CSV yields the valid rows + precise per-line errors;
    an all-bad / bad-header / empty file yields 0 rows + errors. Malformed rows
    are REPORTED, never silently coerced or dropped.
  * **oversize guard** (``_read_capped_chunks``) — a stream over the cap is
    rejected 413 WITHOUT buffering the whole payload (it stops pulling chunks the
    moment the running total crosses the cap).

An optional end-to-end API test (skipped unless DATABASE_URL is Postgres at
schema head >= 0011) proves import -> persist funnels through the single-record
create path: rows land org-scoped and REAL (stand_in=False), bad rows are
reported, and one org's import never leaks into another's.
"""
from __future__ import annotations

import os

import pytest

from src.services import groundtruth_service as svc


# ── pure parser ──────────────────────────────────────────────────────────────
GOOD_CSV = (
    "part_id,process,quantity,actual_unit_cost_usd,material_class,shop,region,"
    "currency,source,part_path,notes\n"
    "widget-a.stl,cnc_3axis,100,42.50,aluminum,acme,US,USD,PO-1001,,first\n"
    "widget-b.stl,sls,50,12.00,polymer,,,,,,\n"
    "widget-c.stl,injection_molding,1000,3.25,polymer,acme,MX,usd,PO-1002,,\n"
)


def test_good_csv_yields_all_real_rows():
    rows, errors = svc.parse_ground_truth_csv(GOOD_CSV)
    assert errors == []
    assert len(rows) == 3
    # imported historical costs are REAL — never stand-in.
    assert all(r["stand_in"] is False for r in rows)
    a = rows[0]
    assert a["part_id"] == "widget-a.stl"
    assert a["process"] == "cnc_3axis"
    assert a["quantity"] == 100
    assert a["actual_unit_cost_usd"] == 42.5
    assert a["material_class"] == "aluminum"
    assert a["shop"] == "acme"
    # blank optional columns normalise to defaults / None
    b = rows[1]
    assert b["material_class"] == "polymer"
    assert b["currency"] == "USD"
    assert b["shop"] is None and b["region"] is None
    # lower-case currency is upper-cased, not rejected
    assert rows[2]["currency"] == "USD"


def test_mixed_csv_reports_precise_per_line_errors():
    csv_text = (
        "part_id,process,quantity,actual_unit_cost_usd,material_class\n"
        "ok-1.stl,sls,10,5.00,polymer\n"          # line 2 valid
        "bad-proc.stl,laser_zap,10,5.00,polymer\n"  # line 3 unknown process
        "neg-cost.stl,sls,10,-5.00,polymer\n"     # line 4 negative cost
        ",sls,10,5.00,polymer\n"                   # line 5 missing part_id
        "ok-2.stl,mjf,20,9.00,titanium\n"         # line 6 valid
        "bad-qty.stl,sls,zero,5.00,polymer\n"     # line 7 non-integer qty
        "bad-mat.stl,sls,10,5.00,unobtainium\n"   # line 8 unknown material
    )
    rows, errors = svc.parse_ground_truth_csv(csv_text)
    # only the two well-formed rows survive
    assert [r["part_id"] for r in rows] == ["ok-1.stl", "ok-2.stl"]
    assert all(r["stand_in"] is False for r in rows)

    by_line = {e["line"]: e["reason"] for e in errors}
    assert set(by_line) == {3, 4, 5, 7, 8}
    assert "unknown process" in by_line[3]
    assert "must be > 0" in by_line[4]
    assert "missing part_id" in by_line[5]
    assert "integer" in by_line[7]
    assert "unknown material_class" in by_line[8]


def test_missing_required_column_is_a_header_error():
    # no actual_unit_cost_usd column at all
    csv_text = "part_id,process,quantity\nx.stl,sls,10\n"
    rows, errors = svc.parse_ground_truth_csv(csv_text)
    assert rows == []
    assert len(errors) == 1
    assert errors[0]["line"] == 1
    assert "actual_unit_cost_usd" in errors[0]["reason"]


def test_all_bad_rows_yield_zero_rows_plus_errors():
    csv_text = (
        "part_id,process,quantity,actual_unit_cost_usd\n"
        "a.stl,nope,10,5\n"
        "b.stl,sls,-1,5\n"
        "c.stl,sls,10,0\n"
    )
    rows, errors = svc.parse_ground_truth_csv(csv_text)
    assert rows == []
    assert len(errors) == 3
    assert {e["line"] for e in errors} == {2, 3, 4}


def test_empty_file_reports_error_not_crash():
    rows, errors = svc.parse_ground_truth_csv("")
    assert rows == []
    assert len(errors) == 1 and errors[0]["line"] == 0

    rows, errors = svc.parse_ground_truth_csv("   \n  \n")
    assert rows == []
    assert len(errors) == 1


def test_blank_lines_are_skipped_not_errored():
    csv_text = (
        "part_id,process,quantity,actual_unit_cost_usd\n"
        "a.stl,sls,10,5\n"
        "\n"
        "b.stl,mjf,20,9\n"
    )
    rows, errors = svc.parse_ground_truth_csv(csv_text)
    assert len(rows) == 2
    assert errors == []


def test_bom_prefixed_header_is_tolerated():
    rows, errors = svc.parse_ground_truth_csv("﻿" + GOOD_CSV)
    assert errors == []
    assert len(rows) == 3


# ── oversize streaming guard (no full buffering) ─────────────────────────────
@pytest.mark.asyncio
async def test_oversize_stream_rejected_413_without_full_buffering():
    from fastapi import HTTPException

    from src.api.groundtruth import _read_capped_chunks

    limit = 16  # bytes
    yielded = {"n": 0}

    async def _chunks():
        # 100 chunks of 4 bytes = 400 bytes >> 16-byte cap; a correct guard must
        # raise long before consuming them all.
        for _ in range(100):
            yielded["n"] += 1
            yield b"AAAA"

    with pytest.raises(HTTPException) as ei:
        await _read_capped_chunks(_chunks(), limit)
    assert ei.value.status_code == 413
    # stopped early — did NOT pull all 100 chunks into memory
    assert yielded["n"] <= 6


@pytest.mark.asyncio
async def test_empty_stream_rejected_400():
    from fastapi import HTTPException

    from src.api.groundtruth import _read_capped_chunks

    async def _chunks():
        return
        yield  # pragma: no cover

    with pytest.raises(HTTPException) as ei:
        await _read_capped_chunks(_chunks(), 1024)
    assert ei.value.status_code == 400


# ── optional end-to-end (real Postgres + real create path) ───────────────────
_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


@_requires_pg
@pytest.mark.asyncio
async def test_import_persists_real_org_scoped_and_isolated():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    def _build_app():
        from fastapi import FastAPI

        from src.api.groundtruth import router as gt_router
        from src.auth.rate_limit import limiter

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(gt_router, prefix="/api/v1/ground-truth")
        return app

    def _act_as(app, user_id: int) -> None:
        from src.auth.require_api_key import AuthedUser, require_api_key

        app.dependency_overrides[require_api_key] = lambda: AuthedUser(
            user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
        )

    org_a, org_b = str(ULID()), str(ULID())
    created_users: list[int] = []

    async def _mk_user(s, label: str) -> int:
        email = f"gti-{org_a[:6]}-{label}@example.com"
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

    async with eng.get_session_factory()() as s:
        for oid, nm in ((org_a, "A"), (org_b, "B")):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": f"Org {nm} {oid[-8:]}", "sl": f"org-{oid[-8:].lower()}"},
            )
        a1 = await _mk_user(s, "a1")
        b1 = await _mk_user(s, "b1")
        for oid, uid in ((org_a, a1), (org_b, b1)):
            await s.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                    "VALUES (:id, :o, :u, 'admin', now())"
                ),
                {"id": str(ULID()), "o": oid, "u": uid},
            )
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    csv_body = (
        "part_id,process,quantity,actual_unit_cost_usd,material_class,source\n"
        "imp-a.stl,cnc_3axis,100,42.50,aluminum,PO-1\n"
        "imp-b.stl,sls,50,12.00,polymer,PO-2\n"
        "imp-bad.stl,not_a_process,10,5.00,polymer,PO-3\n"  # reported, skipped
    )
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, a1)
            files = {"file": ("hist.csv", csv_body.encode(), "text/csv")}
            r = await ac.post("/api/v1/ground-truth/import", files=files)
            assert r.status_code == 200, r.text
            summ = r.json()
            assert summ["imported"] == 2
            assert summ["skipped"] == 1
            assert summ["total"] == 3
            assert summ["errors"][0]["line"] == 4  # the bad row's file line

            # persisted, org-scoped, and REAL (stand_in=False) => counts toward calibration
            body = (await ac.get("/api/v1/ground-truth")).json()
            assert body["total"] == 2
            assert all(rec["stand_in"] is False for rec in body["records"])

            # cross-tenant: org B sees NONE of A's imported rows
            _act_as(app, b1)
            assert (await ac.get("/api/v1/ground-truth")).json()["total"] == 0
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
