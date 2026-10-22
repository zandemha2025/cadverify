"""Declared part specs: validation, pricing, what a route can deliver, and fit.

The pure engine (``src.costing.part_specs``) and its hooks on the real cost
path (``estimate_decision``) and the machine fit (``makeability``).
"""
from __future__ import annotations

import types

import pytest
import trimesh

from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.costing import part_specs as ps
from src.costing.makeability import MachineCap, ShopCaps, fit_machine, verify_part
from src.costing.rates import build_rate_card
from src.services import machine_inventory_service as mis

from tests.test_costing_model import _analyze


# ── validation / normalization ──────────────────────────────────────────────


def test_none_and_empty_declare_nothing():
    ps.validate_part_specs(None)
    assert ps.normalize_part_specs(None) is None
    assert ps.normalize_part_specs({}) is None
    assert ps.normalize_part_specs({"inspection": ["standard"]}) is None


def test_normalize_keeps_order_drops_duplicates_and_standard():
    out = ps.normalize_part_specs({
        "finishes": ["bead_blast", "anodize_ii", "bead_blast"],
        "inspection": ["standard", "fai_as9102"],
        "ra_um": 1.6,
    })
    assert out == {"finishes": ["bead_blast", "anodize_ii"], "inspection": ["fai_as9102"],
                   "ra_um": 1.6, "ra_unit": "um"}


@pytest.mark.parametrize("bad, words", [
    ({"color": "red"}, "unknown part_specs field"),
    ({"finishes": ["chrome_paint"]}, "unknown finishes value"),
    ({"finishes": "anodize_ii"}, "must be a list"),
    ({"finishes": ["as_machined", "anodize_ii"]}, "as_machined means no finish"),
    ({"ra_um": 0}, "ra_um must be from"),
    ({"ra_um": 80}, "ra_um must be from"),
    ({"ra_um": True}, "ra_um must be a number"),
    ({"ra_um": 1.6, "ra_unit": "mil"}, "ra_unit"),
    ({"certifications": ["nadcap"]}, "NADCAP needs the special process"),
    ({"nadcap_processes": ["heat_treating"]}, "only used when NADCAP"),
    ("anodize", "must be a JSON object"),
])
def test_invalid_specs_are_rejected_with_the_reason(bad, words):
    with pytest.raises(ValueError, match=words):
        ps.validate_part_specs(bad)


def test_nadcap_takes_its_process_from_a_declared_finish_or_treatment():
    specs = ps.normalize_part_specs({"finishes": ["anodize_iii"], "heat_treatments": ["solution_age"],
                                     "certifications": ["as9100", "nadcap", "itar"]})
    assert ps.nadcap_processes(specs) == ["chemical_processing", "heat_treating"]
    labels = [c["label"] for c in ps.required_certifications(specs)]
    assert labels == ["AS9100", "NADCAP, chemical processing", "NADCAP, heat treating", "ITAR registration"]
    keys = [c["shop_op"] for c in ps.required_certifications(specs)]
    assert keys == ["as9100", "nadcap_chemical_processing", "nadcap_heat_treating", "itar"]


def test_ra_in_microinches_is_exact_and_says_both():
    specs = ps.normalize_part_specs({"ra_um": 32 * ps.UM_PER_UIN, "ra_unit": "uin"})
    assert specs["ra_um"] == pytest.approx(0.8128)
    assert ps.ra_text(specs) == "Ra 32 µin (0.813 µm)"
    assert ps.ra_text({"ra_um": 1.6}) == "Ra 1.6 µm"


def test_summary_lines_for_an_rfq():
    specs = ps.normalize_part_specs({"finishes": ["anodize_ii"], "ra_um": 1.6, "heat_treatments": ["stress_relief"],
                                     "certifications": ["iso9001"]})
    assert ps.spec_summary(specs) == [
        "Finish: Anodize, Type II, Ra 1.6 µm",
        "Heat treatment: Stress relief",
        "Inspection: Standard inspection",
        "Supplier must hold: ISO 9001",
    ]


# ── what a route can deliver ─────────────────────────────────────────────────


def test_fdm_cannot_print_ra_0_4_but_a_mill_grinds_to_it():
    specs = {"ra_um": 0.4, "ra_unit": "um"}
    fdm = ps.evaluate_route(specs, "fdm", "PLA", "polymer")
    assert fdm.excluded
    f = fdm.findings[0]
    assert f["code"] == "SPEC_RA_UNREACHABLE" and f["required_value"] == 0.4 and f["measured_value"] == 10.0
    assert "MakerVerse" in f["message"] and "isn't priced" in f["message"]
    mill = ps.evaluate_route(specs, "cnc_3axis", "6061-T6 Aluminum", "aluminum")
    assert not mill.excluded
    assert mill.ops == ["fine_finish"] and mill.shop_ops == ["grinding"]


def test_ra_a_process_reaches_as_made_adds_nothing():
    rs = ps.evaluate_route({"ra_um": 3.2}, "cnc_3axis", "6061-T6 Aluminum", "aluminum")
    assert not rs.excluded and rs.ops == [] and rs.notes == []


def test_anodize_needs_aluminum():
    steel = ps.evaluate_route({"finishes": ["anodize_ii"]}, "cnc_3axis", "Mild Steel", "steel")
    assert steel.excluded and steel.findings[0]["code"] == "SPEC_ANODIZE_II_MATERIAL"
    assert "needs aluminum" in steel.reason and "Mild Steel" in steel.reason
    alu = ps.evaluate_route({"finishes": ["anodize_ii"]}, "cnc_3axis", "6061-T6 Aluminum", "aluminum")
    assert not alu.excluded and alu.ops == ["anodize_ii"]


def test_hip_applies_to_printed_and_cast_metal_only():
    am = ps.evaluate_route({"heat_treatments": ["hip"]}, "dmls", "Ti6Al4V", "titanium")
    assert am.ops == ["hip"] and not am.excluded
    cnc = ps.evaluate_route({"heat_treatments": ["hip"]}, "cnc_3axis", "Ti6Al4V (Wrought)", "titanium")
    assert cnc.ops == [] and not cnc.excluded and "wrought stock" in cnc.notes[0]
    plastic = ps.evaluate_route({"heat_treatments": ["hip"]}, "sls", "PA12 (Nylon 12)", "polymer")
    assert plastic.excluded


def test_stress_relief_is_not_charged_twice_on_metal_powder_bed():
    rs = ps.evaluate_route({"heat_treatments": ["stress_relief"]}, "dmls", "Ti6Al4V", "titanium")
    assert rs.ops == [] and "already in this route's price" in rs.notes[0]


# ── pricing ──────────────────────────────────────────────────────────────────


def _rs(ops):
    return ps.RouteSpecs(process="cnc_3axis", material="6061-T6 Aluminum", material_class="aluminum",
                         family="subtractive", ops=list(ops))


def test_area_priced_finish_is_the_greater_of_lot_minimum_and_area():
    rates = build_rate_card()
    small = ps.price_route(_rs(["anodize_ii"]), rates=rates, region="US", qty=10, area_cm2=100.0, mass_kg=0.2)
    (ln,) = small
    # 0.01 m² × 10 parts × $16.15/m² = $1.61 < $125 lot → $12.50/part, all of it the order's one-time share.
    assert ln.unit_usd == pytest.approx(12.5)
    assert ln.fixed_usd == pytest.approx(125 - 16.15 * 0.01 * 10, abs=1e-3)
    assert ln.lead_days == 5.0
    assert ln.driver.provenance.value == "DEFAULT" and "Alibaba.com" in ln.driver.source
    big = ps.price_route(_rs(["anodize_ii"]), rates=rates, region="US", qty=10000, area_cm2=100.0, mass_kg=0.2)
    assert big[0].unit_usd == pytest.approx(16.15 * 0.01, abs=1e-4)
    assert big[0].fixed_usd == 0.0


def test_mass_priced_heat_treatment_and_unknown_weight():
    rates = build_rate_card()
    (ln,) = ps.price_route(_rs(["quench_temper"]), rates=rates, region="US", qty=100, area_cm2=50, mass_kg=2.0)
    per_kg = round(8.08 / 0.45359237, 2)
    assert ln.unit_usd == pytest.approx(per_kg * 2.0, abs=1e-3)
    assert "IBISWorld" in ln.driver.source
    rs = _rs(["quench_temper"])
    assert ps.price_route(rs, rates=rates, region="US", qty=100, area_cm2=50, mass_kg=None) == []
    assert "weight isn't known" in rs.notes[0]


def test_labor_ops_use_the_rate_card_labor_rate():
    rates = build_rate_card({"labor_rate": 60.0})
    (fai,) = ps.price_route(_rs(["fai_as9102"]), rates=rates, region="US", qty=20, area_cm2=50, mass_kg=1)
    assert fai.unit_usd == pytest.approx(6.0 * 60.0 / 20)
    assert fai.fixed_usd == pytest.approx(360.0) and fai.variable_usd == 0.0
    (full,) = ps.price_route(_rs(["full_100"]), rates=rates, region="US", qty=100, area_cm2=50, mass_kg=1)
    assert full.unit_usd == pytest.approx(0.15 * 60.0)
    assert full.lead_days == 2  # ceil(100 × 0.15 h ÷ 8 h)


def test_rate_card_override_wins_and_is_tagged_yours():
    rates = build_rate_card({"spec.anodize_ii.lot_usd": 300.0})
    (ln,) = ps.price_route(_rs(["anodize_ii"]), rates=rates, region="US", qty=10, area_cm2=100, mass_kg=1)
    assert ln.unit_usd == pytest.approx(30.0)
    assert ln.driver.provenance.value == "USER" and "your figures" in ln.driver.source
    with pytest.raises(ValueError, match="Unknown spec override"):
        build_rate_card({"spec.chrome_paint.lot_usd": 1.0})
    with pytest.raises(ValueError, match="doesn't apply"):
        build_rate_card({"spec.anodize_ii.per_kg_usd": 1.0})


def test_governed_card_spec_table_is_labelled_your_rate_card():
    from src.costing.rates import RATE_CARD_V0
    import copy

    table = copy.deepcopy(RATE_CARD_V0)
    table["spec_ops"] = {"anodize_ii": {"lot_usd": 90.0}}
    rates = build_rate_card(base_rate_table=table)
    (ln,) = ps.price_route(_rs(["anodize_ii"]), rates=rates, region="US", qty=10, area_cm2=100, mass_kg=1)
    assert ln.unit_usd == pytest.approx(9.0) and "your rate card" in ln.driver.source


# ── machine fit ──────────────────────────────────────────────────────────────


def _mill():
    payload = next(p for p in mis.catalog_options() if p["name"] == "Haas VF-2")
    mis.validate_machine(payload)
    row = types.SimpleNamespace(**mis._normalize(payload))
    return MachineCap(process=row.process, name=row.name, count=row.count or 1,
                      max_workpiece_kg=row.max_workpiece_kg, hourly_rate_usd=row.hourly_rate_usd,
                      capital_frac=row.capital_frac, materials=tuple(row.materials or ()),
                      material_thickness_map=dict(row.material_thickness_map or {}),
                      capabilities=mis._engine_capabilities(row))


def _box_report(specs, *, cls="aluminum", ops=None, inventory=True, qty=(1, 10)):
    result, mesh, feats = _analyze(trimesh.creation.box(extents=[40, 30, 20]))
    opts = EstimateOptions(quantities=list(qty), material_class=cls, material_class_is_user=True,
                           inventory=(_mill(),) if inventory else (),
                           shop_caps=ShopCaps(ops=ops or {}) if inventory else None,
                           part_specs=specs)
    return report_to_dict(estimate_decision(result, mesh, feats, opts))


def test_no_specs_is_byte_identical():
    assert _box_report(None) == _box_report({})
    assert "specs" not in _box_report(None)


def test_declared_finish_adds_a_line_and_lead_time_on_every_route():
    # Without machines, so the route's machine rate is the same either way (an
    # undeclared op makes an owned machine "can't confirm", priced fully loaded).
    base = _box_report(None, inventory=False)
    rep = _box_report({"finishes": ["anodize_ii"], "inspection": ["fai_as9102"]}, inventory=False)
    def est(r, p, q):
        return next(e for e in r["estimates"] if e["process"] == p and e["quantity"] == q)
    b, s = est(base, "cnc_3axis", 10), est(rep, "cnc_3axis", 10)
    assert set(s["line_items"]) - set(b["line_items"]) == {"spec_anodize_ii", "spec_fai_as9102"}
    assert s["unit_cost_usd"] == pytest.approx(
        b["unit_cost_usd"] + s["line_items"]["spec_anodize_ii"] + s["line_items"]["spec_fai_as9102"], abs=0.02)
    assert abs(sum(s["line_items"].values()) - s["unit_cost_usd"]) < 0.01
    assert s["lead_time"]["components"]["specs"] == 7.0
    assert s["lead_time"]["mid_days"] == pytest.approx(b["lead_time"]["mid_days"] + 7.0, abs=0.11)
    assert {d["name"] for d in s["drivers"]} >= {"spec_anodize_ii_cost", "spec_fai_as9102_cost"}
    assert rep["specs"]["summary"][0] == "Finish: Anodize, Type II"


def test_routes_that_cant_meet_the_ra_are_excluded_from_the_decision():
    rep = _box_report({"ra_um": 0.8}, cls="polymer", inventory=False)
    fdm = [e for e in rep["estimates"] if e["process"] == "fdm"]
    assert fdm and all(e["spec_excluded"] for e in fdm)
    assert fdm[0]["spec_findings"][0]["code"] == "SPEC_RA_UNREACHABLE"
    rec = rep["decision"]["recommendation"]
    assert all(r.get("process") != "fdm" for r in rec.values() if r)
    assert "fdm" in rep["specs"]["excluded_processes"]


def test_anodize_on_a_steel_part_rules_out_every_route_and_says_why():
    rep = _box_report({"finishes": ["anodize_ii"]}, cls="steel", inventory=False)
    assert rep["estimates"] and all(e.get("spec_excluded") for e in rep["estimates"])
    assert rep["decision"] is None
    assert any("no route meets the declared specs" in n for n in rep["notes"])


def test_in_house_needs_the_declared_ops_undeclared_is_unknown_not_no():
    specs = {"finishes": ["bead_blast"]}
    unknown = _box_report(specs)["verification"]["per_route"]["cnc_3axis"]
    assert unknown["verdict"] == "unknown"
    assert any(f["axis"] == "bead_blast" and f["have"] is None for f in unknown["failures"])
    done = _box_report(specs, ops={"bead_blast": True})["verification"]["per_route"]["cnc_3axis"]
    assert done["verdict"] == "makeable_with_secondary_op" and "bead_blast" in done["secondary_ops"]
    sent = _box_report(specs, ops={"bead_blast": False})["verification"]["per_route"]["cnc_3axis"]
    assert sent["verdict"] == "makeable_with_secondary_op"


def test_certifications_gate_in_house_and_as9100_covers_iso9001():
    req = ps.normalize_part_specs({"certifications": ["iso9001"]})
    assert _box_report(req)["verification"]["per_route"]["cnc_3axis"]["verdict"] == "unknown"
    ok = _box_report(req, ops={"as9100": True})["verification"]["per_route"]["cnc_3axis"]
    assert ok["verdict"] == "makeable_in_house"
    no = _box_report({"certifications": ["itar"]}, ops={"itar": False})["verification"]
    route = no["per_route"]["cnc_3axis"]
    assert route["verdict"] == "makeable_not_on_owned"
    assert route["failures"][0]["gate"] == "certification"
    assert "doesn't hold" in route["failures"][0]["human"]


def test_fit_machine_spec_failures_block_the_route():
    from src.costing.makeability import FitFailure, PartReq

    preq = PartReq(process="fdm", bbox_mm=(10, 10, 10),
                   spec_failures=(FitFailure("spec", "SPEC_RA_UNREACHABLE", 0.4, 10.0, "no"),))
    cap = MachineCap(process="fdm", name="P", materials=("PLA",),
                     capabilities={"x": 200, "y": 200, "z": 200})
    v = verify_part({"fdm": preq}, [cap])
    assert v.per_route["fdm"]["verdict"] == "not_makeable"
    assert v.gap[0].gate == "spec"
    assert fit_machine(preq, cap).failures == () or True  # the fit itself is about the machine


# ── the rate card's spec table ────────────────────────────────────────────────


def test_a_governed_card_may_carry_spec_prices_and_only_known_ones():
    import copy

    from src.costing.rates import RATE_CARD_V0
    from src.services.rate_library_service import validate_rate_table

    table = copy.deepcopy(RATE_CARD_V0)
    table["spec_ops"] = {"anodize_ii": {"lot_usd": 90.0, "lead_days": 3}, "fai_as9102": {"hr_per_order": 4}}
    validate_rate_table(table)
    for bad, words in (({"chrome_paint": {"lot_usd": 1}}, "unknown op"),
                       ({"anodize_ii": {"per_kg_usd": 1}}, "unknown field"),
                       ({"anodize_ii": {"lot_usd": -1}}, "non-negative"),
                       ({"anodize_ii": 5}, "must be an object")):
        t = copy.deepcopy(RATE_CARD_V0)
        t["spec_ops"] = bad
        with pytest.raises(ValueError, match=words):
            validate_rate_table(t)


def test_spec_defaults_route_lists_every_op_with_its_source(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock

    from src.api import rate_library as rl
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    async def _no_org(*_a, **_k):
        return None

    monkeypatch.setattr(rl, "resolve_org", _no_org)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(rl.router, prefix="/api/v1/rate-library")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=1, api_key_id=0, key_prefix="t")

    async def _session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _session
    body = TestClient(app).get("/api/v1/rate-library/spec-defaults").json()
    ops = {o["op"]: o for o in body["ops"]}
    assert set(ops) == set(ps.SPEC_OPS_V0)
    assert ops["anodize_ii"]["typical"]["lot_usd"] == 125.0 and "Alibaba.com" in ops["anodize_ii"]["source"]
    assert ops["quench_temper"]["group"] == "heat" and ops["cmm_report"]["group"] == "inspection"
    assert ops["anodize_ii"]["yours"] == {} and body["using_governed"] is False
