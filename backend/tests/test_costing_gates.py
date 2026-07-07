"""Gate tests G1-G7 on the repo's real automotive parts (spec §12).

The real STL set is the ECU/throttle-body batch. Point CADVERIFY_PARTS_DIR at
the extracted folder; the module skips cleanly if it is absent so CI without the
parts still passes the procedural model tests.

G6 validation anchor (positioning, not a precision claim — strategy §2):
    A ~67 cm³ nylon SLS bracket at low volume from a service bureau commonly
    runs ~$80-180/unit. V0's SLS estimate for the ECU Firewall Mount
    (~$126/unit) falls inside that band. This is the stated anchor; V0 does NOT
    claim absolute should-cost accuracy (±40-60%).
"""

from __future__ import annotations

import os

import pytest

from src.costing import estimate_decision, EstimateOptions
from src.costing.cli import _run_engine
from src.costing.harness import ensure_fixture_parts_dir

PARTS_DIR = ensure_fixture_parts_dir()

ECU = "1090523_b8dd5bfe-0a71-405c-906b-aa8dc51a6c30_EK_0BD1_ECU_Firewall_mount.stl"
TBA = "printables_122552_ThrottleBodyAdapter.stl"
MAF = ("655044_0b409a7e-0e9d-424a-81ae-5261cd5f4181_MITSUBISHI_LANCER_1993-"
       "MAF_Sensor_Adapter_for_High_Flow_Air_filetr.stl")
RING = "printables_122552_ThrottleBodyRingOuter.stl"

pytestmark = pytest.mark.skipif(
    not (
        os.path.isdir(PARTS_DIR)
        and all(
            os.path.isfile(os.path.join(PARTS_DIR, fname))
            for fname in (ECU, TBA, MAF, RING)
        )
    ),
    reason=f"real parts fixture batch not present: {PARTS_DIR}",
)


def _decide(fname, **opt_kw):
    path = os.path.join(PARTS_DIR, fname)
    result, mesh, feats = _run_engine(path)
    return estimate_decision(result, mesh, feats, EstimateOptions(**opt_kw)), result


def _stl_files():
    return [f for f in os.listdir(PARTS_DIR) if f.lower().endswith(".stl")]


# ── G1 robustness ──────────────────────────────────────────────────────────
def test_g1_invalid_geometry_never_costed_across_all_parts():
    """Every part with vol<=0 or non-watertight => GEOMETRY_INVALID, no
    estimates, no verdict=='pass' surfaced. 100% of the set."""
    invalid_count = 0
    for f in _stl_files():
        report, result = _decide(f)
        g = result.geometry
        is_invalid = (g.volume is None) or (g.volume <= 0.0) or (not g.is_watertight)
        if is_invalid:
            invalid_count += 1
            assert report.status == "GEOMETRY_INVALID", f"{f} should be invalid"
            assert report.estimates == [], f"{f} must produce zero estimates"
            assert report.decision is None
    # at least the known-broken MAF adapter must be caught
    assert invalid_count >= 1


def test_g1_maf_adapter_is_invalid():
    report, _ = _decide(MAF)
    assert report.status == "GEOMETRY_INVALID"
    assert report.estimates == []


# ── G2 sane routing ────────────────────────────────────────────────────────
def test_g2_no_turning_or_superalloy_on_bracket():
    """ECU bracket (polymer, not rotational): no turning, no titanium/superalloy."""
    report, _ = _decide(ECU)
    assert report.status == "OK"
    procs = {e["process"] for e in report.estimates}
    assert "cnc_turning" not in procs, "bracket is not rotational -> no turning"
    from src.costing.routing import material_family
    for e in report.estimates:
        fam = material_family(e["material"])
        assert fam not in ("titanium", "nickel", "cobalt"), (
            f"{e['process']} picked {e['material']} ({fam}) on a polymer part")


def test_g2_turning_only_when_rotational():
    """Turning surfaces for the rotational ring but not the flat bracket."""
    ring_report, _ = _decide(RING)
    bracket_report, _ = _decide(ECU)
    ring_procs = {e["process"] for e in ring_report.estimates}
    bracket_procs = {e["process"] for e in bracket_report.estimates}
    assert "cnc_turning" in ring_procs
    assert "cnc_turning" not in bracket_procs


# ── G3 explainable cost ────────────────────────────────────────────────────
def test_g3_ecu_estimates_itemized_and_summing():
    report, _ = _decide(ECU)
    assert report.estimates
    for e in report.estimates:
        assert len(e["drivers"]) >= 4
        for d in e["drivers"]:
            assert d["source"].strip() and d["provenance"]
        s = sum(e["line_items"].values())
        assert abs(e["unit_cost_usd"] - round(s, 2)) < 0.02


# ── G4 decision / crossover ────────────────────────────────────────────────
def test_g4_ecu_crossover_and_make_vs_buy():
    """Coherence (weakness #7) + DFM-gated headline (weakness #6)."""
    report, _ = _decide(ECU, quantities=[50, 5000])
    dec = report.decision
    assert dec is not None
    assert dec.crossover_qty is not None and dec.crossover_qty > 1
    # COHERENCE INVARIANT (#7): headline make-now == low-qty recommendation
    assert dec.make_now_process == dec.recommendation[50]["process"]
    # the make-now process is DFM-ready (#6 — never a process the part fails)
    assert dec.recommendation[50]["dfm_ready"] is True
    # tooling/production candidate is injection molding, presented conditionally
    assert dec.tooling_process == "injection_molding"
    assert dec.tooling_dfm_ready is False
    # high-qty tier-1 is still a DFM-ready make-as-is process; molding is tier-2
    assert dec.recommendation[5000]["dfm_ready"] is True
    assert dec.if_redesigned[5000] is not None
    assert dec.if_redesigned[5000]["process"] == "injection_molding"


def test_g4_decision_coherence_across_parts():
    """#7 across the real-parts set (loop, like G1): for every OK part the
    headline make-now process equals the low-qty recommendation and is DFM-ready."""
    checked = 0
    for f in sorted(_stl_files()):
        report, _ = _decide(f, quantities=[50, 5000])
        if report.status != "OK" or report.decision is None:
            continue
        dec = report.decision
        q_lo = min(report.quantities)
        assert dec.make_now_process == dec.recommendation[q_lo]["process"], f
        assert dec.recommendation[q_lo]["dfm_ready"] is True, f
        checked += 1
        if checked >= 10:
            break
    assert checked >= 5


def test_g4_raising_tooling_moves_crossover_right():
    base, _ = _decide(ECU, quantities=[50, 5000])
    bumped, _ = _decide(ECU, quantities=[50, 5000],
                        rate_overrides={"tooling.INJECTION_MOLDING": 60000})
    assert bumped.decision.crossover_qty > base.decision.crossover_qty


# ── Weaknesses #1/#2 nesting, #3 min-charge (real parts) ─────────────────────
def test_nesting_reduces_powderbed_machine():
    """#2: powder-bed nesting divides per-part SLS machine time by parts_per_build
    (the build-job is swept once for the whole plate). The per-part machine cost is
    therefore at most isolated/n — the structural fix for the 82%-machine artifact.
    (For the large flat ECU bracket n=16, so machine drops from the V0 $103.82
    isolated build to ~$37.50.)"""
    report, _ = _decide(ECU, quantities=[50])
    sls = [e for e in report.estimates if e["process"] == "sls"][0]
    n = next(d["value"] for d in sls["drivers"] if d["name"] == "parts_per_build")
    machine = sls["line_items"]["machine"]
    assert n > 1, "powder-bed SLS must nest >1 part per build"
    isolated_machine = machine * n            # one isolated build = build_job × rate
    assert machine <= 0.5 * isolated_machine, "nesting must at least halve per-part machine"
    assert machine < 103.82, f"V1 machine {machine} must beat the V0 isolated $103.82"


def test_small_part_am_not_overcosted():
    """#1/#2: throttle SLS @ qty 100 lands in the independent $3-12 band (was $41),
    and for a small nested part the machine line is no longer the dominant >70%."""
    report, _ = _decide(TBA, quantities=[100])
    sls = [e for e in report.estimates if e["process"] == "sls"][0]
    assert 3.0 <= sls["unit_cost_usd"] <= 12.0, sls["unit_cost_usd"]
    assert sls["line_items"]["machine"] < 0.70 * sls["unit_cost_usd"]


def test_min_charge_floor_real_part():
    """#3: a 1-unit CNC turning order never falls below the shop minimum, and the
    floor is booked as its own line item so Σ = unit still holds."""
    report, _ = _decide(TBA, quantities=[1])
    turn = [e for e in report.estimates if e["process"] == "cnc_turning"][0]
    assert turn["unit_cost_usd"] >= 90.0
    assert "min_charge_floor" in turn["line_items"]
    assert abs(turn["unit_cost_usd"] - round(sum(turn["line_items"].values()), 2)) < 0.02


# ── G5 lead time ───────────────────────────────────────────────────────────
def test_g5_lead_time_components_and_monotonic():
    report, _ = _decide(ECU, quantities=[50, 5000])
    by = {}
    for e in report.estimates:
        lt = e["lead_time"]
        assert set(lt["components"]) >= {"queue", "production", "post_process", "ship"}
        assert lt["low_days"] < lt["high_days"]
        by.setdefault(e["process"], {})[e["quantity"]] = lt["mid_days"]
    for proc, q in by.items():
        if 50 in q and 5000 in q:
            assert q[5000] >= q[50]


# ── R1 finite-capacity lead time ────────────────────────────────────────────
def test_r1_capacity_pool_caps_high_qty_leadtime():
    """R1: high-qty AM lead time is finite-capacity, never multi-year, and the
    machine-pool assumption is stated + overridable."""
    report, _ = _decide(ECU, quantities=[50, 5000])
    mjf = [e for e in report.estimates if e["process"] == "mjf" and e["quantity"] == 5000][0]
    lt = mjf["lead_time"]
    assert lt["high_days"] < 365, f"q5000 mjf lead must be < 1 year, got {lt['high_days']}"
    cap = lt["capacity"]
    assert cap["n_machines"] >= 1 and cap["machine_hours_per_day"] > 0
    assert cap["provenance"] == "DEFAULT"
    # monotonic still holds
    mjf50 = [e for e in report.estimates if e["process"] == "mjf" and e["quantity"] == 50][0]
    assert mjf["lead_time"]["mid_days"] >= mjf50["lead_time"]["mid_days"]


# ── R2 serial-AM XY build-plate nesting ─────────────────────────────────────
def test_r2_serial_xy_nesting_amortizes_sweep():
    """R2: a medium FDM part nests >=1 per plate (the throttle adapter nests many)
    and Σ-invariant holds; parts/plate is XY-derived."""
    report, _ = _decide(TBA, quantities=[100])
    fdm = [e for e in report.estimates if e["process"] == "fdm"][0]
    n = next(d["value"] for d in fdm["drivers"] if d["name"] == "parts_per_build")
    assert n > 1, "throttle adapter must nest >1 FDM part per plate (XY footprint)"
    assert abs(fdm["unit_cost_usd"] - round(sum(fdm["line_items"].values()), 2)) < 0.02
    # XY-nesting source string is surfaced on the parts_per_build driver
    pp = next(d for d in fdm["drivers"] if d["name"] == "parts_per_build")
    assert "XY nest" in pp["source"]


# ── G6 honesty / anchor ────────────────────────────────────────────────────
def test_g6_sls_estimate_in_service_bureau_band():
    """Positioning anchor (V1, nested): ECU SLS ~$47/unit sits inside a nested
    powder-bed bureau band ~$30-110 (V0 was $126 for an un-nested isolated build)."""
    report, _ = _decide(ECU, quantities=[50])
    sls = [e for e in report.estimates if e["process"] == "sls"]
    assert sls, "SLS should be costable for the ECU bracket"
    assert 30.0 <= sls[0]["unit_cost_usd"] <= 110.0
    assert report.assumptions


# ── G7 speed + IP-local ────────────────────────────────────────────────────
def test_g7_no_outbound_socket_during_costing():
    """The cost layer opens zero sockets (CAD-as-IP, strategy constraint)."""
    import socket

    path = os.path.join(PARTS_DIR, ECU)
    result, mesh, feats = _run_engine(path)   # engine runs on local STL

    real_socket = socket.socket

    def _boom(*a, **k):
        raise AssertionError("network access attempted during costing")

    socket.socket = _boom
    try:
        report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[50, 5000]))
    finally:
        socket.socket = real_socket
    assert report.status == "OK"
