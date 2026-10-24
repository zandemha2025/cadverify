"""Pure + mock-session tests for the makeability triage roll-up (W1 VP1).

Two layers, mirroring test_catalog_service / test_portfolio_service:

  * ``triage_rollup`` is exercised directly over synthetic derived catalog rows
    (built through the real ``derive_row``, the same shape ``build_catalog``
    emits) — it pins the honesty contract: per-process counts are correct; the
    three postures (makeable / needs_review / unknown) are mutually exclusive and
    sum to ``total``; a blocking DFM error lands in needs_review; a part with no
    analysis lands in unknown (never makeable); ``truncated`` passes through.
  * ``build_triage`` runs over a mocked session (no Postgres) so the roll-up over
    the real fold + derivation, the truncated propagation, and the empty-org
    contract are all asserted end-to-end without a DB.

An optional DATABASE_URL-guarded API test drives ``GET /api/v1/catalog/triage``
against live Postgres and asserts cross-tenant isolation.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import pytest

from src.services import catalog_service as svc
from src.services.catalog_service import SourceRef


# ---------------------------------------------------------------------------
# result_json builders (real report_to_dict / analysis shapes)
# ---------------------------------------------------------------------------


def _analysis_json(best="cnc_3axis", *, clean=False):
    """An analysis result_json. ``clean`` → no issues at all (a DFM-clean route);
    otherwise a universal error (critical) + on-route advisory + off-route error
    (which must NOT count toward the on-route headline)."""
    if clean:
        return {"best_process": best, "universal_issues": [], "process_scores": []}
    return {
        "best_process": best,
        "universal_issues": [
            {"code": "NON_WATERTIGHT", "severity": "error", "message": "not watertight"},
        ],
        "process_scores": [
            {
                "process": best,
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


def _cost_json(*, process="cnc_3axis", dfm_ready=True, blockers=None):
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
                "drivers": [],
            }
        ],
    }


def _ref(result_json, *, id="01ABC", fn="part.stl", ts=None):
    return SourceRef(
        id=id,
        filename=fn,
        file_type="stl",
        created_at=ts or datetime(2026, 6, 1, tzinfo=timezone.utc),
        result_json=result_json,
    )


def _row(part_key, *, analysis=None, cost=None):
    return svc.derive_row(part_key=part_key, analysis=analysis, cost=cost)


# ---------------------------------------------------------------------------
# process_label
# ---------------------------------------------------------------------------


def test_process_label_known_and_fallback():
    assert svc.process_label("cnc_3axis") == "CNC Milling (3-axis)"
    assert svc.process_label("injection_molding") == "Injection Molding"
    # unknown id → titleized fallback, never dropped
    assert svc.process_label("some_new_proc") == "Some New Proc"
    assert svc.process_label(None) == "Unrouted"


# ---------------------------------------------------------------------------
# triage_bucket — the per-row classifier (mutually exclusive branches)
# ---------------------------------------------------------------------------


def test_bucket_makeable_requires_analysis_confirming_clean_route():
    # costed + a DFM-clean analysis on the route → makeable
    row = _row("m", analysis=_ref(_analysis_json(clean=True)), cost=_ref(_cost_json()))
    assert svc.triage_bucket(row) == "makeable"


def test_bucket_needs_review_on_critical_finding():
    # analysis carries a universal error (critical) on the route → needs_review
    row = _row("m", analysis=_ref(_analysis_json()), cost=_ref(_cost_json()))
    assert row["findings"]["critical"] == 1
    assert svc.triage_bucket(row) == "needs_review"


def test_bucket_needs_review_on_blocking_dfm_error():
    # a cost-side DFM blocker (price withheld) → needs_review, even with no analysis
    row = _row(
        "m",
        analysis=None,
        cost=_ref(_cost_json(dfm_ready=False, blockers=["Wall too thin for CNC."])),
    )
    assert row["route_blocker_count"] == 1
    assert svc.triage_bucket(row) == "needs_review"


def test_bucket_unknown_when_costed_but_never_analyzed():
    # routed by a cost decision, but no DFM analysis ran → unknown, NEVER makeable
    row = _row("m", analysis=None, cost=_ref(_cost_json()))
    assert row["findings"] is None
    assert svc.triage_bucket(row) == "unknown"


def test_bucket_unknown_when_no_route():
    # analysis with no best_process and no cost → no route → unknown
    row = _row(
        "m",
        analysis=_ref({"best_process": "", "universal_issues": [], "process_scores": []}),
        cost=None,
    )
    assert row["recommended_route"] is None
    assert svc.triage_bucket(row) == "unknown"


# ---------------------------------------------------------------------------
# triage_rollup — the pure aggregation over derived rows
# ---------------------------------------------------------------------------


def _mixed_rows():
    """A synthetic org catalog spanning all buckets + two routed processes."""
    return [
        # makeable, cnc_3axis (costed + clean analysis)
        _row("m-mk-cnc", analysis=_ref(_analysis_json(clean=True)), cost=_ref(_cost_json())),
        # needs_review, cnc_3axis (critical finding on route)
        _row("m-nr-cnc", analysis=_ref(_analysis_json()), cost=_ref(_cost_json())),
        # makeable, injection_molding (drafted-only, clean DFM route)
        _row(
            "m-mk-im",
            analysis=_ref(_analysis_json(best="injection_molding", clean=True)),
            cost=None,
        ),
        # unknown (costed, never analyzed) — still ROUTED to cnc_3axis
        _row("m-unk-costed", analysis=None, cost=_ref(_cost_json())),
        # unknown (no route at all)
        _row(
            "m-unk-noroute",
            analysis=_ref({"best_process": "", "universal_issues": [], "process_scores": []}),
            cost=None,
        ),
    ]


def test_rollup_counts_per_process_are_correct():
    out = svc.triage_rollup(_mixed_rows())
    by = {p["process"]: p for p in out["by_process"]}
    # cnc_3axis: m-mk-cnc + m-nr-cnc + m-unk-costed = 3 routed
    assert by["cnc_3axis"]["count"] == 3
    assert by["cnc_3axis"]["label"] == "CNC Milling (3-axis)"
    # injection_molding: m-mk-im = 1 routed
    assert by["injection_molding"]["count"] == 1
    assert by["injection_molding"]["label"] == "Injection Molding"
    # the no-route unknown contributes to no process
    assert set(by) == {"cnc_3axis", "injection_molding"}
    # sorted by count desc then id
    assert [p["process"] for p in out["by_process"]] == ["cnc_3axis", "injection_molding"]


def test_rollup_buckets_mutually_exclusive_and_sum_to_total():
    out = svc.triage_rollup(_mixed_rows())
    s = out["summary"]
    assert s["total"] == 5
    assert s["makeable"] == 2       # m-mk-cnc, m-mk-im
    assert s["needs_review"] == 1   # m-nr-cnc
    assert s["unknown"] == 2        # m-unk-costed, m-unk-noroute
    # mutually exclusive + exhaustive
    assert s["makeable"] + s["needs_review"] + s["unknown"] == s["total"]
    # analyzed = the parts with a real DFM makeability signal
    assert s["analyzed"] == s["makeable"] + s["needs_review"] == 3


def test_rollup_no_analysis_never_counted_makeable():
    # An org of ONLY costed-but-unanalyzed parts → all unknown, zero makeable.
    rows = [_row(f"m{i}", analysis=None, cost=_ref(_cost_json())) for i in range(4)]
    out = svc.triage_rollup(rows)
    assert out["summary"]["makeable"] == 0
    assert out["summary"]["unknown"] == 4
    assert out["summary"]["needs_review"] == 0


def test_rollup_truncated_flag_passes_through_honestly():
    assert svc.triage_rollup([], truncated=True)["summary"]["truncated"] is True
    assert svc.triage_rollup([], truncated=False)["summary"]["truncated"] is False


def test_rollup_empty_is_zeroed_not_error():
    out = svc.triage_rollup([])
    s = out["summary"]
    assert s == {
        "total": 0, "analyzed": 0, "makeable": 0,
        "needs_review": 0, "unknown": 0, "truncated": False,
    }
    assert out["by_process"] == []
    assert "programs" not in out


def test_rollup_program_grouping_is_additive_and_honest():
    rows = _mixed_rows()
    # declare programs for two parts only
    programs = {"m-mk-cnc": "Alpha", "m-nr-cnc": "Alpha", "m-mk-im": "Beta"}
    out = svc.triage_rollup(rows, programs=programs)
    groups = {g["program"]: g for g in out["programs"]}
    assert groups["Alpha"]["total"] == 2
    assert groups["Alpha"]["makeable"] == 1
    assert groups["Alpha"]["needs_review"] == 1
    assert groups["Beta"]["total"] == 1
    assert groups["Beta"]["makeable"] == 1
    # sorted by program name
    assert [g["program"] for g in out["programs"]] == ["Alpha", "Beta"]
    # no programs declared → key absent entirely (byte-identical to before)
    assert "programs" not in svc.triage_rollup(rows)


# ---------------------------------------------------------------------------
# Mock-session build_triage — real fold + derivation, no Postgres
# ---------------------------------------------------------------------------


class _Row:
    def __init__(self, mesh, result_json, *, ulid=None, ts=None):
        self.mesh_hash = mesh
        self.ulid = ulid or f"ul-{mesh}"
        self.filename = f"{mesh}.stl"
        self.file_type = "stl"
        self.created_at = ts or datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.result_json = result_json


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Dispatches the fold scans by table name in the SQL text. ``part_contexts``
    (the optional program join) returns [] — no declared contexts in these fakes."""

    def __init__(self, analyses, costs):
        self._an = analyses
        self._cost = costs

    async def execute(self, stmt):
        s = str(stmt).lower()
        if "part_contexts" in s:
            return _FakeResult([])
        if "cost_decisions" in s:
            return _FakeResult(self._cost)
        return _FakeResult(self._an)


@pytest.mark.asyncio
async def test_build_triage_over_mock_session():
    # makeable (costed + clean analysis), needs_review (critical finding),
    # unknown (costed, no analysis), plus a drafted-only makeable.
    mk = _Row("m-mk", _cost_json())
    mk_an = _Row("m-mk", _analysis_json(clean=True))
    nr = _Row("m-nr", _cost_json())
    nr_an = _Row("m-nr", _analysis_json())
    unk = _Row("m-unk", _cost_json())            # costed, no analysis → unknown
    drafted = _Row("m-drafted", _analysis_json(best="injection_molding", clean=True))

    session = _FakeSession(
        analyses=[mk_an, nr_an, drafted],
        costs=[mk, nr, unk],
    )
    out = await svc.build_triage(session, org_id="org-1")
    s = out["summary"]
    assert s["total"] == 4
    assert s["makeable"] == 2       # m-mk, m-drafted
    assert s["needs_review"] == 1   # m-nr
    assert s["unknown"] == 1        # m-unk
    assert s["makeable"] + s["needs_review"] + s["unknown"] == s["total"]
    by = {p["process"]: p["count"] for p in out["by_process"]}
    assert by["cnc_3axis"] == 3     # m-mk, m-nr, m-unk all route to cnc
    assert by["injection_molding"] == 1
    assert "programs" not in out


@pytest.mark.asyncio
async def test_build_triage_truncated_propagates(monkeypatch):
    monkeypatch.setattr(svc, "CATALOG_SCAN_CAP", 1)
    c1 = _Row("m1", _cost_json(), ulid="ul-b")
    c2 = _Row("m2", _cost_json(), ulid="ul-a")
    session = _FakeSession(analyses=[], costs=[c1, c2])
    out = await svc.build_triage(session, org_id="org-1")
    assert out["summary"]["truncated"] is True


@pytest.mark.asyncio
async def test_build_triage_empty_org_is_zeroed_not_error():
    out = await svc.build_triage(_FakeSession([], []), org_id=None)
    assert out["by_process"] == []
    assert out["summary"] == {
        "total": 0, "analyzed": 0, "makeable": 0,
        "needs_review": 0, "unknown": 0, "truncated": False,
    }


# ---------------------------------------------------------------------------
# DATABASE_URL-guarded API test — cross-tenant isolation of the rollup
# ---------------------------------------------------------------------------

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _build_app():
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


@_requires_pg
@pytest.mark.asyncio
async def test_triage_api_cross_tenant_isolation():
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
        email = f"triage-{tag}-{label}@example.com"
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

    async with eng.get_session_factory()() as s:
        for oid, name in (
            (org_a, f"TriOrg A {tag}"),
            (org_b, f"TriOrg B {tag}"),
            (org_empty, f"TriOrg Empty {tag}"),
        ):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": name, "sl": name.lower().replace(" ", "-")},
            )
        a1 = await _mk_user(s, "a1")
        b1 = await _mk_user(s, "b1")
        e1 = await _mk_user(s, "e1")
        await _mk_membership(s, org_a, a1, "admin")
        await _mk_membership(s, org_b, b1, "admin")
        await _mk_membership(s, org_empty, e1, "admin")

        # Org A: makeable (clean cnc) + needs_review (blocked cnc) + unknown (costed only)
        await _mk_analysis(s, org_a, a1, f"a-mk-{tag}", _analysis_json(clean=True))
        await _mk_cost(s, org_a, a1, f"a-mk-{tag}", _cost_json())
        await _mk_cost(
            s, org_a, a1, f"a-nr-{tag}",
            _cost_json(dfm_ready=False, blockers=["Wall too thin for CNC."]),
        )
        await _mk_cost(s, org_a, a1, f"a-unk-{tag}", _cost_json())

        # Org B: two makeable die_casting parts — must NEVER count for org A.
        await _mk_analysis(s, org_b, b1, f"b-1-{tag}", _analysis_json(best="die_casting", clean=True))
        await _mk_cost(s, org_b, b1, f"b-1-{tag}", _cost_json(process="die_casting"))
        await _mk_analysis(s, org_b, b1, f"b-2-{tag}", _analysis_json(best="die_casting", clean=True))
        await _mk_cost(s, org_b, b1, f"b-2-{tag}", _cost_json(process="die_casting"))

        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # ---- org A ----
            _act_as(app, a1)
            r = await ac.get("/api/v1/catalog/triage")
            assert r.status_code == 200, r.text
            a = r.json()
            assert a["summary"]["total"] == 3
            assert a["summary"]["makeable"] == 1
            assert a["summary"]["needs_review"] == 1
            assert a["summary"]["unknown"] == 1
            procs_a = {p["process"] for p in a["by_process"]}
            assert procs_a == {"cnc_3axis"}          # org B's die_casting never leaks
            assert a["summary"]["truncated"] is False

            # ---- org B — symmetric isolation ----
            _act_as(app, b1)
            b = (await ac.get("/api/v1/catalog/triage")).json()
            assert b["summary"]["total"] == 2
            assert b["summary"]["makeable"] == 2
            procs_b = {p["process"] for p in b["by_process"]}
            assert procs_b == {"die_casting"}        # org A's cnc never leaks

            # ---- empty org — zeroed, not an error ----
            _act_as(app, e1)
            e = await ac.get("/api/v1/catalog/triage")
            assert e.status_code == 200
            eb = e.json()
            assert eb["summary"]["total"] == 0
            assert eb["summary"]["makeable"] == 0
            assert eb["by_process"] == []
            assert eb["summary"]["truncated"] is False
    finally:
        async with eng.get_session_factory()() as s:
            if created_users:
                ids = created_users
                await s.execute(text("DELETE FROM analyses WHERE user_id = ANY(:i)"), {"i": ids})
                await s.execute(text("DELETE FROM cost_decisions WHERE user_id = ANY(:i)"), {"i": ids})
                await s.execute(text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": ids})
                await s.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": ids})
            await s.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b, :c)"),
                {"a": org_a, "b": org_b, "c": org_empty},
            )
            await s.commit()
        await eng.dispose_engine()
