"""Machine load: the hours of work the checked parts put on each machine you own.

Pure: where a part's machine time lands (a recorded in-house outcome at its
quantity, else 100 of each when the newest record sorts it onto your machine,
nothing for parts recorded another way) and the per-machine sums.
Postgres (skipped without it): GET /machine-inventory/load reads the org's
newest record per part and newest recorded outcome, and only the caller's org.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from src.services import machine_load_service as ml


def _est(process, qty, cycle, unit=10.0, material="6061-T6 Aluminum"):
    return {"process": process, "quantity": qty, "material": material, "unit_cost_usd": unit,
            "drivers": [{"name": "cycle_time", "value": cycle, "unit": "hr"}]}


def _result(verdict, *, machine=None, process=None, estimates=(), per_route=None):
    v = {"verdict": verdict, "best_machine": machine, "inventory_declared": True, "per_route": per_route or {}}
    if machine and process:
        v["resource"] = {"machine": machine, "process": process}
    return {"status": "OK", "estimates": list(estimates), "verification": v}


MILL = _result("makeable_in_house", machine="Haas VF-2", process="cnc_3axis",
               estimates=[_est("cnc_3axis", 10, 0.5), _est("cnc_3axis", 100, 0.25), _est("mjf", 100, 0.1, unit=5.0)],
               per_route={"cnc_3axis": {"verdict": "makeable_in_house", "best_machine": "Haas VF-2"},
                          "mjf": {"verdict": "makeable_in_house", "best_machine": "HP Jet Fusion 5200"}})


def test_not_decided_lands_on_the_machine_the_record_sorts_it_onto_at_the_quantity_its_page_opens_at():
    # Priced at 10 and 100: the part page opens at 10, so the load counts 10 (catalog_service.opening_qty).
    load = ml.part_load(MILL, None, None)
    assert load == {"basis": "default", "machine": "Haas VF-2", "process": "cnc_3axis", "quantity": 10,
                    "quantity_basis": "opening", "hours_each": 0.5, "hours": 5.0}


def test_a_part_checked_at_its_own_quantities_counts_its_hours_never_not_estimated():
    """me-13: the shaft checked at 25 and 250 showed "machine time not estimated" on the ST-20."""
    lathe = _result("makeable_in_house", machine="Haas ST-20", process="cnc_turning",
                    estimates=[_est("cnc_turning", 25, 0.116), _est("cnc_turning", 250, 0.104)])
    lathe["quantities"] = [25, 250]
    load = ml.part_load(lathe, None, None)
    assert (load["machine"], load["quantity"], load["quantity_basis"], load["hours"]) == ("Haas ST-20", 25, "opening", 2.9)
    # Nothing priced at all: the default quantity, and the hours stay unknown (never estimated here).
    assert ml.load_quantity({"estimates": []}, None) == (100, "default")


def test_not_decided_counts_at_the_quantity_the_part_was_checked_for():
    # A catalog run listed 25 of it: the ladder carries 25 in place of 100.
    run = {**MILL, "quantities": [1, 25, 1000, 2000, 5000, 10000],
           "estimates": [_est("cnc_3axis", 25, 0.3), _est("cnc_3axis", 1000, 0.2)]}
    load = ml.part_load(run, None, None)
    assert (load["basis"], load["quantity"], load["hours"]) == ("checked", 25, 7.5)
    assert ml.checked_quantity({"quantities": [1, 100, 1000, 2000, 5000, 10000]}) is None
    assert ml.checked_quantity({"quantities": [1, 100, 500, 2000, 5000, 10000]}) == 500
    assert ml.checked_quantity({}) is None
    # Quantities chosen another way (an API call's "10, 100") name no checked quantity.
    assert ml.checked_quantity({"quantities": [10, 100]}) is None
    assert ml.checked_quantity({"quantities": [10, 100, 1000, 10000]}) is None


def test_a_recorded_in_house_outcome_counts_at_its_own_quantity_and_route():
    load = ml.part_load(MILL, "inhouse", {"process": "cnc_3axis", "quantity": 10, "material": "6061-T6 Aluminum"})
    assert (load["basis"], load["machine"], load["quantity"], load["hours"]) == ("decided", "Haas VF-2", 10, 5.0)
    # Recorded on another route of yours: that route's machine.
    other = ml.part_load(MILL, "inhouse", {"process": "mjf", "quantity": 100})
    assert (other["machine"], other["hours"]) == ("HP Jet Fusion 5200", 10.0)


# op-12: the parts list's yearly quantity, on the ladder or off it, is the load's quantity.
LISTED = {**MILL, "quantities": [1, 100, 1000, 2000, 5000, 10000],
          "estimates": [_est("cnc_3axis", 100, 0.1), _est("cnc_3axis", 1000, 0.069)],
          "decision": {"options": {"1000": {"in_house": {"process": "cnc_3axis", "machine": "Haas VF-2",
                                                         "unit_cost_usd": 20.0, "low_usd": 17.0, "high_usd": 23.0}},
                                   "100": {"in_house": {"process": "cnc_3axis", "machine": "Haas VF-2",
                                                        "unit_cost_usd": 25.0, "low_usd": 21.0, "high_usd": 29.0}}}}}


def test_a_part_counts_at_its_yearly_quantity_also_when_the_ladder_already_has_it():
    # RFS-21030: 1,000 a year sits on the ladder, so the record names no "checked" quantity; it was counted at 100.
    load = ml.part_load(LISTED, None, None, yearly=1000)
    assert (load["quantity"], load["quantity_basis"], load["hours"]) == (1000, "yearly", 69.0)
    # A yearly quantity the record didn't price: the checked one, else the default (never an estimate here).
    assert ml.load_quantity(LISTED, 750) == (100, "opening")
    assert ml.load_quantity({"quantities": [1, 100, 750, 2000, 5000, 10000]}, 750) == (750, "yearly")


def test_a_sign_off_at_another_quantity_never_changes_the_load_basis():
    # The valve stem signed off at 100 (op-08): its load stays at its 1,000 a year, and says it was decided at 100.
    load = ml.part_load(LISTED, "inhouse", {"process": "cnc_3axis", "quantity": 100}, yearly=1000)
    assert (load["basis"], load["quantity"], load["decided_quantity"], load["hours"]) == ("decided", 1000, 100, 69.0)
    out = ml.machine_load([{"part_key": "s", "file_name": "stem.step", "result": LISTED, "disposition": "inhouse",
                            "basis": {"process": "cnc_3axis", "quantity": 100}, "yearly": 1000}])
    assert out["decided_at_other_quantity"] == 1 and out["machines"][0]["hours"] == 69.0


def test_a_part_cheaper_to_keep_buying_adds_no_hours():
    # Undecided, a machine of yours could make it, but what you pay today is below its range: bought, as the run sorts it.
    load = ml.part_load(LISTED, None, None, yearly=1000, buy_price={"usd_each": 12.0, "source": "parts_list"})
    assert load["basis"] == "bought" and (load["make_each"], load["buy_each"]) == (20.0, 12.0)
    # op-07: lower but inside the in-house range is still bought; within 2% is a tie and stays bought too.
    assert ml.part_load(LISTED, None, None, yearly=1000, buy_price={"usd_each": 18.0})["basis"] == "bought"
    assert ml.part_load(LISTED, None, None, yearly=1000, buy_price={"usd_each": 20.3})["basis"] == "bought"
    assert ml.part_load(LISTED, None, None, yearly=1000, buy_price={"usd_each": 21.0})["basis"] == "checked"
    assert ml.part_load(LISTED, None, None, yearly=1000, buy_price={"usd_each": 33.0})["hours"] == 69.0
    # Recorded "Keep buying from our supplier": a buy outcome, never machine hours.
    assert ml.part_load(LISTED, "supplier", {"supplier": True, "quantity": 1000}) == {"basis": "other",
                                                                                     "disposition": "supplier"}
    out = ml.machine_load([
        {"part_key": "a", "result": LISTED, "yearly": 1000, "buy_price": {"usd_each": 12.0}},
        {"part_key": "b", "result": LISTED, "disposition": "supplier", "basis": {"supplier": True}},
        {"part_key": "c", "result": LISTED, "yearly": 1000}])
    assert (out["bought"], out["other_decisions"], out["machines"][0]["parts"]) == (1, 1, 1)


def test_capacity_is_schedule_times_count_and_says_when_its_assumed():
    cap = ml.capacity_by_name([{"name": "Haas VF-2 (mill cell)", "count": 3, "schedule": None},
                               {"name": "Lathe", "count": 1, "schedule": {"shifts": 1, "hours_per_shift": 8,
                                                                         "days_per_year": 250}}])
    assert cap["Haas VF-2 (mill cell)"]["hours"] == 11520.0 and cap["Haas VF-2 (mill cell)"]["set"] is False
    assert cap["Lathe"]["hours"] == 2000.0 and cap["Lathe"]["set"] is True
    assert ml.schedule_text(cap["Haas VF-2 (mill cell)"]) == (
        "3 machines × 2 shifts × 8 h × 240 days = 11,520 h a year (assumed; set its hours in Your shop)")
    assert ml.schedule_text(cap["Lathe"]) == "1 shift × 8 h × 250 days = 2,000 h a year"
    rows = ml.with_capacity([{"machine": "Haas VF-2 (mill cell)", "hours": 2830.0},
                             {"machine": "Lathe", "hours": 2161.0}, {"machine": "Elsewhere", "hours": 5.0}], cap)
    assert [(r["utilization_pct"], r["overloaded"]) for r in rows] == [(24.6, False), (108.0, True), (None, None)]
    assert ml.overloaded_words(rows) == ["Lathe: 2,161 h needed of 2,000 h a year (108%)"]


@pytest.mark.parametrize("raw, words", [
    ({"shifts": 0}, "shifts must be from 1 to 4"),
    ({"hours_per_shift": 30}, "hours per shift must be from 0.5 to 24"),
    ({"shifts": 3, "hours_per_shift": 10}, "at most 24 hours a day"),
    ({"weeks": 50}, "unknown schedule field"),
    ("2x8", "must be an object"),
])
def test_a_schedule_it_cant_use_names_the_field(raw, words):
    with pytest.raises(ValueError, match=words):
        ml.normalize_schedule(raw)
    assert ml.normalize_schedule({"shifts": 3}) == {"shifts": 3, "hours_per_shift": 8.0, "days_per_year": 240}


def test_a_quantity_the_record_didnt_price_leaves_the_hours_unknown():
    load = ml.part_load(MILL, "inhouse", {"process": "cnc_3axis", "quantity": 250})
    assert load["machine"] == "Haas VF-2" and load["hours_each"] is None and load["hours"] is None


def test_recorded_another_way_or_not_on_your_machines_isnt_load():
    assert ml.part_load(MILL, "outside", {"process": "fdm", "quantity": 10}) == {"basis": "other", "disposition": "outside"}
    assert ml.part_load(_result("makeable_outsource_only", estimates=[_est("fdm", 100, 1.0)]), None, None) is None
    assert ml.part_load(None, None, None) is None
    # Recorded in-house, but no machine of yours clears that route on the newest record.
    gone = ml.part_load(_result("makeable_outsource_only", estimates=[_est("fdm", 10, 1.0)]), "inhouse", {"process": "fdm", "quantity": 10})
    assert gone["basis"] == "decided" and gone["machine"] is None and gone["hours"] == 10.0


def test_per_machine_sums_split_decided_from_not_yet_decided():
    parts = [
        {"part_key": "a", "record_id": "R1", "file_name": "a.step", "result": MILL, "disposition": None, "basis": None},
        {"part_key": "b", "record_id": "R2", "file_name": "b.step", "label": "BRK-100", "result": MILL,
         "disposition": "inhouse", "basis": {"process": "cnc_3axis", "quantity": 10}, "stale": True},
        {"part_key": "c", "record_id": "R3", "file_name": "c.step", "result": MILL,
         "disposition": "inhouse", "basis": {"process": "cnc_3axis", "quantity": 250}},
        {"part_key": "d", "record_id": "R4", "file_name": "d.step", "result": MILL, "disposition": "outside", "basis": None},
        {"part_key": "e", "record_id": "R5", "file_name": "e.step",
         "result": _result("makeable_outsource_only", estimates=[_est("fdm", 10, 1.0)]),
         "disposition": "inhouse", "basis": {"process": "fdm", "quantity": 10}},
        {"part_key": "f", "record_id": "R6", "file_name": "f.step", "result": _result("makeable_outsource_only"),
         "disposition": None, "basis": None},
    ]
    out = ml.machine_load(parts)
    assert (out["quantity"], out["parts"], out["other_decisions"], out["decided_unplaced_count"]) == (100, 6, 1, 1)
    assert out["decided_unplaced"][0]["file_name"] == "e.step"
    (haas,) = out["machines"]
    assert haas["machine"] == "Haas VF-2" and haas["process"] == "cnc_3axis"
    assert (haas["parts"], haas["hours"], haas["hours_parts"]) == (3, 10.0, 2)
    assert (haas["decided_parts"], haas["decided_hours"], haas["default_parts"], haas["default_hours"]) == (2, 5.0, 1, 5.0)
    assert haas["stale_parts"] == 1
    assert [(t["file_name"], t["basis"], t["quantity"], t["hours"]) for t in haas["top"]] == [
        ("BRK-100", "decided", 10, 5.0), ("a.step", "default", 10, 5.0), ("c.step", "decided", 250, None)]


# ── Postgres: the endpoint, org-scoped ───────────────────────────────────────
_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")


@pytest_asyncio.fixture
async def orgs():
    if not _PG:
        pytest.skip("requires PostgreSQL at schema head (DATABASE_URL=postgresql://...)")
    from fastapi import FastAPI
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.api.machine_inventory import router
    from src.auth.rate_limit import limiter
    from src.db.models import CostDecision

    await eng.dispose_engine()
    tag = uuid.uuid4().hex[:10]
    ids = {}
    async with eng.get_session_factory()() as s, s.begin():
        for label in ("mine", "theirs"):
            org = str(ULID())
            await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :n, now())"),
                            {"id": org, "n": f"load-{label}-{tag}"})
            uid = (await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider, plan, current_org_id) "
                "VALUES (:e, :e, 'analyst', 'password', 'pilot', :o) RETURNING id"
            ), {"e": f"{label}-{tag}@acme-aero.com", "o": org})).scalar_one()
            await s.execute(text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:id, :o, :u, 'admin', now())"
            ), {"id": str(ULID()), "o": org, "u": uid})
            ids[label] = (org, uid)

        def rec(label, key, result, params="p", **gov):
            org, uid = ids[label]
            return CostDecision(ulid=str(ULID()), user_id=uid, org_id=org, mesh_hash=key, params_hash=params,
                                engine_version="test", filename=f"{key[:6]}.step", file_type="step",
                                result_json=result, **gov)

        old = rec("mine", "a" * 64, MILL, user_disposition="inhouse",
                  disposition_basis={"process": "cnc_3axis", "quantity": 10, "material": "6061-T6 Aluminum"})
        s.add(old)
        await s.flush()
        # A newer check of the same part: its outcome stays the one recorded on the older record.
        s.add(rec("mine", "a" * 64, MILL, params="p2"))
        s.add(rec("mine", "b" * 64, MILL))
        await s.flush()
        # me-13: a newer re-check of b that failed to price never wipes its hours.
        s.add(rec("mine", "b" * 64, {"status": "OK", "estimates": [], "cost_error": "timed out",
                                     "verification": MILL["verification"]}, params="p3"))
        # A catalog-run part listed at 25: its record's ladder carries 25 in place of 100.
        listed = {**MILL, "estimates": [_est("cnc_3axis", 25, 0.3)]}
        s.add(rec("mine", "d" * 64, listed, quantities=[1, 25, 1000, 2000, 5000, 10000]))
        s.add(rec("theirs", "c" * 64, MILL))
        # Part b is listed at 10 a year; the Haas cell is 2 machines on one 8-hour shift, 200 days.
        await s.execute(text("INSERT INTO part_contexts (ulid, org_id, mesh_hash, annual_volume) "
                             "VALUES (:u, :o, :h, 10)"), {"u": str(ULID()), "o": ids["mine"][0], "h": "b" * 64})
        await s.execute(text(
            "INSERT INTO machine_instances (ulid, org_id, name, process, count, capabilities, schedule) "
            "VALUES (:u, :o, 'Haas VF-2', 'cnc_3axis', 2, '{}', "
            "'{\"shifts\": 1, \"hours_per_shift\": 8, \"days_per_year\": 200}')"),
            {"u": str(ULID()), "o": ids["mine"][0]})
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/machine-inventory")
    try:
        yield {"app": app, "ids": ids}
    finally:
        async with eng.get_session_factory()() as s, s.begin():
            for org, uid in ids.values():
                await s.execute(text("DELETE FROM cost_decisions WHERE org_id = :o"), {"o": org})
                await s.execute(text("DELETE FROM part_contexts WHERE org_id = :o"), {"o": org})
                await s.execute(text("DELETE FROM machine_instances WHERE org_id = :o"), {"o": org})
                await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
                await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await eng.dispose_engine()


async def _get(app, uid, path):
    from httpx import ASGITransport, AsyncClient

    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=uid, api_key_id=0, key_prefix="session", role="analyst")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.get(path)


@pytest.mark.asyncio
async def test_load_endpoint_reads_only_the_callers_org(orgs):
    org, uid = orgs["ids"]["mine"]
    r = await _get(orgs["app"], uid, "/api/v1/machine-inventory/load")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parts"] == 3  # the other org's part isn't read
    (haas,) = body["machines"]
    assert (haas["machine"], haas["parts"], haas["decided_parts"], haas["decided_hours"]) == ("Haas VF-2", 3, 1, 5.0)
    # b counts at its 10 a year (5 h), d at its listed 25 (7.5 h), a as decided at 10 (5 h).
    assert (haas["default_parts"], haas["default_hours"], haas["hours"]) == (2, 12.5, 17.5)
    listed = next(t for t in haas["top"] if t["part_key"] == "d" * 64)
    assert (listed["basis"], listed["quantity"], listed["hours"]) == ("checked", 25, 7.5)
    yearly = next(t for t in haas["top"] if t["part_key"] == "b" * 64)
    assert (yearly["quantity"], yearly["quantity_basis"], yearly["hours"]) == (10, "yearly", 5.0)
    assert (haas["available_hours"], haas["utilization_pct"], haas["overloaded"]) == (3200.0, 0.5, False)
    assert haas["capacity"]["text"] == "2 machines × 1 shift × 8 h × 200 days = 3,200 h a year"
    _, other_uid = orgs["ids"]["theirs"]
    theirs = (await _get(orgs["app"], other_uid, "/api/v1/machine-inventory/load")).json()
    assert theirs["parts"] == 1 and theirs["machines"][0]["decided_parts"] == 0
