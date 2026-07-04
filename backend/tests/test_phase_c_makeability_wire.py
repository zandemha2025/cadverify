"""Phase C — machine-inventory verification wired into the LIVE cost path.

Covers the Phase-C deliverables against the REAL orchestrator (estimate_decision
→ report_to_dict), procedural meshes only so these always run in CI:

  * byte-identity: NO inventory + NO env → report dict is IDENTICAL and carries
    NO ``verification`` key (a regression test that FAILS if someone later makes
    the key always-on); inventory present but NO machine matching a route → the
    ``estimates`` stay byte-identical (only the additive verdict block is added).
  * verdict shapes incl. the negative/unknown first-class outcomes:
    makeable_in_house / makeable_not_on_owned (+ concrete gap) /
    makeable_outsource_only / unknown-no-inventory.
  * machine-specific MARGINAL rate: a passing owned machine re-costs its process
    at its OWN declared rate; the machine_cost driver is SHOP-tagged and NAMES
    the machine; owned_in_house flips; other processes are untouched.
  * real-profile service-environment integration: a declared sour environment
    excludes a non-NACE material with a CITED exclusion, straight off the loader's
    nested-compliance MaterialProfile shape (NOT a hand-built flat dict).

A live-Postgres block (skipped without DATABASE_URL=postgresql://…) proves
two-org isolation: org A's declared machine informs A's verdict and NEVER B's.
"""
from __future__ import annotations

import os

import pytest

from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.costing.makeability import MachineCap

from tests.test_costing_model import _analyze, _bulky_block, _driver, _est


# ─────────────────────────────────────────────────────────────────────────────
# Builders — machines for the STEEL shortlist of the 40×30×25 procedural block
#   (cnc_3axis|Mild Steel, cnc_turning|Mild Steel, wire_edm|AISI 4130,
#    cnc_5axis|AISI 4130, sand_casting|Ductile Iron, forging|Mild Steel)
# ─────────────────────────────────────────────────────────────────────────────
def _mill(name="Haas VF-2 #3", x=762, y=406, z=508, materials=("steel", "Mild Steel"),
          max_kg=200.0, rate=75.0, capital_frac=0.4, it=9, process="cnc_3axis"):
    caps = {"x": x, "y": y, "z": z, "axes": 3}
    if it is not None:
        caps["achievable_it_grade"] = it
    return MachineCap(process=process, name=name, count=1, max_workpiece_kg=max_kg,
                      hourly_rate_usd=rate, capital_frac=capital_frac,
                      materials=tuple(materials), capabilities=caps)


def _report(inventory=(), env=None, shop_caps=None, material_class="steel",
            qtys=(10, 1000)):
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=list(qtys), material_class=material_class,
                           material_class_is_user=True,
                           inventory=tuple(inventory), service_environment=env,
                           shop_caps=shop_caps)
    return estimate_decision(result, mesh, feats, opts)


# ─────────────────────────────────────────────────────────────────────────────
# BYTE-IDENTITY (spec §2.1 — the hard invariant)
# ─────────────────────────────────────────────────────────────────────────────
def test_no_inventory_no_env_is_byte_identical_and_adds_no_key():
    """No machines + no environment → the served dict is identical AND carries NO
    verification key. This FAILS the instant someone makes the key always-on."""
    base = report_to_dict(_report())
    again = report_to_dict(_report())
    assert base == again
    assert "verification" not in base
    assert base["decision"] is not None  # a real decision was produced


def test_report_has_no_verification_attr_leak_when_unused():
    rep = _report()
    assert rep.verification is None


def test_estimates_byte_identical_when_no_machine_matches_a_route():
    """Inventory present but NO owned machine runs any eligible process (an SLA
    printer for a steel block) → the marginal-rate seam is a no-op → the
    ``estimates`` are byte-identical to the no-inventory path (spec C2). Only the
    additive verdict block differs."""
    sla = MachineCap(process="sla", name="Form 3", count=1, max_workpiece_kg=5.0,
                     hourly_rate_usd=12.0, capital_frac=0.3,
                     materials=("polymer",), capabilities={"x": 145, "y": 145, "z": 185})
    base = report_to_dict(_report())
    with_inv = report_to_dict(_report(inventory=[sla]))
    assert with_inv["estimates"] == base["estimates"]
    # the verdict block IS added, and it is an honest outsource_only (owns nothing
    # of any eligible family) — never a fabricated pass.
    assert with_inv["verification"]["verdict"] == "makeable_outsource_only"


# ─────────────────────────────────────────────────────────────────────────────
# VERDICT SHAPES on the live path (incl. negative / unknown, first-class)
# ─────────────────────────────────────────────────────────────────────────────
def test_makeable_in_house_verdict_on_report():
    rep = _report(inventory=[_mill()])
    v = report_to_dict(rep)["verification"]
    assert v["verdict"] == "makeable_in_house"
    assert v["best_machine"] == "Haas VF-2 #3"
    assert v["inventory_declared"] is True
    assert v["environment_declared"] is False
    assert v["provenance"] == "user"
    # per-route detail names the machine that passed cnc_3axis
    assert v["per_route"]["cnc_3axis"]["verdict"] == "makeable_in_house"
    assert v["per_route"]["cnc_3axis"]["best_machine"] == "Haas VF-2 #3"


def test_makeable_not_on_owned_carries_concrete_gap():
    """A machine too small on every axis → the negative verdict is first-class and
    the gap is a CONCRETE measured-vs-declared delta, never a vague 'too big'."""
    tiny = _mill(name="mini", x=20, y=20, z=20)
    v = report_to_dict(_report(inventory=[tiny]))["verification"]
    assert v["verdict"] == "makeable_not_on_owned"
    assert v["gap"], "expected a concrete acquisition gap"
    g0 = v["gap"][0]
    assert g0["gate"] == "envelope"
    assert g0["have"] is not None and g0["need"] is not None  # quantified
    assert g0["have"] == 20  # cites the owned machine's real envelope


def test_makeable_outsource_only_when_family_unowned():
    v = report_to_dict(_report(inventory=[_mill(process="sla", materials=("polymer",))]))[
        "verification"]
    assert v["verdict"] == "makeable_outsource_only"


def test_unknown_when_env_declared_but_no_inventory():
    """Environment declared, NO machines → the machine verdict is honestly
    'unknown' (never a fake pass), and it is still a first-class block because an
    environment was declared."""
    v = report_to_dict(_report(env={"max_temp_c": 200}))["verification"]
    assert v["verdict"] == "unknown"
    assert v["inventory_declared"] is False
    assert v["environment_declared"] is True


def test_unknown_when_capability_undeclared_not_fabricated_pass():
    """A machine of the right family whose ENVELOPE/mass are undeclared → the
    cnc_3axis route fit is 'unknown' for those axes → NEVER a fabricated makeable.
    (The aggregate is outsource_only because the other 5 routes are unowned — also
    honest; the point is the owned-family route is not faked green.)"""
    mystery = MachineCap(process="cnc_3axis", name="mystery", count=1,
                         max_workpiece_kg=None, hourly_rate_usd=75.0,
                         capital_frac=None, materials=("steel",),
                         capabilities={"axes": 3})  # no envelope, no mass
    v = report_to_dict(_report(inventory=[mystery]))["verification"]
    assert v["per_route"]["cnc_3axis"]["verdict"] == "unknown"
    assert v["verdict"] != "makeable_in_house"  # never a fabricated pass
    # the unknown route surfaces the undeclared gates (have is None), not a gap
    unknown_gates = {f["gate"] for f in v["per_route"]["cnc_3axis"]["failures"]}
    assert {"envelope", "mass"} <= unknown_gates


# ─────────────────────────────────────────────────────────────────────────────
# MACHINE-SPECIFIC MARGINAL RATE + provenance (spec C2)
# ─────────────────────────────────────────────────────────────────────────────
def test_marginal_rate_substituted_and_shop_tagged_naming_machine():
    """A passing owned machine re-costs cnc_3axis at its OWN rate: the machine_cost
    driver is SHOP-tagged, NAMES the machine, and owned_in_house flips."""
    base = report_to_dict(_report())
    e0 = _est_dict(base, "cnc_3axis", 10)
    machine_line_base = _driver(e0, "machine_cost")

    rep = report_to_dict(_report(inventory=[_mill(rate=200.0, capital_frac=0.5)]))
    e1 = _est_dict(rep, "cnc_3axis", 10)
    md = _driver(e1, "machine_cost")
    assert md["provenance"] == "SHOP"
    assert "Haas VF-2 #3" in md["source"]
    assert "200" in md["source"]  # the machine's own declared rate appears
    # the machine cost genuinely changed vs the generic rate-card path
    assert md["value"] != machine_line_base["value"]
    # first-class make-it-ourselves flag + a machine-named owned_in_house driver
    assert e1.get("owned_in_house") is True
    od = _driver(e1, "owned_in_house")
    assert od is not None and "Haas VF-2 #3" in od["source"]
    assert od["provenance"] == "USER"  # ownership is USER-declared


def test_marginal_rate_only_touches_the_fitted_process():
    """Owning a cnc_3axis machine must not change wire_edm / cnc_5axis lines
    (their material AISI 4130 isn't on this mill, and there's no owned EDM)."""
    base = report_to_dict(_report())
    rep = report_to_dict(_report(inventory=[_mill()]))
    for proc in ("wire_edm", "cnc_5axis", "forging"):
        b = _est_dict(base, proc, 10)
        r = _est_dict(rep, proc, 10)
        if b is not None and r is not None:
            assert r["line_items"] == b["line_items"], proc


def test_line_items_still_sum_on_the_machine_rate_path():
    rep = report_to_dict(_report(inventory=[_mill()]))
    for e in rep["estimates"]:
        s = round(sum(e["line_items"].values()), 2)
        assert abs(e["unit_cost_usd"] - s) < 0.02, e["process"]


def test_per_machine_capital_frac_drives_the_marginal_seam():
    """A machine that declares its OWN capital_frac=0 is fully-loaded (off-switch
    honored per-machine): owned_in_house is NOT set, no capital removed."""
    m0 = _mill(rate=100.0, capital_frac=0.0)
    e = _est_dict(report_to_dict(_report(inventory=[m0])), "cnc_3axis", 10)
    assert e.get("owned_in_house") is None  # no marginal seam when cap_frac == 0
    md = _driver(e, "machine_cost")
    assert md["provenance"] == "SHOP" and "100" in md["source"]


# ─────────────────────────────────────────────────────────────────────────────
# REAL-PROFILE service-environment integration (loader's nested-compliance shape)
# ─────────────────────────────────────────────────────────────────────────────
def test_sour_env_excludes_non_nace_material_with_cited_exclusion():
    """A declared sour environment excludes the non-NACE materials in the live
    shortlist (Mild Steel / Ductile Iron) and CITES NACE MR0175 — read straight
    off the real MaterialProfile.compliance nested flags, not a flat dict. AISI
    4130 (NACE-qualified) is NOT excluded."""
    rep = report_to_dict(_report(inventory=[_mill()], env={"sour_service": True}))
    v = rep["verification"]
    excl_axes = {e["axis"] for e in v["env_exclusions"]}
    assert "Mild Steel" in excl_axes  # non-NACE → excluded
    assert "AISI 4130" not in excl_axes  # NACE-qualified → allowed
    mild = [e for e in v["env_exclusions"] if e["axis"] == "Mild Steel"][0]
    assert "NACE MR0175" in mild["human"]  # cited, not a naked drop


def test_over_temp_env_excludes_material_below_service_temp():
    """A 500°C service excludes materials whose real max_temperature is below it,
    citing the temperature — off the loader's top-level max_temperature field."""
    rep = report_to_dict(_report(inventory=[_mill()], env={"max_temp_c": 5000}))
    v = rep["verification"]
    # AISI 4130 max_temperature is 400°C < 5000 → excluded with a temp citation
    temp_excl = [e for e in v["env_exclusions"]
                 if "service temperature" in e["human"]]
    assert temp_excl, "expected a cited over-temperature exclusion"


# small local helper: fetch a serialized estimate dict from a report dict
def _est_dict(report_dict, process, qty):
    for e in report_dict["estimates"]:
        if e["process"] == process and e["quantity"] == qty:
            return e
    return None


# ═════════════════════════════════════════════════════════════════════════════
# LIVE POSTGRES — two-org isolation (org A's machines never inform org B)
# ═════════════════════════════════════════════════════════════════════════════
_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


async def _seed_org_user(s, oid: str, label: str) -> int:
    from sqlalchemy import text
    from ulid import ULID

    await s.execute(
        text("INSERT INTO organizations (id, name, slug, created_at) "
             "VALUES (:id, :n, :sl, now())"),
        {"id": oid, "n": f"Org {label} {oid[-8:]}", "sl": f"org-{oid[-8:].lower()}"},
    )
    email = f"phasec-{oid[-8:]}-{label}@example.com"
    uid = int((await s.execute(
        text("INSERT INTO users (email, email_lower, role, auth_provider) "
             "VALUES (:e, :el, 'analyst', 'password') RETURNING id"),
        {"e": email, "el": email.lower()},
    )).first()[0])
    await s.execute(
        text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
             "VALUES (:id, :o, :u, 'admin', now())"),
        {"id": str(ULID()), "o": oid, "u": uid},
    )
    return uid


async def _cleanup(oids, uids) -> None:
    from sqlalchemy import text
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(text("DELETE FROM machine_instances WHERE org_id = ANY(:o)"),
                        {"o": oids})
        await s.execute(text("DELETE FROM part_contexts WHERE org_id = ANY(:o)"),
                        {"o": oids})
        if uids:
            await s.execute(text("DELETE FROM memberships WHERE user_id = ANY(:i)"),
                            {"i": uids})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": uids})
        await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"),
                        {"o": oids})
        await s.commit()


@_requires_pg
@pytest.mark.asyncio
async def test_pg_two_org_machine_isolation_in_verdict():
    """The SAME part, costed for two orgs on real Postgres: org A owns a mill that
    FITS (→ makeable_in_house on A's machine); org B owns a mill too SMALL (→
    makeable_not_on_owned). A's machine never leaks into B's verdict, and B's
    never into A's. Uses the REAL org-scoped ``load_org_inventory`` loader +
    the REAL ``estimate_decision`` wiring — the exact isolation the route relies on.
    """
    from ulid import ULID
    import src.db.engine as eng
    from src.services import machine_inventory_service as svc

    org_a, org_b = str(ULID()), str(ULID())
    uids: list[int] = []
    try:
        async with eng.get_session_factory()() as s:
            a1 = await _seed_org_user(s, org_a, "A")
            b1 = await _seed_org_user(s, org_b, "B")
            uids += [a1, b1]
            # A: a mill that FITS the 40×30×25 block; B: a mill too small on Z
            await svc.create_machine(s, org_a, {
                "name": "A-VF2", "process": "cnc_3axis", "count": 1,
                "max_workpiece_kg": 200, "hourly_rate_usd": 75, "capital_frac": 0.4,
                "capabilities": {"x": 762, "y": 406, "z": 508, "axes": 3,
                                 "achievable_it_grade": 9},
                "materials": ["steel", "Mild Steel"]}, created_by=a1)
            await svc.create_machine(s, org_b, {
                "name": "B-mini", "process": "cnc_3axis", "count": 1,
                "max_workpiece_kg": 200, "hourly_rate_usd": 90, "capital_frac": 0.4,
                "capabilities": {"x": 20, "y": 20, "z": 20, "axes": 3,
                                 "achievable_it_grade": 9},
                "materials": ["steel", "Mild Steel"]}, created_by=b1)
            await s.commit()

        result, mesh, feats = _analyze(_bulky_block())

        async with eng.get_session_factory()() as s:
            inv_a = await svc.load_org_inventory(s, org_a)
            inv_b = await svc.load_org_inventory(s, org_b)

        # org-scoped loads never cross tenants
        assert {m.name for m in inv_a} == {"A-VF2"}
        assert {m.name for m in inv_b} == {"B-mini"}

        def _verdict(inv):
            opts = EstimateOptions(quantities=[10, 1000], material_class="steel",
                                   material_class_is_user=True, inventory=tuple(inv))
            return report_to_dict(estimate_decision(result, mesh, feats, opts))[
                "verification"]

        va = _verdict(inv_a)
        vb = _verdict(inv_b)
        assert va["verdict"] == "makeable_in_house"
        assert va["best_machine"] == "A-VF2"
        assert vb["verdict"] == "makeable_not_on_owned"
        # B's block never sees A-VF2; A's never sees B-mini
        assert "A-VF2" not in str(vb)
        assert "B-mini" not in str(va)
    finally:
        await _cleanup([org_a, org_b], uids)
        await eng.dispose_engine()
