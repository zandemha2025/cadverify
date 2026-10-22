"""Part specs on outbound copies: what an RFQ package and a share link carry.

The buyer's declared specs (finishes and Ra, heat treatment, inspection, the
certifications the supplier must hold) are allowed outbound fields; the price
lines and lead days they add travel with their typical source; a spec price the
shop typed stays hidden like any other shop rate; nothing else rides along.
"""
from __future__ import annotations

import csv
import io
import json
from types import SimpleNamespace

import pytest
import trimesh

from src.services import outbound
from src.services import rfq_package_service as rfq

SPECS = {"finishes": ["anodize_ii"], "ra_um": 1.6, "ra_unit": "um", "heat_treatments": ["stress_relief"],
         "inspection": ["fai_as9102"], "certifications": ["as9100", "itar", "nadcap"]}


@pytest.fixture(scope="module")
def spec_record():
    from src.costing import EstimateOptions, estimate_decision, report_to_dict
    from tests.test_costing_model import _analyze

    result, mesh, feats = _analyze(trimesh.creation.box(extents=[40, 30, 20]))
    opts = EstimateOptions(quantities=[10, 100], material_class="aluminum", material_class_is_user=True,
                           part_specs=SPECS, rate_overrides={"spec.anodize_ii.lot_usd": 211.37})
    return json.loads(json.dumps(report_to_dict(estimate_decision(result, mesh, feats, opts)), default=str))


def _est(rec, process, qty):
    return next(e for e in rec["estimates"] if e["process"] == process and e["quantity"] == qty)


def test_spec_lines_and_block_leave_and_a_typed_spec_price_stays_hidden(spec_record):
    out = outbound.cost_record(spec_record)
    e = _est(out, "cnc_3axis", 10)
    assert {"spec_anodize_ii", "spec_stress_relief", "spec_fai_as9102"} <= set(e["line_items"])
    drivers = {d["name"]: d for d in e["drivers"]}
    # Typical values with their source travel, including the per-kg heat-treat figure.
    heat = drivers["spec_stress_relief_cost"]
    assert heat["provenance"] == "DEFAULT" and "IBISWorld" in heat["source"] and "/kg" in heat["source"]
    assert "AS9102 report" in drivers["spec_fai_as9102_cost"]["source"]
    # The anodize lot minimum the shop typed is the shop's: its text and value don't leave.
    anod = drivers["spec_anodize_ii_cost"]
    assert "211.37" not in json.dumps(anod)
    assert e["lead_time"]["components"]["specs"] == 10.0
    block = out["specs"]
    assert block["declared"] == {k: SPECS[k] for k in SPECS}
    assert block["supplier_must_hold"] == ["AS9100", "ITAR registration",
                                           "NADCAP, chemical processing", "NADCAP, heat treating"]
    assert block["summary"][0] == "Finish: Anodize, Type II, Ra 1.6 µm"
    assert "211.37" not in json.dumps(out)


def test_spec_excluded_routes_say_why_outside_too():
    from src.costing import EstimateOptions, estimate_decision, report_to_dict
    from tests.test_costing_model import _analyze

    result, mesh, feats = _analyze(trimesh.creation.box(extents=[40, 30, 20]))
    rep = report_to_dict(estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[10], material_class="polymer", part_specs={"ra_um": 0.8})))
    out = outbound.cost_record(json.loads(json.dumps(rep, default=str)))
    fdm = next(e for e in out["estimates"] if e["process"] == "fdm")
    assert fdm["spec_excluded"] is True and "MakerVerse" in fdm["spec_exclusion_reason"]
    assert fdm["spec_findings"][0]["code"] == "SPEC_RA_UNREACHABLE"
    assert set(fdm["spec_findings"][0]) <= set(outbound._ISSUE_KEYS) | {"citation"}


def test_rfq_item_carries_the_buyer_specs_and_drops_unknown_keys():
    item = {"decision": {"id": "01X", "filename": "bracket.step"}, "cost_decision": {},
            "part_context": {"program": "Rail", "part_specs": {**SPECS, "shop_secret": "Bay-7"},
                             "service_environment": None}}
    out = outbound.rfq_item(item)
    ctx = out["part_context"]
    assert ctx["part_specs"] == SPECS
    assert "shop_secret" not in json.dumps(out)
    assert ctx["supplier_must_hold"][0] == "AS9100"
    assert ctx["spec_summary"][-1].startswith("Supplier must hold: AS9100")
    # No specs: no keys.
    bare = outbound.rfq_item({"decision": {}, "cost_decision": {}, "part_context": {"program": "Rail"}})
    assert "part_specs" not in bare["part_context"]


def test_supplier_brief_and_line_items_name_what_the_supplier_must_hold():
    items = [outbound.rfq_item({"decision": {"id": "01X", "filename": "bracket.step", "approval_status": "approved"},
                                "cost_decision": {}, "part_context": {"part_specs": SPECS}})]
    package = SimpleNamespace(title="RFQ", supplier_name=None, item_count=1, approved_count=1, stale_count=0,
                              unvalidated_count=0, raw_cad_included=False, live_supplier_send=False,
                              metadata_json={}, warnings_json=[])
    md = rfq._supplier_brief(package, items)
    assert "## Part specs" in md and "### bracket.step" in md
    assert "The supplier must hold: AS9100, ITAR registration, NADCAP, chemical processing, NADCAP, heat treating." in md
    assert "- Inspection: First article inspection, AS9102" in md
    html = rfq._supplier_brief_html(package, items)
    assert "Part specs" in html and "ITAR registration" in html
    rows = list(csv.reader(io.StringIO(rfq._line_items_csv(items))))
    head = rows[0]
    assert head[-2:] == ["part_specs", "supplier_must_hold"]
    assert "Heat treatment: Stress relief" in rows[1][head.index("part_specs")]
    assert rows[1][head.index("supplier_must_hold")].startswith("AS9100; ITAR registration")
    # A package without specs reads as before.
    assert "## Part specs" not in rfq._supplier_brief(package, [])
