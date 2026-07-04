"""Catalog API integration tests (W1 step 4) against live Postgres.

Drives ``GET /api/v1/catalog`` through an ASGI client with only the auth
principal overridden — everything below auth (require_role -> require_api_key,
the real get_db_session -> resolve_org -> the org-scoped catalog build) runs
against the live DB. Proves the four asks:

  * Cross-tenant isolation — org A never sees org B's parts, and vice-versa
    (the tenant boundary is the ORG: org-mate a2's parts ARE visible to a1).
  * Pagination — page/page_size slice a real ``total`` with consistent
    ``has_more``.
  * Empty state — a fresh org's catalog is an empty grid, not an error.
  * Facets — state / route / has_findings filter on real derived fields, and
    the facet summary counts match.

Also asserts the grid's honesty: a DFM-blocked route withholds its price, and a
costed-but-un-analyzed part reports ``findings: null`` (not a fabricated zero).

Skipped unless DATABASE_URL is Postgres at schema head. Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/catalog_iso_test \\
        .venv/bin/python -m pytest tests/test_catalog_api.py -q
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _build_app():
    """A FastAPI app mounting the catalog router at its real prefix, with the
    slowapi limiter state the @limiter.limit route needs."""
    from fastapi import FastAPI

    from src.api.catalog import router as catalog_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(catalog_router, prefix="/api/v1/catalog")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


# --- analysis result_json builders (real shapes) ---------------------------


def _analysis_result(best="cnc_3axis", *, clean=False):
    if clean:
        return {"best_process": best, "universal_issues": [], "process_scores": []}
    return {
        "best_process": best,
        "universal_issues": [
            {"code": "NON_WATERTIGHT", "severity": "error", "message": "not watertight"},
        ],
        "process_scores": [
            {
                "process": "cnc_3axis",
                "recommended_material": "aluminum_6061",
                "issues": [
                    {"code": "DEEP_POCKET", "severity": "warning", "message": "deep pocket"},
                ],
            },
            {
                "process": "die_casting",
                "recommended_material": "zamak",
                "issues": [
                    {"code": "NO_DRAFT", "severity": "error", "message": "no draft"},
                ],
            },
        ],
    }


def _cost_result(*, process="cnc_3axis", dfm_ready=True, blockers=None):
    return {
        "decision": {
            "make_now_process": process,
            "make_now_material": "aluminum_6061",
            "crossover_qty": 500.0,
        },
        "estimates": [
            {
                "process": process,
                "material": "aluminum_6061",
                "quantity": 50,
                "unit_cost_usd": 12.5,
                "dfm_ready": dfm_ready,
                "dfm_blockers": blockers or [],
                "confidence": {"validated": False, "label": "assumption band"},
                "drivers": [
                    {"name": "machine_rate", "provenance": "DEFAULT", "source": "generic"},
                    {"name": "labor_rate", "provenance": "SHOP", "source": "your shop"},
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_keyset_bad_cursor_is_400_not_500(monkeypatch):
    """A malformed keyset cursor is a client error (400 'invalid cursor'), never an
    unhandled 500. No DB needed: resolve_org is stubbed to a fake org and the bad
    cursor fails to decode BEFORE any query runs."""
    from httpx import ASGITransport, AsyncClient

    from src.api.errors import structured_http_error_handler
    from src.db.engine import get_db_session

    async def _fake_resolve_org(_session, _user_id):
        return "org-fake"

    monkeypatch.setattr("src.api.catalog.resolve_org", _fake_resolve_org)

    app = _build_app()
    # structured error handler so HTTPException(400) serializes like the real app.
    from fastapi import HTTPException as _HTTPException
    from starlette.exceptions import HTTPException as _StarletteHTTPException

    app.add_exception_handler(_HTTPException, structured_http_error_handler)
    app.add_exception_handler(_StarletteHTTPException, structured_http_error_handler)
    # get_db_session is never actually used (decode fails first), but must resolve.
    app.dependency_overrides[get_db_session] = lambda: object()
    _act_as(app, 1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for bad in ("@@@not-base64@@@", "bm8tc2VwYXJhdG9y", "bm90LWlzb3xtZXNo"):
            r = await ac.get(f"/api/v1/catalog?keyset=true&cursor={bad}")
            assert r.status_code == 400, (bad, r.text)
            assert "invalid cursor" in r.text


@_requires_pg
@pytest.mark.asyncio
async def test_catalog_isolation_pagination_facets_and_honesty():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_a = str(ULID())
    org_b = str(ULID())
    org_empty = str(ULID())
    created_users: list[int] = []

    async def _mk_user(s, label: str) -> int:
        email = f"cat-{tag}-{label}@example.com"
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

    async def _mk_membership(s, org_id, uid, role):
        await s.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                "VALUES (:id, :o, :u, :r, now())"
            ),
            {"id": str(ULID()), "o": org_id, "u": uid, "r": role},
        )

    async def _mk_analysis(s, org_id, uid, mesh, result) -> str:
        u = str(ULID())
        await s.execute(
            text(
                "INSERT INTO analyses (ulid, user_id, org_id, mesh_hash, "
                "process_set_hash, analysis_version, filename, file_type, "
                "file_size_bytes, result_json, verdict, face_count, duration_ms) "
                "VALUES (:ul, :u, :o, :mh, :ph, '0.3.0', :fn, 'stl', 1024, "
                "CAST(:rj AS jsonb), 'issues', 12, 50.0)"
            ),
            {
                "ul": u, "u": uid, "o": org_id, "mh": mesh,
                "ph": f"pset-{u}", "fn": f"{mesh}.stl", "rj": json.dumps(result),
            },
        )
        return u

    async def _mk_cost(s, org_id, uid, mesh, result) -> str:
        u = str(ULID())
        await s.execute(
            text(
                "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, "
                "params_hash, engine_version, filename, file_type, result_json, "
                "make_now_process, crossover_qty) VALUES (:ul, :u, :o, :mh, :ph, "
                "'0.3.0', :fn, 'stl', CAST(:rj AS jsonb), :mnp, 500.0)"
            ),
            {
                "ul": u, "u": uid, "o": org_id, "mh": mesh,
                "ph": f"params-{u}", "fn": f"{mesh}.stl",
                "rj": json.dumps(result),
                "mnp": (result.get("decision") or {}).get("make_now_process"),
            },
        )
        return u

    # ---- seed ---------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        for oid, name in (
            (org_a, f"Org A {tag}"),
            (org_b, f"Org B {tag}"),
            (org_empty, f"Org Empty {tag}"),
        ):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": name, "sl": name.lower().replace(" ", "-")},
            )
        a1 = await _mk_user(s, "a1")
        a2 = await _mk_user(s, "a2")
        b1 = await _mk_user(s, "b1")
        e1 = await _mk_user(s, "e1")
        await _mk_membership(s, org_a, a1, "admin")
        await _mk_membership(s, org_a, a2, "member")
        await _mk_membership(s, org_b, b1, "admin")
        await _mk_membership(s, org_empty, e1, "admin")

        # Org A parts (mesh keys unique per part):
        #  P1 (a1): costed + analyzed, DFM-clean route → Costed, findings 0
        #  P2 (a1): costed + analyzed, has findings     → Costed, findings >0
        #  P3 (a2): analyzed only                       → Drafted, findings >0 (org-mate!)
        #  P4 (a1): costed only, blocked route          → Costed, price withheld, findings null
        mP1 = f"meshA-P1-{tag}"
        mP2 = f"meshA-P2-{tag}"
        mP3 = f"meshA-P3-{tag}"
        mP4 = f"meshA-P4-{tag}"
        await _mk_analysis(s, org_a, a1, mP1, _analysis_result(clean=True))
        await _mk_cost(s, org_a, a1, mP1, _cost_result())
        await _mk_analysis(s, org_a, a1, mP2, _analysis_result())
        await _mk_cost(s, org_a, a1, mP2, _cost_result())
        await _mk_analysis(s, org_a, a2, mP3, _analysis_result())  # org-mate, drafted
        await _mk_cost(
            s, org_a, a1, mP4,
            _cost_result(dfm_ready=False, blockers=["Wall too thin for CNC."]),
        )

        # Org B: one part, distinct mesh.
        mB1 = f"meshB-1-{tag}"
        await _mk_cost(s, org_b, b1, mB1, _cost_result())

        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # ============ ACT AS a1 (org A) ============
            _act_as(app, a1)
            r = await ac.get("/api/v1/catalog?page_size=100")
            assert r.status_code == 200, r.text
            body = r.json()
            parts = {row["part_key"] for row in body["rows"]}
            # org-mate a2's Drafted part IS visible (tenant boundary = ORG)
            assert {mP1, mP2, mP3, mP4} <= parts
            # org B never leaks
            assert mB1 not in parts
            assert body["pagination"]["total"] == 4

            by_key = {row["part_key"]: row for row in body["rows"]}

            # P1: costed + clean analysis → Costed, findings total 0, price present
            assert by_key[mP1]["lifecycle_state"] == "Costed"
            assert by_key[mP1]["findings"]["total"] == 0
            assert by_key[mP1]["unit_cost"]["usd"] == 12.5
            assert by_key[mP1]["unit_cost"]["withheld"] is False
            assert by_key[mP1]["unit_cost"]["validated"] is False

            # P2: findings route-scoped (universal error + cnc advisory = 2; the
            # off-route die_casting error is excluded)
            assert by_key[mP2]["findings"]["total"] == 2
            assert by_key[mP2]["findings"]["critical"] == 1
            assert by_key[mP2]["findings"]["advisory"] == 1

            # P3: org-mate, Drafted (analysis only) — no price, route from DFM
            assert by_key[mP3]["lifecycle_state"] == "Drafted"
            assert by_key[mP3]["unit_cost"] is None
            assert by_key[mP3]["recommended_route"]["source"] == "dfm"

            # P4: blocked route → price WITHHELD; no analysis → findings null
            assert by_key[mP4]["unit_cost"]["usd"] is None
            assert by_key[mP4]["unit_cost"]["withheld"] is True
            assert by_key[mP4]["unit_cost"]["withheld_reason"] == "Wall too thin for CNC."
            assert by_key[mP4]["findings"] is None

            # ---- facets summary (over the full org catalog) ----
            facets = body["facets"]
            assert facets["state"] == {"Costed": 3, "Drafted": 1}
            assert facets["route"]["cnc_3axis"] == 4
            assert facets["findings"]["with_findings"] == 2   # P2, P3
            assert facets["findings"]["without_findings"] == 1  # P1
            assert facets["findings"]["unknown"] == 1           # P4

            # ---- facet filters (real query params) ----
            r = await ac.get("/api/v1/catalog?state=Drafted&page_size=100")
            assert {row["part_key"] for row in r.json()["rows"]} == {mP3}

            r = await ac.get("/api/v1/catalog?has_findings=true&page_size=100")
            assert {row["part_key"] for row in r.json()["rows"]} == {mP2, mP3}

            r = await ac.get("/api/v1/catalog?has_findings=false&page_size=100")
            assert {row["part_key"] for row in r.json()["rows"]} == {mP1}

            r = await ac.get("/api/v1/catalog?route=cnc_3axis&page_size=100")
            assert r.json()["pagination"]["total"] == 4
            r = await ac.get("/api/v1/catalog?route=sheet_metal&page_size=100")
            assert r.json()["pagination"]["total"] == 0

            # invalid state → 400
            assert (await ac.get("/api/v1/catalog?state=bogus")).status_code == 400

            # ---- pagination (real total, consistent has_more) ----
            r1 = await ac.get("/api/v1/catalog?page=1&page_size=2")
            b1p = r1.json()
            assert len(b1p["rows"]) == 2
            assert b1p["pagination"]["total"] == 4
            assert b1p["pagination"]["total_pages"] == 2
            assert b1p["pagination"]["has_more"] is True
            r2 = await ac.get("/api/v1/catalog?page=2&page_size=2")
            b2p = r2.json()
            assert len(b2p["rows"]) == 2
            assert b2p["pagination"]["has_more"] is False
            # no row appears on both pages (offset slice is disjoint + total)
            assert not (
                {r["part_key"] for r in b1p["rows"]}
                & {r["part_key"] for r in b2p["rows"]}
            )
            # a page past the end is an empty grid, not an error
            r3 = await ac.get("/api/v1/catalog?page=99&page_size=2")
            assert r3.status_code == 200 and r3.json()["rows"] == []

            # ============ ACT AS b1 (org B) — symmetric isolation ============
            _act_as(app, b1)
            r = await ac.get("/api/v1/catalog?page_size=100")
            parts_b = {row["part_key"] for row in r.json()["rows"]}
            assert mB1 in parts_b
            assert not ({mP1, mP2, mP3, mP4} & parts_b)
            assert r.json()["pagination"]["total"] == 1

            # ============ ACT AS e1 (empty org) — empty state ============
            _act_as(app, e1)
            r = await ac.get("/api/v1/catalog")
            assert r.status_code == 200
            eb = r.json()
            assert eb["rows"] == []
            assert eb["pagination"]["total"] == 0
            assert eb["pagination"]["total_pages"] == 0
            assert eb["pagination"]["has_more"] is False
            assert eb["facets"]["state"] == {}
            assert eb["truncated"] is False
    finally:
        # ---- teardown (FK-safe) ----------------------------------
        async with eng.get_session_factory()() as s:
            if created_users:
                ids = created_users
                await s.execute(
                    text("DELETE FROM analyses WHERE user_id = ANY(:i)"), {"i": ids}
                )
                await s.execute(
                    text("DELETE FROM cost_decisions WHERE user_id = ANY(:i)"),
                    {"i": ids},
                )
                await s.execute(
                    text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": ids}
                )
                await s.execute(
                    text("DELETE FROM users WHERE id = ANY(:i)"), {"i": ids}
                )
            await s.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b, :c)"),
                {"a": org_a, "b": org_b, "c": org_empty},
            )
            await s.commit()
        await eng.dispose_engine()
