"""Accuracy-harness tests (fix-spec §13.4) — measured, reproducible, local.

These assert the V1 accuracy CHARACTERIZATION, not a rubber stamp:
  - the harness runs on the frozen real-part sample and is DETERMINISTIC;
  - it opens ZERO sockets (CAD-as-IP);
  - the CORE accuracy wins hold (small-part-AM B-1/B-2, CNC floor B-3, tooling
    B-5, >=80% overall in the independent bands, and CNC/IM/powder-bed centered);
  - the KNOWN residual (serial AM: FDM/SLA run high — no build-plate nesting) is
    MEASURED and flagged in the documented direction, not hidden.

Skips cleanly when the real parts dir is absent (CI without the STL batch still
passes the procedural model tests).
"""

from __future__ import annotations

import pytest

from src.costing import harness

PARTS_DIR = harness.ensure_fixture_parts_dir()

pytestmark = pytest.mark.skipif(
    not harness.has_sample_parts(PARTS_DIR),
    reason=f"real parts fixture batch not present: {PARTS_DIR}",
)


@pytest.fixture(scope="module")
def res():
    return harness.run_harness(PARTS_DIR)


# ── sample + run integrity ──────────────────────────────────────────────────
def test_sample_is_at_least_10_real_parts(res):
    assert res.n_parts >= 10, f"sample collapsed to {res.n_parts} parts"
    assert len(res.comparisons) >= 100, "too few (part,process,qty) comparisons"


def test_harness_is_deterministic():
    """A second full run produces identical comparisons (reproducible bands)."""
    a = harness.run_harness(PARTS_DIR)
    b = harness.run_harness(PARTS_DIR)
    key = lambda c: (c.part, c.process, c.qty, round(c.v1_unit, 4),
                     round(c.ref_lo, 4), round(c.ref_hi, 4))
    assert sorted(map(key, a.comparisons)) == sorted(map(key, b.comparisons))


def test_zero_network_egress_during_harness():
    """The harness opens no sockets (run on a 2-part subset under a socket block)."""
    import socket

    real = socket.socket

    def _boom(*a, **k):
        raise AssertionError("network access attempted during accuracy harness")

    subset = harness.SAMPLE_PARTS[:2]
    socket.socket = _boom
    try:
        r = harness.run_harness(PARTS_DIR, sample=subset, do_floor_checks=False)
    finally:
        socket.socket = real
    assert r.n_parts == 2
    assert r.comparisons


# ── §13.4 acceptance criteria (the ones V1 meets) ───────────────────────────
def test_c1_at_least_80pct_in_independent_band(res):
    crit = harness.pass_criteria(res)
    ok, detail = crit["C1_in_band>=80pct"]
    assert ok, detail


def test_c3_small_part_am_regression_b1_b2(res):
    """Throttle adapter (2.81 cm³) SLS/MJF land within 2x the independent AM band
    — the flat-$17.50 over-cost is gone (validation-packet B-1/B-2)."""
    crit = harness.pass_criteria(res)
    ok, detail = crit["C3_smallpart_AM_in_band"]
    assert ok, detail


def test_c4_cnc_floor_clears_shop_minimum(res):
    """Every CNC estimate at qty=1 clears the independent R4 CNC order minimum
    (validation-packet B-3 min-charge floor)."""
    crit = harness.pass_criteria(res)
    ok, detail = crit["C4_cnc_floor>=R4min"]
    assert ok, detail
    assert len(res.floor_checks) >= 2


def test_c5_tooling_within_independent_band(res):
    """Every IM tooling figure sits inside the independent R3 size×cavity band
    (validation-packet B-5)."""
    crit = harness.pass_criteria(res)
    ok, detail = crit["C5_tooling_in_R3"]
    assert ok, detail
    assert len(res.tooling_checks) >= 5


# ── well-characterized processes stay centered ──────────────────────────────
def test_cnc_im_powderbed_processes_are_centered(res):
    """CNC, injection molding, and nested powder-bed (SLS/MJF) all sit within
    +/-60% of the independent midpoint (no systematic bias)."""
    per = harness.aggregate_by_process(res.comparisons)
    for proc in ("cnc_3axis", "cnc_5axis", "cnc_turning",
                 "injection_molding", "sls", "mjf"):
        assert proc in per, f"{proc} missing from comparisons"
        assert abs(per[proc]["median_signed_err"]) <= 0.60, (
            f"{proc} median {per[proc]['median_signed_err']:+.2f} exceeds +/-60% band")


def test_all_processes_within_systematic_bias_bar(res):
    """Every costed process — including the now-XY-nested FDM/SLA — sits within
    the +/-60% systematic-bias bar (C2)."""
    per = harness.aggregate_by_process(res.comparisons)
    for proc, v in per.items():
        assert abs(v["median_signed_err"]) <= 0.60, (
            f"{proc} median {v['median_signed_err']:+.2f} exceeds +/-60%")


# ── R2: the serial-AM residual is now FIXED by XY build-plate nesting ────────
def test_serial_am_within_band_after_xy_nesting(res):
    """R2: FDM/SLA now nest in X-Y on the build plate (per-part deposition kept,
    shared Z-sweep amortized), so their systematic bias drops inside the +/-60%
    bar. The pre-fix V1 ran +0.6..+0.75 high; this asserts the fix, not the old
    residual."""
    per = harness.aggregate_by_process(res.comparisons)
    for proc in ("fdm", "sla"):
        assert proc in per
        assert abs(per[proc]["median_signed_err"]) <= 0.60, (
            f"{proc} median {per[proc]['median_signed_err']:+.2f} must now be "
            f"within +/-60% after XY nesting")
