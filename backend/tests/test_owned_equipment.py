"""In-house / owned-equipment marginal costing (make-it-ourselves path).

The target customer makes parts in its OWN facility on machines it ALREADY
OWNS. When the org owns the machine, its capital purchase/amortization is a
SUNK cost, so the true marginal cost is material + energy + operator +
consumables — NOT the fully-loaded bureau rate. Declaring a process OWNED
(EstimateOptions.owned_processes, USER) costs its machine line at
machine_rate × (1 - machine_capital_frac).

These tests assert the structural guarantees (procedural meshes only, so they
always run in CI):
  * byte-identical when nothing is owned (the seam is a no-op by default)
  * owning a process removes EXACTLY the machine_capital_frac share of its
    machine line and lowers its unit cost; other processes are untouched
  * off-switch machine_capital_frac=0.0 => owned == fully-loaded, byte-identical
  * Σ(line_items) == unit_cost still holds on the owned path
  * provenance: USER owned declaration + DEFAULT (unvalidated) fraction;
    `validated` never flips
  * make-vs-buy: owning the make-now process is at least as cheap as not owning
"""

from __future__ import annotations

import trimesh

from src.costing import estimate_decision, EstimateOptions, report_to_dict
from src.costing.rates import RATE_CARD_V0, _resolve_process_token

# Reuse the engine harness + procedural meshes from the model test module.
from tests.test_costing_model import _analyze, _bulky_block, _est, _driver

CAP_FRAC = RATE_CARD_V0["global"]["machine_capital_frac"]


def _report(owned=frozenset(), overrides=None, qtys=(10, 1000)):
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=list(qtys), owned_processes=owned,
                           rate_overrides=dict(overrides or {}))
    return estimate_decision(result, mesh, feats, opts)


def _pt(process_value):
    pt = _resolve_process_token(process_value)
    assert pt is not None, process_value
    return pt


def test_default_frac_is_a_live_assumption():
    """The DEFAULT capital fraction is present and non-trivial (~0.35)."""
    assert 0.0 < CAP_FRAC < 1.0


def test_byte_identical_when_nothing_owned():
    """EstimateOptions(owned_processes=frozenset()) == today's estimate.

    Nothing owned => no owned_in_house flags, no owned driver, no
    machine_capital_frac assumption — the seam is a pure no-op.
    """
    base = report_to_dict(_report(owned=frozenset()))
    again = report_to_dict(_report(owned=frozenset()))
    assert base == again  # deterministic

    # structurally: none of the owned surfaces exist by default
    assert not any("owned_in_house" in e for e in base["estimates"])
    assert not any(d["name"] == "owned_in_house"
                   for e in base["estimates"] for d in e["drivers"])
    assert not any(a["name"] == "machine_capital_frac" for a in base["assumptions"])


def test_owning_a_process_removes_exactly_the_capital_share():
    """Owning a process cuts its machine line by EXACTLY machine_capital_frac
    of the machine portion, and lowers that process's unit cost."""
    base = _report(owned=frozenset())
    # a subtractive process has a large, clean machine line for the arithmetic
    procs = {e["process"] for e in base.estimates}
    proc = "cnc_3axis" if "cnc_3axis" in procs else sorted(procs)[0]
    owned = _report(owned=frozenset({_pt(proc)}))

    for q in (10, 1000):
        e_full = _est(base, proc, q)
        e_own = _est(owned, proc, q)
        m_full = e_full["line_items"]["machine"]
        m_own = e_own["line_items"]["machine"]
        # exact capital-fraction removal (within 4-decimal line-item rounding)
        assert abs(m_own - m_full * (1.0 - CAP_FRAC)) < 1e-3, (proc, q, m_full, m_own)
        assert m_own < m_full
        assert e_own["unit_cost_usd"] < e_full["unit_cost_usd"]


def test_other_processes_unchanged_when_one_is_owned():
    """Owning ONE process leaves every OTHER process's estimate byte-identical."""
    base = _report(owned=frozenset())
    procs = sorted({e["process"] for e in base.estimates})
    owned_proc = "cnc_3axis" if "cnc_3axis" in procs else procs[0]
    owned = _report(owned=frozenset({_pt(owned_proc)}))

    base_d = report_to_dict(base)["estimates"]
    own_d = report_to_dict(owned)["estimates"]
    other_base = [e for e in base_d if e["process"] != owned_proc]
    other_own = [e for e in own_d if e["process"] != owned_proc]
    assert other_base == other_own


def test_off_switch_is_byte_identical_even_when_owned():
    """machine_capital_frac=0.0 => owned == fully-loaded, byte-identical even
    when owned_processes is set."""
    procs = {e["process"] for e in _report().estimates}
    proc = "cnc_3axis" if "cnc_3axis" in procs else sorted(procs)[0]
    off = {"machine_capital_frac": 0.0}
    not_owned = report_to_dict(_report(owned=frozenset(), overrides=off))
    owned = report_to_dict(_report(owned=frozenset({_pt(proc)}), overrides=off))
    assert owned == not_owned


def test_line_items_sum_to_unit_cost_on_owned_path():
    """Σ(line_items) == unit_cost still holds when a process is owned (G3)."""
    procs = {e["process"] for e in _report().estimates}
    proc = "cnc_3axis" if "cnc_3axis" in procs else sorted(procs)[0]
    owned = _report(owned=frozenset({_pt(proc)}))
    for e in owned.estimates:
        s = sum(e["line_items"].values())
        assert abs(e["unit_cost_usd"] - round(s, 2)) < 0.02, (
            e["process"], e["quantity"], e["unit_cost_usd"], s)


def test_provenance_user_declaration_default_fraction_validated_false():
    """The owned line is USER (declaration); the fraction is a DEFAULT
    assumption tagged not-shop-validated; `validated` never flips."""
    base = _report(owned=frozenset())
    procs = {e["process"] for e in base.estimates}
    proc = "cnc_3axis" if "cnc_3axis" in procs else sorted(procs)[0]
    owned = _report(owned=frozenset({_pt(proc)}))

    e = _est(owned, proc, 10)
    assert e.get("owned_in_house") is True

    d = _driver(e, "owned_in_house")
    assert d is not None, "expected an owned_in_house driver"
    assert d["provenance"] == "USER"                        # the declaration is USER
    assert "not shop-validated" in d["source"]              # honest fraction caveat
    assert "capital" in d["source"].lower()

    # the fraction magnitude is surfaced as a DEFAULT assumption, unvalidated
    frac = next(a for a in report_to_dict(owned)["assumptions"]
                if a["name"] == "machine_capital_frac")
    assert frac["provenance"] == "DEFAULT"
    assert "not shop-validated" in frac["source"]

    # owning must never flip the confidence band to MEASURED/validated
    assert e["confidence"]["validated"] is False


def test_make_vs_buy_owning_makenow_is_at_least_as_cheap():
    """Owning the make-now process makes in-house at least as cheap as (usually
    cheaper than) not owning it — make-it-ourselves is first-class + cheaper."""
    base = _report(owned=frozenset())
    make_now = base.decision.make_now_process
    assert make_now is not None
    owned = _report(owned=frozenset({_pt(make_now)}))

    for q in (10, 1000):
        e_full = _est(base, make_now, q)
        e_own = _est(owned, make_now, q)
        assert e_own["unit_cost_usd"] <= e_full["unit_cost_usd"]
    # and strictly cheaper somewhere (the machine line is a real cost share)
    assert any(_est(owned, make_now, q)["unit_cost_usd"]
               < _est(base, make_now, q)["unit_cost_usd"] for q in (10, 1000))
