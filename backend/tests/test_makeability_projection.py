"""Phase D — makeability projection + scaled rollup + capability-investment ranking.

Two layers (the repo's pure-vs-PG split):

  * PURE — ``derive_makeability_fields`` maps a cost decision's ``result_json`` (the
    Phase-C ``verification`` block) to the makeability columns for EVERY §0 verdict
    (incl. the negative/unknown/geometry-invalid first-class outcomes); the D4
    ``rank_acquisitions`` math over fixture gap data (ties, empty, spec aggregation);
    and STALENESS VISIBILITY (a stale group carries the flag + count, never hidden).
  * PG (DATABASE_URL-guarded) — migration 0023 in the chain; two-org isolation on
    the rollup / drill-down / ranking; and projection MAINTENANCE on a machine
    add/delete (the stale-mark) + a re-cost clearing it — all through the REAL
    persist funnels + the REAL machine-inventory router (the wired paths).

HONESTY under test: no fabricated verdict/count/dollar; a verdict computed against
inventory that has since changed is STALE + visible; GETs stay read-only; a
malformed keyset cursor is a typed 400, never a 500.
"""
from __future__ import annotations

import os
import uuid

import pytest

from src.services import catalog_service as svc
from src.services import part_summary_service as pss


# ═══════════════════════════════════════════════════════════════════════════
# result_json builders (real report_to_dict / verification shapes)
# ═══════════════════════════════════════════════════════════════════════════


def _verif(verdict, *, per_route=None, gap=None):
    """A minimal but faithful Phase-C verification block."""
    return {
        "verdict": verdict,
        "best_machine": None,
        "resource": None,
        "gap": gap or [],
        "env_exclusions": [],
        "per_route": per_route or {},
        "inventory_declared": True,
        "environment_declared": False,
        "provenance": "user",
        "note": "",
    }


def _cost_json(*, process="cnc_3axis", material="steel", status="OK",
               verdict=None, per_route=None, gap=None, dfm_ready=True):
    cj = {
        "status": status,
        "decision": {
            "make_now_process": process if status != "GEOMETRY_INVALID" else "",
            "make_now_material": material,
            "crossover_qty": 500.0,
        },
        "quantities": [10],
        "estimates": [
            {
                "process": process, "material": material, "quantity": 10,
                "unit_cost_usd": 12.5, "dfm_ready": dfm_ready, "dfm_blockers": [],
                "confidence": {"validated": False, "label": "assumption band"},
                "drivers": [{"provenance": "MEASURED"}, {"provenance": "DEFAULT"}],
            }
        ],
    }
    if status == "GEOMETRY_INVALID":
        cj["estimates"] = []
        cj["decision"] = {}
    if verdict is not None:
        cj["verification"] = _verif(verdict, per_route=per_route, gap=gap)
    return cj


def _fail(gate, need, have, *, axis=None):
    return {"gate": gate, "axis": axis or gate, "need": need, "have": have,
            "human": f"{gate} {need} > {have}"}


def _nowned(process, fails):
    """A per_route entry for a not-on-owned route with the given hard failures."""
    return {process: {"verdict": "makeable_not_on_owned", "machines_evaluated": 1,
                      "best_machine": "M", "failures": fails}}


def _outsource(*processes):
    return {p: {"verdict": "makeable_outsource_only", "machines_evaluated": 0,
                "best_machine": None, "failures": []} for p in processes}


# ═══════════════════════════════════════════════════════════════════════════
# PURE — bucket mapping from EVERY §0 verdict lattice value
# ═══════════════════════════════════════════════════════════════════════════

_ALL_VERDICTS = [
    ("makeable_in_house", "makeable_in_house", True),
    ("makeable_with_secondary_op", "makeable_in_house", True),
    ("makeable_not_on_owned", "needs_capability", False),
    ("makeable_outsource_only", "makeable_outside", False),
    ("environment_excluded", "not_makeable", False),
    ("not_makeable", "not_makeable", False),
    ("unknown", "unknown", None),
]


@pytest.mark.parametrize("verdict,bucket,in_house", _ALL_VERDICTS)
def test_bucket_and_in_house_for_every_verdict(verdict, bucket, in_house):
    assert svc.makeability_bucket(verdict) == bucket
    f = pss.derive_makeability_fields(_cost_json(verdict=verdict))
    assert f["makeability_verdict"] == verdict
    assert f["makeability_bucket"] == bucket
    assert f["in_house_makeable"] is in_house


def test_every_bucket_value_is_in_the_constant():
    # the mapping only ever emits one of the six declared buckets
    for verdict, bucket, _ in _ALL_VERDICTS:
        assert bucket in svc.MAKEABILITY_BUCKETS
    assert svc.makeability_bucket("makeable_in_house", "GEOMETRY_INVALID") \
        == "geometry_invalid"


def test_geometry_invalid_status_wins_and_is_not_in_house():
    f = pss.derive_makeability_fields(_cost_json(status="GEOMETRY_INVALID"))
    assert f["makeability_bucket"] == "geometry_invalid"
    assert f["in_house_makeable"] is False
    assert f["unlock_process"] is None  # no acquisition for invalid geometry
    # even if a stray verdict rode along, geometry-invalid still wins
    f2 = pss.derive_makeability_fields(
        _cost_json(status="GEOMETRY_INVALID", verdict="makeable_in_house"))
    assert f2["makeability_bucket"] == "geometry_invalid"
    assert f2["in_house_makeable"] is False


def test_no_cost_and_no_verification_is_unknown_never_fabricated():
    assert pss.derive_makeability_fields(None)["makeability_bucket"] == "unknown"
    # a cost with NO verification block (no inventory/env declared at cost time) —
    # honestly unknown, never a fabricated verdict (byte-identity-when-unused).
    f = pss.derive_makeability_fields(_cost_json(verdict=None))
    assert f["makeability_verdict"] is None
    assert f["makeability_bucket"] == "unknown"
    assert f["in_house_makeable"] is None


# ═══════════════════════════════════════════════════════════════════════════
# PURE — unlock derivation from real gap data
# ═══════════════════════════════════════════════════════════════════════════


def test_unlock_not_on_owned_single_envelope_gate():
    pr = _nowned("cnc_5axis", [_fail("envelope", 380.0, 305.0)])
    f = pss.derive_makeability_fields(
        _cost_json(process="cnc_5axis", verdict="makeable_not_on_owned", per_route=pr))
    assert f["unlock_process"] == "cnc_5axis"
    assert f["unlock_gate"] == "envelope"
    assert f["unlock_single"] is True
    assert f["unlock_need_num"] == 380.0
    assert f["unlock_need_label"] is None
    assert f["makeability_gap"]["kind"] == "upgrade"


def test_unlock_not_on_owned_material_gate_is_categorical():
    pr = _nowned("cnc_3axis", [_fail("material", "Inconel 718", None)])
    f = pss.derive_makeability_fields(
        _cost_json(verdict="makeable_not_on_owned", per_route=pr))
    assert f["unlock_gate"] == "material"
    assert f["unlock_need_num"] is None
    assert f["unlock_need_label"] == "Inconel 718"
    assert f["unlock_single"] is True


def test_unlock_multi_gate_is_not_single():
    # envelope AND material both block → no single acquisition unlocks it
    pr = _nowned("cnc_3axis", [_fail("material", "Inconel 718", None),
                               _fail("envelope", 500.0, 305.0)])
    f = pss.derive_makeability_fields(
        _cost_json(verdict="makeable_not_on_owned", per_route=pr))
    assert f["unlock_single"] is False
    # the binding gate is the highest-priority one (envelope leads material)
    assert f["unlock_gate"] == "envelope"


def test_unlock_not_on_owned_picks_closest_route():
    # two not-on-owned routes: cnc_5axis has 2 gates, cnc_turning has 1 → pick turning
    pr = {}
    pr.update(_nowned("cnc_5axis", [_fail("envelope", 500.0, 305.0),
                                    _fail("axes", 5, 3)]))
    pr.update(_nowned("cnc_turning", [_fail("envelope", 200.0, 150.0)]))
    f = pss.derive_makeability_fields(
        _cost_json(verdict="makeable_not_on_owned", per_route=pr))
    assert f["unlock_process"] == "cnc_turning"
    assert f["unlock_single"] is True


def test_unlock_outsource_prefers_recommended_route():
    pr = _outsource("cnc_3axis", "cnc_turning", "forging")
    f = pss.derive_makeability_fields(
        _cost_json(process="cnc_turning", verdict="makeable_outsource_only",
                   per_route=pr))
    assert f["unlock_process"] == "cnc_turning"  # the recommended make-now route
    assert f["unlock_gate"] is None              # a pure acquire (owns none)
    assert f["unlock_single"] is True
    assert f["makeability_gap"]["kind"] == "acquire"


# ═══════════════════════════════════════════════════════════════════════════
# PURE — rank_acquisitions math (ties, empty, spec aggregation, staleness)
# ═══════════════════════════════════════════════════════════════════════════


def test_rank_empty_is_empty():
    assert svc.rank_acquisitions([]) == []


def test_rank_orders_by_parts_unlocked_desc():
    groups = [
        {"process": "cnc_turning", "gate": None, "count": 2, "need_min": None,
         "need_max": None, "labels": [], "stale_count": 0, "any_stale": False},
        {"process": "cnc_5axis", "gate": "envelope", "count": 5, "need_min": 350.0,
         "need_max": 420.0, "labels": [], "stale_count": 0, "any_stale": False},
    ]
    r = svc.rank_acquisitions(groups)
    assert [e["parts_unlocked"] for e in r] == [5, 2]
    top = r[0]
    assert top["acquisition"]["kind"] == "upgrade"
    assert top["acquisition"]["process"] == "cnc_5axis"
    # envelope spec aggregates to the MAX need (must clear the largest blocked part)
    assert top["acquisition"]["spec"]["work_envelope_mm_min"] == 420.0
    # the pure-acquire entry names the process, no fabricated dollar anywhere
    acq = r[1]["acquisition"]
    assert acq["kind"] == "acquire" and acq["gate"] is None
    for e in r:
        assert "usd" not in str(e).lower() or "$" not in str(e)  # no dollar figure


def test_rank_ties_break_deterministically_by_process_then_gate():
    groups = [
        {"process": "cnc_5axis", "gate": "material", "count": 3, "need_min": None,
         "need_max": None, "labels": ["Inconel 718"], "stale_count": 0,
         "any_stale": False},
        {"process": "cnc_3axis", "gate": "envelope", "count": 3, "need_min": 40.0,
         "need_max": 40.0, "labels": [], "stale_count": 0, "any_stale": False},
    ]
    r = svc.rank_acquisitions(groups)
    # equal counts → sorted by process id ascending (cnc_3axis before cnc_5axis)
    assert [e["acquisition"]["process"] for e in r] == ["cnc_3axis", "cnc_5axis"]


def test_rank_tolerance_takes_min_it_and_material_unions():
    groups = [
        {"process": "cnc_3axis", "gate": "tolerance", "count": 2, "need_min": 6.0,
         "need_max": 8.0, "labels": [], "stale_count": 0, "any_stale": False},
        {"process": "cnc_turning", "gate": "material", "count": 1, "need_min": None,
         "need_max": None, "labels": ["Inconel 718", "Ti6Al4V", "Inconel 718"],
         "stale_count": 0, "any_stale": False},
    ]
    r = {e["acquisition"]["gate"]: e for e in svc.rank_acquisitions(groups)}
    # tolerance acquisition must hold the TIGHTEST (min IT grade)
    assert r["tolerance"]["acquisition"]["spec"]["achievable_it_grade_max"] == 6.0
    # material acquisition unions + de-dups the required set
    assert r["material"]["acquisition"]["spec"]["qualify_materials"] == \
        ["Inconel 718", "Ti6Al4V"]


def test_rank_carries_staleness_visibly():
    groups = [
        {"process": "cnc_5axis", "gate": "envelope", "count": 4, "need_min": 300.0,
         "need_max": 500.0, "labels": [], "stale_count": 2, "any_stale": True},
    ]
    e = svc.rank_acquisitions(groups)[0]
    assert e["stale"] is True
    assert e["stale_parts"] == 2
    assert e["basis"]  # every entry names its basis (provenance)


# ═══════════════════════════════════════════════════════════════════════════
# LIVE POSTGRES — migration in the chain, isolation, maintenance, routes
# ═══════════════════════════════════════════════════════════════════════════

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


class _Fixture:
    def __init__(self, tag):
        self.tag = tag
        self.org_ids = []
        self.user_ids = []

    async def org(self, s, label):
        from sqlalchemy import text
        from ulid import ULID

        oid = str(ULID())
        await s.execute(
            text("INSERT INTO organizations (id, name, slug, created_at) "
                 "VALUES (:id, :n, :sl, now())"),
            {"id": oid, "n": f"MK {label} {self.tag}", "sl": f"mk-{label}-{self.tag}"},
        )
        self.org_ids.append(oid)
        return oid

    async def user(self, s, org_id, label):
        from sqlalchemy import text
        from ulid import ULID

        email = f"mk-{self.tag}-{label}@example.com"
        uid = int((await s.execute(
            text("INSERT INTO users (email, email_lower, role, auth_provider) "
                 "VALUES (:e, :el, 'analyst', 'password') RETURNING id"),
            {"e": email, "el": email.lower()},
        )).first()[0])
        await s.execute(
            text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                 "VALUES (:id, :o, :u, 'admin', now())"),
            {"id": str(ULID()), "o": org_id, "u": uid},
        )
        kid = int((await s.execute(
            text("INSERT INTO api_keys (user_id, org_id, name, prefix, hmac_index, "
                 "secret_hash) VALUES (:u, :o, :n, :p, :h, 'x') RETURNING id"),
            {"u": uid, "o": org_id, "n": label, "p": f"pfx{label}{self.tag}",
             "h": f"hmac-{self.tag}-{label}"},
        )).first()[0])
        self.user_ids.append(uid)
        from src.auth.require_api_key import AuthedUser

        return AuthedUser(user_id=uid, api_key_id=kid, key_prefix="test", role="analyst")


async def _persist_cost(s, user, mesh, result, *, params=None):
    from src.services import cost_decision_service as csvc

    return await csvc.persist_cost_decision(
        s, user, mesh_hash=mesh, params_hash=params or f"p-{uuid.uuid4().hex}",
        engine_version="0.3.0", filename=f"{mesh}.stl", file_type="stl",
        result_json=result,
    )


async def _cleanup(fx):
    import src.db.engine as eng
    from sqlalchemy import text

    async with eng.get_session_factory()() as s:
        if fx.user_ids:
            ids = fx.user_ids
            await s.execute(text("DELETE FROM part_summaries WHERE org_id = ANY(:o)"), {"o": fx.org_ids})
            await s.execute(text("DELETE FROM machine_instances WHERE org_id = ANY(:o)"), {"o": fx.org_ids})
            await s.execute(text("DELETE FROM analyses WHERE user_id = ANY(:i)"), {"i": ids})
            await s.execute(text("DELETE FROM cost_decisions WHERE user_id = ANY(:i)"), {"i": ids})
            await s.execute(text("DELETE FROM api_keys WHERE user_id = ANY(:i)"), {"i": ids})
            await s.execute(text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": ids})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": ids})
        if fx.org_ids:
            await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": fx.org_ids})
        await s.commit()
    await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_pg_migration_0023_in_chain():
    """After ``alembic upgrade head`` the 0023 columns + org-leading indexes exist
    on ``part_summaries`` — proving the migration is in the chain and applied."""
    import src.db.engine as eng
    from sqlalchemy import text

    async with eng.get_session_factory()() as s:
        cols = {r[0] for r in (await s.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='part_summaries'"))).all()}
        for c in ("makeability_verdict", "in_house_makeable", "makeability_bucket",
                  "makeability_stale", "unlock_process", "unlock_gate",
                  "unlock_single", "unlock_need_num", "unlock_need_label",
                  "makeability_gap"):
            assert c in cols, c
        idx = {r[0] for r in (await s.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='part_summaries'"))).all()}
        assert "ix_part_summaries_org_mkbucket" in idx
        assert "ix_part_summaries_org_unlock" in idx
    await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_pg_two_org_isolation_rollup_and_ranking():
    """Two orgs, distinct parts persisted through the REAL cost funnel. The scaled
    makeability rollup, the capability-investment ranking, AND the drill-down are
    each org-scoped: org A's parts/acquisitions never leak into B's, nor B's into A."""
    import src.db.engine as eng

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org_a = await fx.org(s, "A")
            org_b = await fx.org(s, "B")
            ua = await fx.user(s, org_a, "a")
            ub = await fx.user(s, org_b, "b")

            # Org A: 1 in-house, 2 not-on-owned (cnc_5axis envelope: 380 & 420),
            # 1 outsource_only (cnc_turning). → ranking top = cnc_5axis/envelope (2).
            await _persist_cost(s, ua, f"a-ih-{fx.tag}",
                                _cost_json(verdict="makeable_in_house"))
            await _persist_cost(s, ua, f"a-no1-{fx.tag}",
                                _cost_json(process="cnc_5axis",
                                           verdict="makeable_not_on_owned",
                                           per_route=_nowned("cnc_5axis", [_fail("envelope", 380.0, 305.0)])))
            await _persist_cost(s, ua, f"a-no2-{fx.tag}",
                                _cost_json(process="cnc_5axis",
                                           verdict="makeable_not_on_owned",
                                           per_route=_nowned("cnc_5axis", [_fail("envelope", 420.0, 305.0)])))
            await _persist_cost(s, ua, f"a-out-{fx.tag}",
                                _cost_json(process="cnc_turning",
                                           verdict="makeable_outsource_only",
                                           per_route=_outsource("cnc_turning")))
            # Org B: 3 outsource_only forging parts (must never touch A's ranking).
            for i in (1, 2, 3):
                await _persist_cost(s, ub, f"b-{i}-{fx.tag}",
                                    _cost_json(process="forging",
                                               verdict="makeable_outsource_only",
                                               per_route=_outsource("forging")))
            await s.commit()

        async with eng.get_session_factory()() as s:
            roll_a = await svc.build_makeability_rollup(s, org_a)
            sa = roll_a["summary"]
            assert sa["makeable_in_house"] == 1
            assert sa["needs_capability"] == 2
            assert sa["makeable_outside"] == 1
            assert sa["total"] == 4
            assert sa["stale"] is False and sa["stale_count"] == 0

            rank_a = await svc.build_capability_investment(s, org_a)
            top = rank_a["ranking"][0]
            assert top["acquisition"]["process"] == "cnc_5axis"
            assert top["acquisition"]["gate"] == "envelope"
            assert top["parts_unlocked"] == 2
            # spec aggregates to the MAX blocked dimension (420, not 380)
            assert top["acquisition"]["spec"]["work_envelope_mm_min"] == 420.0
            # B's forging acquisition NEVER appears in A's ranking
            procs_a = {e["acquisition"]["process"] for e in rank_a["ranking"]}
            assert "forging" not in procs_a
            assert rank_a["summary"]["parts_unlockable_by_one_acquisition"] == 3

            # drill-down isolation: A's cnc_5axis/envelope page has exactly A's 2 parts
            page = await svc.build_capability_investment_page(
                s, org_a, "cnc_5axis", "envelope", limit=100)
            keys = {r["part_key"] for r in page["rows"]}
            assert keys == {f"a-no1-{fx.tag}", f"a-no2-{fx.tag}"}
            assert not any(k.startswith("b-") for k in keys)

            # Org B rollup/ranking is B-only
            roll_b = await svc.build_makeability_rollup(s, org_b)
            assert roll_b["summary"]["makeable_outside"] == 3
            assert roll_b["summary"]["total"] == 3
            rank_b = await svc.build_capability_investment(s, org_b)
            assert {e["acquisition"]["process"] for e in rank_b["ranking"]} == {"forging"}
    finally:
        await _cleanup(fx)


@_requires_pg
@pytest.mark.asyncio
async def test_pg_bucket_drill_down_and_bad_cursor_is_400():
    """The bucket drill-down keyset-walks a single bucket; a malformed cursor raises
    the typed ``InvalidCursorError`` (→ the route answers 400, never a 500)."""
    import src.db.engine as eng

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org = await fx.org(s, "T")
            u = await fx.user(s, org, "t")
            for i in range(3):
                await _persist_cost(s, u, f"t-{i}-{fx.tag}",
                                    _cost_json(verdict="makeable_in_house"))
            await s.commit()

        async with eng.get_session_factory()() as s:
            walked = []
            cursor = None
            while True:
                page = await svc.build_makeability_bucket_page(
                    s, org, "makeable_in_house", cursor=cursor, limit=2)
                walked.extend(page["rows"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert len(walked) == 3
            # each drill-down row carries the makeability detail
            assert all(r["makeability"]["verdict"] == "makeable_in_house" for r in walked)

            with pytest.raises(svc.InvalidCursorError):
                await svc.build_makeability_bucket_page(
                    s, org, "makeable_in_house", cursor="!!not-base64!!")
    finally:
        await _cleanup(fx)


@_requires_pg
@pytest.mark.asyncio
async def test_pg_projection_maintenance_on_machine_add_delete():
    """The D2 crux: a machine ADD/DELETE (through the REAL machine-inventory router)
    marks the org's verdict-carrying summaries STALE (visible in the rollup), and a
    re-cost through the REAL cost funnel CLEARS the stale flag — never silently wrong."""
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng

    fx = _Fixture(uuid.uuid4().hex[:8])
    mesh = f"m-{fx.tag}"
    try:
        async with eng.get_session_factory()() as s:
            org = await fx.org(s, "M")
            user = await fx.user(s, org, "m")
            await _persist_cost(s, user, mesh, _cost_json(verdict="makeable_in_house"))
            await s.commit()

        # fresh verdict: not stale
        async with eng.get_session_factory()() as s:
            roll = await svc.build_makeability_rollup(s, org)
            assert roll["summary"]["makeable_in_house"] == 1
            assert roll["summary"]["stale"] is False

        # ADD a machine via the real router → org's verdicts marked stale
        app = _build_app()
        _act_as(app, user.user_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/api/v1/machine-inventory", json={
                "name": "VF-2", "process": "cnc_3axis", "count": 1,
                "max_workpiece_kg": 200, "hourly_rate_usd": 75, "capital_frac": 0.4,
                "capabilities": {"x": 762, "y": 406, "z": 508, "axes": 3},
                "materials": ["steel"]})
            assert r.status_code == 201, r.text
            machine_id = r.json()["id"]

        async with eng.get_session_factory()() as s:
            roll = await svc.build_makeability_rollup(s, org)
            # still counted (bucket unchanged) BUT flagged stale + counted stale
            assert roll["summary"]["makeable_in_house"] == 1
            assert roll["summary"]["stale"] is True
            assert roll["summary"]["stale_count"] == 1

        # RE-COST the part (through the real funnel) → stale cleared for that part
        async with eng.get_session_factory()() as s:
            u2 = type("U", (), {"user_id": fx.user_ids[0]})()
            from src.auth.require_api_key import AuthedUser

            await _persist_cost(
                s, AuthedUser(user_id=fx.user_ids[0], api_key_id=0,
                              key_prefix="t", role="analyst"),
                mesh, _cost_json(verdict="makeable_in_house"),
                params=f"recost-{fx.tag}")
            await s.commit()

        async with eng.get_session_factory()() as s:
            roll = await svc.build_makeability_rollup(s, org)
            assert roll["summary"]["stale"] is False
            assert roll["summary"]["stale_count"] == 0

        # DELETE the machine via the real router → verdicts marked stale again
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            d = await c.delete(f"/api/v1/machine-inventory/{machine_id}")
            assert d.status_code == 200, d.text

        async with eng.get_session_factory()() as s:
            roll = await svc.build_makeability_rollup(s, org)
            assert roll["summary"]["stale"] is True
            assert roll["summary"]["stale_count"] == 1
    finally:
        await _cleanup(fx)


@_requires_pg
@pytest.mark.asyncio
async def test_pg_routes_makeability_and_capability_investment():
    """The org-scoped GET routes end-to-end (resolve_org from the caller): the D3
    rollup + D4 ranking + a bad-cursor 400, and two-org isolation at the route."""
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org_a = await fx.org(s, "A")
            org_b = await fx.org(s, "B")
            ua = await fx.user(s, org_a, "a")
            ub = await fx.user(s, org_b, "b")
            await _persist_cost(s, ua, f"a-1-{fx.tag}",
                                _cost_json(process="cnc_5axis",
                                           verdict="makeable_not_on_owned",
                                           per_route=_nowned("cnc_5axis", [_fail("envelope", 400.0, 305.0)])))
            await _persist_cost(s, ub, f"b-1-{fx.tag}",
                                _cost_json(process="forging",
                                           verdict="makeable_outsource_only",
                                           per_route=_outsource("forging")))
            await s.commit()

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            _act_as(app, ua.user_id)
            rm = await c.get("/api/v1/catalog/makeability")
            assert rm.status_code == 200, rm.text
            body = rm.json()
            assert body["summary"]["needs_capability"] == 1
            assert set(body["buckets"]) == set(svc.MAKEABILITY_BUCKETS)

            rc = await c.get("/api/v1/catalog/capability-investment")
            assert rc.status_code == 200, rc.text
            ranking = rc.json()["ranking"]
            assert ranking and ranking[0]["acquisition"]["process"] == "cnc_5axis"
            assert "forging" not in {e["acquisition"]["process"] for e in ranking}
            # no fabricated dollar figure anywhere in the ranking payload
            assert "acquisition_cost" not in str(rc.json())

            # bad drill-down cursor → typed 400 (never a 500)
            bad = await c.get("/api/v1/catalog/makeability",
                              params={"bucket": "needs_capability", "cursor": "@@@"})
            assert bad.status_code == 400
            # invalid bucket → 400
            badb = await c.get("/api/v1/catalog/makeability",
                               params={"bucket": "nonsense"})
            assert badb.status_code == 400

            # route-level isolation: org B sees only forging, never A's cnc_5axis
            _act_as(app, ub.user_id)
            rc_b = await c.get("/api/v1/catalog/capability-investment")
            procs_b = {e["acquisition"]["process"] for e in rc_b.json()["ranking"]}
            assert procs_b == {"forging"}
    finally:
        await _cleanup(fx)


# ── app builders for the route-level PG tests (mirror the machine-inventory test) ──
def _build_app():
    from fastapi import FastAPI

    from src.api.catalog import router as catalog_router
    from src.api.machine_inventory import router as machine_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(catalog_router, prefix="/api/v1/catalog")
    app.include_router(machine_router, prefix="/api/v1/machine-inventory")
    return app


def _act_as(app, user_id: int) -> None:
    import src.db.engine as eng
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )

    async def _session():
        async with eng.get_session_factory()() as s:
            yield s

    app.dependency_overrides[get_db_session] = _session
