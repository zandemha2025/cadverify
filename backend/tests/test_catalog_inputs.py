"""The catalog folds read slim, cached record inputs (capacity report C6).

* Pure: every figure the parts pages derive is identical on a full record and
  on its slim inputs, across the record shapes the engine writes and the odd
  ones (missing keys, nulls, non-dict entries fail the same way).
* Cache: bounded by size; the oldest records leave first.
* Postgres: the fold equals the old full-record fold (newest current price per
  part, what-ifs never the price), reads each record's ``result_json`` once,
  then answers from memory, and an exact part pages past newer what-ifs.
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import datetime, timezone

import pytest

from src.services import catalog_inputs as ci
from src.services import catalog_service as cs
from src.services.cost_decision_service import is_current_price, what_if_of
from src.services.rate_card_basis import priced_version

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)")

WHEN = datetime(2026, 10, 1, tzinfo=timezone.utc)
HEAVY = {"gate": "wall", "detail": "x" * 4000, "evidence": [{"face": i, "mm": 0.4} for i in range(50)]}


def _estimate(process, material, qty, unit, *, ready=True, conf=None, drivers=None, **extra):
    e = {
        "process": process, "material": material, "quantity": qty, "unit_cost_usd": unit,
        "fixed_cost_usd": 100.0, "variable_cost_usd": unit - 1, "dfm_ready": ready,
        "dfm_blockers": [] if ready else ["Wall too thin for this process."],
        "dfm_blocker_details": [HEAVY, HEAVY], "lead_time": {"days": 12, "basis": "typical"},
        "line_items": [{"name": "machine", "usd": unit / 2}], "qty_model": {"kind": "learning"},
        "material_mass": {"kg": 0.2}, "est_error_band_pct": 25, "dfm_score": 0.8, "dfm_verdict": "pass",
        "confidence": conf if conf is not None else {"validated": False, "label": "assumption band", "low": 1, "high": 2},
        "drivers": drivers if drivers is not None else [
            {"name": "machine_rate", "provenance": "DEFAULT", "source": "typical", "value": 85.0},
            {"name": "labor_rate", "provenance": "SHOP", "source": "your shop", "value": 40.0},
            {"name": "stock", "provenance": "MEASURED", "source": "mesh", "value": 3.1},
            {"name": "setup", "source": "no provenance"},
            {"name": "override", "provenance": "USER", "value": 1},
        ],
    }
    e.update(extra)
    return e


def _cost(**over):
    rec = {
        "decision": {
            "make_now_process": "cnc_3axis", "make_now_material": "aluminum_6061", "crossover_qty": 1200.0,
            "recommendation": {
                "1": {"process": "cnc_3axis", "material": "aluminum_6061", "unit_cost_usd": 48.0},
                "10": {"process": "cnc_3axis", "material": "steel_1018", "unit_cost_usd": 30.0},
                "500": {"process": "die_casting", "material": "zamak", "unit_cost_usd": 9.0, "dfm_ready": True},
                "5000": {"process": "die_casting", "material": "zamak", "unit_cost_usd": 4.0, "environment_excluded": False},
            },
            "if_redesigned": {
                "10": {"process": "sheet_metal", "unit_cost_usd": 20.0, "caveat": "fold the flange"},
                "5000": {"process": "injection_molding", "unit_cost_usd": 2.5, "caveat": "add draft"},
            },
        },
        "quantities": [1, 10, 500, 5000],
        "estimates": [
            _estimate(p, m, q, u, ready=(p != "die_casting" or q >= 500),
                      conf={"validated": q == 10, "label": "band"} if p == "cnc_3axis" else None)
            for p, m in (("cnc_3axis", "aluminum_6061"), ("cnc_3axis", "steel_1018"), ("die_casting", "zamak"))
            for q, u in ((1, 48.0), (10, 30.0), (500, 9.0), (5000, 4.0))
        ],
        "rate_card": {"version": 3, "changed": {"machine_rate": [85, 90]}, "source": "your published rate card v3"},
        "engine_feasibility": {"big": ["x" * 500] * 20},
        "assumptions": [{"name": "region", "value": "US"}] * 30,
        "notes": ["n"] * 10, "geometry": {"volume_cm3": 12.0}, "material_class": "metal",
    }
    rec.update(over)
    return rec


def _analysis(**over):
    rec = {
        "best_process": "cnc_3axis",
        "universal_issues": [
            {"code": "NON_WATERTIGHT", "severity": "error", "message": "not watertight", "fix_suggestion": "heal", "scope": "part"},
            {"code": "THIN", "message": "no severity given"},
        ],
        "process_scores": [
            {"process": "cnc_3axis", "recommended_material": "aluminum_6061", "score": 80, "standards": ["x"],
             "issues": [{"code": "DEEP_POCKET", "severity": "warning", "message": "deep pocket", "fix_suggestion": "f" * 300},
                        {"code": "NON_WATERTIGHT", "severity": "warning", "message": "not watertight"}]},
            {"process": "die_casting", "recommended_material": "zamak",
             "issues": [{"code": "NO_DRAFT", "severity": "error", "message": "no draft"}]},
        ],
        "features": [{"kind": "hole", "d": 3}] * 100, "priority_fixes": ["p"] * 40, "geometry": {"faces": 1200},
    }
    rec.update(over)
    return rec


def _ref(rj):
    return cs.SourceRef(id="01REC", filename="part.step", file_type="step", created_at=WHEN, result_json=rj)


def _figures(cost_rj, an_rj, declared):
    out = {}
    for label, fn in [
        ("row", lambda: cs.derive_row(part_key="m", analysis=_ref(an_rj) if an_rj is not None else None,
                                      cost=_ref(cost_rj) if cost_rj is not None else None, declared_qty=declared)),
        ("savings", lambda: cs.derive_savings(cost_rj) if cost_rj is not None else None),
        ("annual", lambda: cs.annualization_at_quantity(cost_rj, declared) if cost_rj is not None else None),
        ("what_if", lambda: (what_if_of(cost_rj), is_current_price(cost_rj))),
        ("priced", lambda: priced_version(cost_rj, WHEN, [])),
    ]:
        try:
            out[label] = fn()
        except Exception as exc:  # a malformed record must fail the same way
            out[label] = ("raised", type(exc).__name__)
    return out


COST_SHAPES = {
    "typical": _cost(),
    "no_quantities": _cost(quantities=None),
    "empty_quantities": _cost(quantities=[]),
    "dfm_ready_null": _cost(estimates=[_estimate("cnc_3axis", "aluminum_6061", 10, 30.0, dfm_ready=None)]),
    "dfm_ready_missing": _cost(estimates=[{k: v for k, v in _estimate("cnc_3axis", "aluminum_6061", 10, 30.0).items() if k != "dfm_ready"}]),
    "confidence_not_dict": _cost(estimates=[_estimate("cnc_3axis", "aluminum_6061", 10, 30.0, conf="banded")]),
    "confidence_empty": _cost(estimates=[_estimate("cnc_3axis", "aluminum_6061", 10, 30.0, conf={})]),
    "drivers_not_list": _cost(estimates=[_estimate("cnc_3axis", "aluminum_6061", 10, 30.0, drivers={"a": 1})]),
    "driver_not_dict": _cost(estimates=[_estimate("cnc_3axis", "aluminum_6061", 10, 30.0, drivers=["DEFAULT", None])]),
    "driver_provenance_null": _cost(estimates=[_estimate("cnc_3axis", "aluminum_6061", 10, 30.0, drivers=[{"provenance": None}])]),
    "estimate_not_dict": _cost(estimates=[None, _estimate("cnc_3axis", "aluminum_6061", 10, 30.0)]),
    "estimates_not_list": _cost(estimates={"cnc": 1}),
    "env_excluded": _cost(estimates=[_estimate("die_casting", "zamak", 500, 9.0, environment_excluded=True)]),
    "no_decision": _cost(decision=None),
    "what_if": _cost(what_if={"label": "What if: overhead 15%", "overrides": {"overhead_pct": 15}, "shop": None}),
    "what_if_null": _cost(what_if=None),
    "rate_card_no_version": _cost(rate_card={"source": "x"}),
    "rate_card_not_dict": _cost(rate_card=2),
    "adopted_priced_at": _cost(rate_card=None, priced_at="2026-09-01T00:00:00+00:00"),
    "empty": {},
}
ANALYSIS_SHAPES = {
    "typical": _analysis(),
    "no_issues": _analysis(universal_issues=None, process_scores=None),
    "score_not_dict": _analysis(process_scores=["cnc_3axis"]),
    "issue_not_dict": _analysis(universal_issues=["oops"]),
    "best_unknown": _analysis(best_process="laser_cutting"),
    "empty": {},
}


@pytest.mark.parametrize("cost_name", sorted(COST_SHAPES))
@pytest.mark.parametrize("an_name", [None, *sorted(ANALYSIS_SHAPES)])
def test_every_derived_figure_is_identical_on_slim_inputs(cost_name, an_name):
    full_cost = COST_SHAPES[cost_name]
    full_an = ANALYSIS_SHAPES[an_name] if an_name else None
    before = copy.deepcopy((full_cost, full_an))
    slim_cost = ci.slim_cost(full_cost)
    slim_an = ci.slim_analysis(full_an) if full_an is not None else None
    assert (full_cost, full_an) == before  # slimming never edits the record
    for declared in (None, 1, 7, 10, 500, 5000, True, 0):
        assert _figures(full_cost, full_an, declared) == _figures(slim_cost, slim_an, declared), (cost_name, an_name, declared)
    # The derivation leaves the shared slim inputs as they were.
    assert slim_cost == ci.slim_cost(full_cost)


def test_analysis_only_rows_are_identical():
    for name, rec in ANALYSIS_SHAPES.items():
        assert _figures(None, rec, None)["row"] == _figures(None, ci.slim_analysis(rec), None)["row"], name


def test_not_a_dict_passes_through():
    for odd in (None, [1, 2], "x", 3):
        assert ci.slim_cost(odd) == odd
        assert ci.slim_analysis(odd) == odd


def test_slim_inputs_drop_the_heavy_parts():
    full, slim = _cost(), ci.slim_cost(_cost())
    assert set(slim) == {"decision", "quantities", "rate_card", "estimates"}
    assert set(slim["estimates"][0]) == set(ci._ESTIMATE_KEYS) - {"environment_excluded"}
    assert slim["rate_card"] == {"version": 3}
    assert len(json.dumps(slim)) < len(json.dumps(full)) / 10
    an = ci.slim_analysis(_analysis())
    assert set(an) == {"best_process", "universal_issues", "process_scores"}
    assert an["universal_issues"][0] == {"code": "NON_WATERTIGHT", "severity": "error", "message": "not watertight"}


def test_cache_is_bounded_and_oldest_leave_first(monkeypatch):
    cache = ci._Cache()
    for i in range(10):
        cache.put((i, f"u{i}"), {"i": i}, 100, 350)
    assert len(cache) == 3 and cache.bytes <= 350
    assert cache.get((9, "u9")) == (True, {"i": 9})
    assert cache.get((0, "u0")) == (False, None)
    cache.put((99, "big"), {}, 351, 350)  # larger than the whole budget: not kept
    assert cache.get((99, "big")) == (False, None)
    counted = ci._Cache(max_entries=2)
    for i in range(5):
        counted.put((i, "u"), True, 1, 1 << 62)
    assert len(counted) == 2
    monkeypatch.setenv("CATALOG_INPUT_CACHE_MB", "0")
    assert ci._budget_bytes() == 0


# ---------------------------------------------------------------------------
# Postgres: the folds over real rows
# ---------------------------------------------------------------------------


async def _seed(s, tag):
    from sqlalchemy import text
    from ulid import ULID

    org = str(ULID())
    await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:i, :n, :s, now())"),
                    {"i": org, "n": f"Inputs {tag}", "s": f"inputs-{tag}"})
    email = f"inputs-{tag}@example.com"
    uid = int((await s.execute(text(
        "INSERT INTO users (email, email_lower, role, auth_provider) VALUES (:e, :e, 'analyst', 'password') RETURNING id"
    ), {"e": email})).first()[0])
    await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:i, :o, :u, 'admin', now())"),
                    {"i": str(ULID()), "o": org, "u": uid})
    return org, uid


async def _add(s, table, org, uid, mesh, rj):
    from sqlalchemy import text
    from ulid import ULID

    u = str(ULID())
    if table == "analyses":
        await s.execute(text(
            "INSERT INTO analyses (ulid, user_id, org_id, mesh_hash, process_set_hash, analysis_version, filename, "
            "file_type, file_size_bytes, result_json, verdict, face_count, duration_ms) VALUES (:u, :uid, :o, :m, :ph, "
            "'0.3.0', :fn, 'step', 1024, CAST(:rj AS jsonb), 'issues', 12, 50.0)"
        ), {"u": u, "uid": uid, "o": org, "m": mesh, "ph": f"ps-{u}", "fn": f"{mesh}.step", "rj": json.dumps(rj)})
    else:
        await s.execute(text(
            "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, params_hash, engine_version, filename, "
            "file_type, result_json, make_now_process) VALUES (:u, :uid, :o, :m, :ph, '0.3.0', :fn, 'step', "
            "CAST(:rj AS jsonb), 'cnc_3axis')"
        ), {"u": u, "uid": uid, "o": org, "m": mesh, "ph": f"pp-{u}", "fn": f"{mesh}.step", "rj": json.dumps(rj)})
    return u


async def _full_record_fold(s, org):
    """The fold as it read before: whole rows, newest current price per part."""
    from sqlalchemy import select

    from src.db.models import Analysis, CostDecision
    from src.services.cost_decision_service import current_price_clause

    ans = (await s.execute(select(Analysis).where(Analysis.org_id == org).order_by(Analysis.ulid.desc()))).scalars().all()
    costs = (await s.execute(select(CostDecision).where(CostDecision.org_id == org, current_price_clause())
                             .order_by(CostDecision.ulid.desc()))).scalars().all()
    an_by, cost_by = cs._fold_latest_by_mesh(ans), cs._fold_latest_by_mesh(costs)
    rows = []
    for mesh in sorted(set(an_by) | set(cost_by)):
        a, c = an_by.get(mesh), cost_by.get(mesh)
        mk = lambda r: cs.SourceRef(id=r.ulid, filename=r.filename, file_type=r.file_type,  # noqa: E731
                                    created_at=r.created_at, result_json=r.result_json or {})
        rows.append(cs.derive_row(part_key=mesh, analysis=mk(a) if a else None, cost=mk(c) if c else None))
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows


@_requires_pg
@pytest.mark.asyncio
async def test_fold_matches_full_records_and_reads_each_record_once():
    from sqlalchemy import event, text

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    async with eng.get_session_factory()() as s:
        org, uid = await _seed(s, tag)
        for i in range(4):
            mesh = f"m{i}-{tag}"
            await _add(s, "analyses", org, uid, mesh, _analysis(best_process=("cnc_3axis", "die_casting")[i % 2]))
            await _add(s, "analyses", org, uid, mesh, _analysis())  # a re-check: the newer one is the part's
            if i != 3:
                await _add(s, "cost_decisions", org, uid, mesh, _cost())
        # Part 0's newest record is a what-if: never its price on the parts list.
        await _add(s, "cost_decisions", org, uid, f"m0-{tag}", _cost(
            what_if={"label": "What if: overhead 15%", "overrides": {"overhead_pct": 15}},
            decision={**_cost()["decision"], "make_now_process": "die_casting"}))
        await _add(s, "cost_decisions", org, uid, f"m4-{tag}", _cost(what_if={"label": "only a what-if"}))
        await s.commit()

    reads: list[str] = []

    def _count(conn, cursor, statement, params, context, executemany):
        if "result_json" in statement:
            reads.append(statement)

    engine = eng.get_engine()
    event.listen(engine.sync_engine, "before_cursor_execute", _count)
    try:
        async with eng.get_session_factory()() as s:
            expected = await _full_record_fold(s, org)
            reads.clear()
            first = await cs.build_catalog(s, org)
            first_reads = len(reads)
            reads.clear()
            again = await cs.build_catalog(s, org)
            portfolio = await cs.build_portfolio(s, org)
            assert reads == []  # every record answered from memory
        assert first["rows"] == expected == again["rows"]
        assert first_reads == 3  # what-if test, analysis inputs, cost inputs
        assert {r["part_key"] for r in first["rows"]} == {f"m{i}-{tag}" for i in range(4)}  # m4: only a what-if
        m0 = next(r for r in first["rows"] if r["part_key"] == f"m0-{tag}")
        assert m0["recommended_route"]["process"] == "cnc_3axis"  # the what-if's die casting never shows
        assert portfolio["summary"]["costed"] == 3 and portfolio["summary"]["drafted"] == 1
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _count)
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
            await s.commit()


@_requires_pg
@pytest.mark.asyncio
async def test_exact_part_pages_past_newer_what_ifs_and_deleted_records_are_gone():
    from sqlalchemy import text

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    mesh = f"wi-{tag}"
    async with eng.get_session_factory()() as s:
        org, uid = await _seed(s, tag)
        price = await _add(s, "cost_decisions", org, uid, mesh, _cost())
        for i in range(60):  # more what-ifs than one page of the listing
            await _add(s, "cost_decisions", org, uid, mesh, _cost(what_if={"label": f"What if {i}"}))
        await s.commit()
    try:
        async with eng.get_session_factory()() as s:
            built = await cs.build_catalog(s, org, part_key=mesh)
            assert [r["cost_decision"]["id"] for r in built["rows"]] == [price]
            await s.execute(text("DELETE FROM cost_decisions WHERE ulid = :u"), {"u": price})
            await s.commit()
            assert (await cs.build_catalog(s, org, part_key=mesh))["rows"] == []
            assert (await cs.build_catalog(s, org))["rows"] == []
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
            await s.commit()
