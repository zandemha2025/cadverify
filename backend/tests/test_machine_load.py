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


def test_not_decided_lands_on_the_machine_the_record_sorts_it_onto_at_100_of_each():
    load = ml.part_load(MILL, None, None)
    assert load == {"basis": "default", "machine": "Haas VF-2", "process": "cnc_3axis", "quantity": 100,
                    "hours_each": 0.25, "hours": 25.0}


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
    assert (haas["parts"], haas["hours"], haas["hours_parts"]) == (3, 30.0, 2)
    assert (haas["decided_parts"], haas["decided_hours"], haas["default_parts"], haas["default_hours"]) == (2, 5.0, 1, 25.0)
    assert haas["stale_parts"] == 1
    assert [(t["file_name"], t["basis"], t["quantity"], t["hours"]) for t in haas["top"]] == [
        ("a.step", "default", 100, 25.0), ("BRK-100", "decided", 10, 5.0), ("c.step", "decided", 250, None)]


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
        # A catalog-run part listed at 25: its record's ladder carries 25 in place of 100.
        listed = {**MILL, "estimates": [_est("cnc_3axis", 25, 0.3)]}
        s.add(rec("mine", "d" * 64, listed, quantities=[1, 25, 1000, 2000, 5000, 10000]))
        s.add(rec("theirs", "c" * 64, MILL))
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/machine-inventory")
    try:
        yield {"app": app, "ids": ids}
    finally:
        async with eng.get_session_factory()() as s, s.begin():
            for org, uid in ids.values():
                await s.execute(text("DELETE FROM cost_decisions WHERE org_id = :o"), {"o": org})
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
    assert (haas["default_parts"], haas["default_hours"], haas["hours"]) == (2, 32.5, 37.5)
    listed = next(t for t in haas["top"] if t["part_key"] == "d" * 64)
    assert (listed["basis"], listed["quantity"], listed["hours"]) == ("checked", 25, 7.5)
    _, other_uid = orgs["ids"]["theirs"]
    theirs = (await _get(orgs["app"], other_uid, "/api/v1/machine-inventory/load")).json()
    assert theirs["parts"] == 1 and theirs["machines"][0]["decided_parts"] == 0
