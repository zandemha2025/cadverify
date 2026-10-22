"""A published rate card shows everywhere (round 11, ce-10, ce-16, me-05).

Priyanka Shah published rate card v1 (labor $35/h -> $58/h) and re-costed the
60 x 40 x 20 mm steel pocket block. Her hand numbers at 100 off, v1:

    labor        0.5 h x $58               = $29.00
    setup        0.75 h x $58 / 100        = $0.435
    programming  2 h x $58 / 100           = $1.16
    inspection   (0.5 / 100 + 0.03) h x $58 = 0.035 h x $58 = $2.03
    machine      0.209245 h x $75          = $15.69   (unchanged: v1 kept $75/h)
    -> $49.63 a part, "exactly my hand calculation"

The price was right; every line was tagged "Typical", the summary said "0 of 8
from your file or shop" and the lens said "Add your labor rate". These tests hold
the lines that use her $58 to "your rates v1", and every saved record to the card
it was priced at.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.analysis.models import ProcessType as PT
from src.costing import cost_model
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.rates import RATE_CARD_V0, build_rate_card
from src.costing.routing import select_material
from src.services import rate_card_basis as rcb

CYCLE_HR = 0.209245  # the engine's cycle on her file (her CSV: machine 15.6934 = 0.209245 h x $75)


def _pocket_block():
    return GeoDrivers(
        volume_cm3=37.9, surface_area_cm2=106.92, bbox_mm=(20.0, 40.0, 60.0),
        bbox_volume_cm3=48.0, hull_volume_cm3=48.0, nominal_wall_mm=7.09, face_count=179296,
        max_bbox_mm=60.0, is_valid=True, rotational=False, rot_axis_len_mm=60.0,
        rot_cross_dia_mm=44.7, billet_bbox_mm=(20.0, 40.0, 60.0), billet_basis="oriented candidate")


def _v1_payload(labor=58.0):
    p = copy.deepcopy(RATE_CARD_V0)
    p["global"]["labor_rate"] = labor
    return p


def _result_for(est, material_class="steel"):
    """The record's shape for one estimate (estimate._serialize's driver fields)."""
    return {
        "material_class": material_class,
        "estimates": [{
            "process": est.process, "material": est.material, "quantity": est.quantity,
            "unit_cost_usd": round(est.unit_cost_usd, 2), "line_items": est.line_items,
            "drivers": [{"name": d.name, "value": d.value, "unit": d.unit,
                         "provenance": d.provenance.value, "source": d.source,
                         "error_band_pct": d.error_band_pct} for d in est.drivers],
        }],
        "assumptions": [
            {"name": "labor_rate", "value": 58.0, "unit": "$/hr", "provenance": "DEFAULT",
             "source": "loaded shop-floor labor"},
            {"name": "overhead", "value": 0.0, "unit": "frac", "provenance": "DEFAULT",
             "source": "indirect burden"},
        ],
    }


@pytest.fixture()
def v1_block(monkeypatch):
    monkeypatch.setattr(cost_model, "_cnc_cycle",
                        lambda process, drivers, cls, rates: (CYCLE_HR, 0.1782, "her cycle"))
    rates = build_rate_card(base_rate_table=_v1_payload())
    mat = select_material(PT.CNC_3AXIS, "steel", rates)
    return cost_breakdown(PT.CNC_3AXIS, _pocket_block(), mat, "steel", 100, rates, "US")


def _d(result, name):
    return next(d for d in result["estimates"][0]["drivers"] if d["name"] == name)


def test_changed_keys_are_only_what_the_org_changed():
    p = _v1_payload()
    p["process"][PT.CNC_3AXIS]["machine_rate"] = 82
    p["material_prices"] = {"Mild Steel": 2.4}
    assert rcb.changed_keys(p) == {"labor_rate": 58.0, "machine_rate.CNC_3AXIS": 82.0,
                                   "material_price.Mild Steel": 2.4}
    # a card copied from the typical table unchanged is still typical, line by line
    assert rcb.changed_keys(copy.deepcopy(RATE_CARD_V0)) == {}
    # the stored payload is JSON: process keys are the enum values ("cnc_3axis")
    import json
    stored = json.loads(json.dumps(p, default=str))
    assert rcb.changed_keys(stored)["machine_rate.CNC_3AXIS"] == 82.0


def test_v1_lines_using_her_labor_rate_are_tagged_your_rates_v1(v1_block):
    e = v1_block
    # her arithmetic, line by line, at 100 off and $58/h
    assert round(e.line_items["labor"], 2) == round(0.5 * 58, 2) == 29.00
    labor = {d.name: d.value for d in e.drivers}
    assert round(labor["setup_cost"], 3) == round(0.75 * 58 / 100, 3) == 0.435
    assert round(labor["nre_cost"], 2) == round(2 * 58 / 100, 2) == 1.16
    assert round(labor["inspection_cost"], 2) == round((0.5 / 100 + 0.03) * 58, 2) == 2.03
    assert round(labor["machine_cost"], 2) == round(CYCLE_HR * 75, 2) == 15.69
    assert round(e.unit_cost_usd, 2) == 49.63

    before = _result_for(e)
    typical_before = sum(1 for d in before["estimates"][0]["drivers"] if d["provenance"] == "DEFAULT")
    out = rcb.apply_rate_card(before, 1, _v1_payload())

    for name in ("labor_cost", "setup_cost", "nre_cost", "inspection_cost"):
        d = _d(out, name)
        assert d["provenance"] == "SHOP", name           # was DEFAULT -> "Typical" on screen
        assert d["rate_card"] == 1
        assert "$58/h labor rate from your rates v1" in d["source"]
    # her v1 kept $75/h on the 3-axis: the machine line is still a typical rate
    assert _d(out, "machine_cost")["provenance"] == "DEFAULT"
    assert "rate_card" not in _d(out, "machine_cost")
    # "N of M from your file or shop" goes up by the four labor lines
    typical_after = sum(1 for d in out["estimates"][0]["drivers"] if d["provenance"] == "DEFAULT")
    assert typical_before - typical_after == 4
    # no number moves
    assert [d["value"] for d in out["estimates"][0]["drivers"]] == \
        [d["value"] for d in before["estimates"][0]["drivers"]]
    assert out["estimates"][0]["unit_cost_usd"] == 49.63
    # the assumption row for the labor rate is hers; overhead she didn't change stays typical
    a = {x["name"]: x for x in out["assumptions"]}
    assert a["labor_rate"]["provenance"] == "SHOP" and a["labor_rate"]["rate_card"] == 1
    assert a["overhead"]["provenance"] == "DEFAULT"
    # the record says which card priced it
    assert out["rate_card"] == {"version": 1, "changed": {"labor_rate": 58.0},
                                "source": "your published rate card v1"}
    # the input is never mutated
    assert _d(before, "labor_cost")["provenance"] == "DEFAULT"


def test_a_machine_rate_or_material_price_in_the_card_tags_its_line(v1_block):
    p = _v1_payload()
    p["process"]["cnc_3axis"] = dict(p["process"][PT.CNC_3AXIS], machine_rate=82)
    p["material_prices"] = {"Mild Steel": 2.4}
    out = rcb.apply_rate_card(_result_for(v1_block), 2, p)
    m = _d(out, "machine_cost")
    assert m["provenance"] == "SHOP" and "$82/h machine rate from your rates v2" in m["source"]
    mat = _d(out, "material_cost")
    assert mat["provenance"] == "SHOP" and "$2.4/kg Mild Steel from your rates v2" in mat["source"]


def test_a_user_override_for_this_quote_keeps_its_tag(v1_block):
    r = _result_for(v1_block)
    _d(r, "labor_cost")["provenance"] = "USER"
    out = rcb.apply_rate_card(r, 1, _v1_payload())
    assert _d(out, "labor_cost")["provenance"] == "USER"
    assert "rate_card" not in _d(out, "labor_cost")


def test_typical_table_leaves_the_record_alone(v1_block):
    r = _result_for(v1_block)
    assert rcb.apply_rate_card(r, None, None) is r


# ── which card a saved record was priced at ───────────────────────────────────

T_PUBLISH = datetime(2026, 10, 22, 15, 59, tzinfo=timezone.utc)


def _row(version, status="published", ef=T_PUBLISH, et=None):
    return SimpleNamespace(version=version, status=status, effective_from=ef, effective_to=et)


def test_record_before_v1_reads_priced_at_v0_your_rates_are_v1():
    """ce-10: "the part shows the v0 price and says clearly ... v1 is in use, re-cost"."""
    rows = [_row(1)]
    made = T_PUBLISH - timedelta(minutes=25)  # her 15:35 check, before the 15:59 publish
    b = rcb.basis({"estimates": []}, made, rows, enabled=True, now=T_PUBLISH + timedelta(minutes=20))
    assert b == {"priced": 0, "current": 1, "out_of_date": True,
                 "text": "Priced at rates v0; your rates are v1."}


def test_record_re_costed_at_v1_is_current():
    rows = [_row(1)]
    made = T_PUBLISH + timedelta(minutes=22)
    b = rcb.basis({"rate_card": {"version": 1}}, made, rows, enabled=True, now=made)
    assert b["priced"] == 1 and b["current"] == 1 and b["out_of_date"] is False
    assert b["text"] == "Priced at your rates v1."
    # without a stamp (an older record), the card in effect when it was made
    assert rcb.basis({}, made, rows, enabled=True, now=made)["priced"] == 1


def test_superseded_and_archived_cards_keep_their_window():
    t2 = T_PUBLISH + timedelta(days=3)
    rows = [_row(1, status="archived", et=t2), _row(3, ef=t2)]
    assert rcb.in_effect(rows, T_PUBLISH + timedelta(days=1)) == 1
    assert rcb.in_effect(rows, t2 + timedelta(seconds=1)) == 3
    assert rcb.in_effect(rows, T_PUBLISH - timedelta(seconds=1)) == 0
    # a draft is never in effect
    assert rcb.in_effect([_row(2, status="draft")], t2) == 0
    b = rcb.basis({}, T_PUBLISH + timedelta(days=1), rows, enabled=True, now=t2 + timedelta(hours=1))
    assert b["text"] == "Priced at rates v1; your rates are v3."


def test_flag_off_nothing_is_out_of_date_by_rates():
    b = rcb.basis({}, T_PUBLISH - timedelta(days=1), [_row(1)], enabled=False,
                  now=T_PUBLISH + timedelta(days=1))
    assert b["current"] == 0 and b["out_of_date"] is False
    assert b["text"] == "Priced at typical rates (v0)."


@pytest.mark.asyncio
async def test_saved_records_read_their_card_from_the_org_timeline(monkeypatch):
    """The records page, part page and exports read ``rates`` off ``basis_for``:
    one query over the org's real ``rate_card_versions`` rows."""
    from sqlalchemy import select

    from src.db.models import ApiKey, CostDecision, Organization, RateCardVersion, User
    from src.services import rate_library_service
    from tests.sqlite_tables import sqlite_sessionmaker

    monkeypatch.setenv("RATE_LIBRARY_ENABLED", "1")
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=1)
    engine, maker = await sqlite_sessionmaker(Organization, User, ApiKey, RateCardVersion, CostDecision)
    try:
        async with maker() as s:
            s.add_all([Organization(id="ORG-NFP", name="Northfield Pumps", slug="nfp"),
                       Organization(id="ORG-OTHER", name="Other", slug="other"),
                       User(id=7, email="p@nfp.example", email_lower="p@nfp.example",
                            role="analyst", auth_provider="password")])
            await s.flush()
            s.add_all([
                RateCardVersion(org_id="ORG-NFP", version=1, name="v1", status="published",
                                payload=_v1_payload(), effective_from=published),
                RateCardVersion(org_id="ORG-NFP", version=2, name="draft", status="draft",
                                payload=_v1_payload(61.0)),
                # another org's card never reaches this org's records
                RateCardVersion(org_id="ORG-OTHER", version=5, name="x", status="published",
                                payload=_v1_payload(99.0), effective_from=published - timedelta(days=9)),
            ])
            for i, (made, rj) in enumerate([(published - timedelta(minutes=24), {}),
                                            (published + timedelta(minutes=22),
                                             {"rate_card": {"version": 1}})]):
                s.add(CostDecision(user_id=7, org_id="ORG-NFP", mesh_hash="pocket", params_hash=f"p{i}",
                                   engine_version="t", filename="pocket-block.step", file_type="step",
                                   result_json=rj, approval_status="unreviewed", is_public=False,
                                   created_at=made))
            await s.commit()
        async with maker() as s:
            ds = (await s.execute(select(CostDecision).order_by(CostDecision.created_at))).scalars().all()
            out = await rcb.basis_for(s, "ORG-NFP", ds)
        old, new = (out[d.ulid] for d in ds)
    finally:
        await engine.dispose()
    assert old["text"] == "Priced at rates v0; your rates are v1." and old["out_of_date"] is True
    assert new == {"priced": 1, "current": 1, "out_of_date": False, "text": "Priced at your rates v1."}
    rate_library_service.invalidate("ORG-NFP")


def test_a_draft_lists_every_value_it_changes_for_review():
    """ce-13: a rate-card draft can change machine rates, overhead, margin and material
    prices, and the review shows each change, not only labor."""
    from src.services.rate_library_service import changes_against

    p = _v1_payload()
    p["global"]["overhead"] = 0.15
    p["global"]["margin"] = 0.10
    p["process"][PT.CNC_3AXIS]["machine_rate"] = 82
    p["material_prices"] = {"Mild Steel": 2.4}
    rows = {c["path"]: (c["from"], c["to"]) for c in changes_against(None, p)}
    assert rows == {
        "global.labor_rate": (35.0, 58.0),
        "global.overhead": (0.0, 0.15),
        "global.margin": (0.0, 0.10),
        "process.cnc_3axis.machine_rate": (75, 82),
        "material_prices.Mild Steel": (None, 2.4),
    }
    # against a published card: only what differs from it
    assert {c["path"] for c in changes_against(_v1_payload(), p)} == {
        "global.overhead", "global.margin", "process.cnc_3axis.machine_rate", "material_prices.Mild Steel"}
