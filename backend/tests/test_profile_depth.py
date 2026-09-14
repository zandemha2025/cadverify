"""Machine-catalog and shop-profile depth tests (data-plane lane, 2026-09-14).

These tests guard the trust contract of the cost/verification engine's reference
data:

  * every manufacturing process the platform can route to has real machine
    coverage (a verdict that silently says "no machine knows how" is a hole);
  * machine specs stay internally sane (positive envelopes, ordered layer
    bounds, additive machines carry additive fields);
  * every shop profile in the local store loads, binds only valid dotted-key
    overrides (real ProcessType names, known material vocabulary, known region
    codes), and declares honest provenance - modeled exemplars must SAY they
    are modeled, never dress up as measured data.
"""

from __future__ import annotations

import json
import os

import pytest

from src.analysis.models import ProcessType
from src.costing.rates import MATERIAL_FAMILY
from src.costing.shop_profile import (
    DEFAULT_STORE_DIR,
    ShopProfile,
    list_profiles,
    load_profile,
)
from src.profiles.database import MACHINES

# Processes where a single machine is too thin to be a credible catalog.
CORE_PROCESSES = {
    ProcessType.FDM, ProcessType.SLA, ProcessType.SLS, ProcessType.MJF,
    ProcessType.DMLS, ProcessType.SLM,
    ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS, ProcessType.CNC_TURNING,
    ProcessType.INJECTION_MOLDING, ProcessType.SHEET_METAL,
}

ADDITIVE_PROCESSES = {
    ProcessType.FDM, ProcessType.SLA, ProcessType.DLP, ProcessType.SLS,
    ProcessType.MJF, ProcessType.DMLS, ProcessType.SLM, ProcessType.EBM,
    ProcessType.BINDER_JET,
}

KNOWN_REGIONS = {"US", "EU", "MX", "CN", "IN", "SA"}
KNOWN_MATERIAL_CLASSES = set(MATERIAL_FAMILY.values())


# ── machine catalog depth ──────────────────────────────────────────────────

def test_every_process_has_machine_coverage():
    for pt in ProcessType:
        have = [m for m in MACHINES if m.process_type == pt]
        assert have, f"process {pt.value} has ZERO machine profiles"
    for pt in CORE_PROCESSES:
        have = [m for m in MACHINES if m.process_type == pt]
        assert len(have) >= 2, (
            f"core process {pt.value} has only {len(have)} machine(s)")


def test_no_duplicate_machine_names():
    names = [m.name for m in MACHINES]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate machine names: {sorted(dupes)}"


def test_machine_specs_internally_sane():
    for m in MACHINES:
        assert all(v > 0 for v in m.build_volume), (
            f"{m.name}: non-positive build_volume {m.build_volume}")
        if m.min_layer_height is not None and m.max_layer_height is not None:
            assert m.min_layer_height <= m.max_layer_height, (
                f"{m.name}: layer bounds inverted "
                f"({m.min_layer_height} > {m.max_layer_height})")
        if m.process_type in ADDITIVE_PROCESSES:
            assert m.materials, f"{m.name}: additive machine with no materials"
            assert m.min_layer_height is not None, (
                f"{m.name}: additive machine missing min_layer_height")


def test_cell_profiles_are_labeled():
    """Proxy-envelope entries (cells, molding presses) must say so in notes."""
    for m in MACHINES:
        if m.process_type in (ProcessType.INVESTMENT_CASTING,
                              ProcessType.SAND_CASTING, ProcessType.FORGING):
            assert "cell" in (m.notes or "").lower(), (
                f"{m.name}: process-cell entry must label itself as a cell")


# ── shop-profile store ─────────────────────────────────────────────────────

def _all_profiles():
    names = list_profiles()
    assert len(names) >= 8, (
        f"shop-profile store too thin: {len(names)} profiles "
        f"(archetype matrix needs region x process spread)")
    return [load_profile(n) for n in names]


def test_shop_profiles_load_and_have_declared_provenance():
    for p in _all_profiles():
        assert isinstance(p, ShopProfile)
        src = (p.source or "").lower()
        assert src, f"{p.name}: empty provenance string"
        assert any(tag in src for tag in ("modeled", "export", "audit", "rfq", "quoted")), (
            f"{p.name}: provenance must declare its class "
            f"(modeled exemplar vs measured export), got: {p.source!r}")


def test_shop_profile_regions_known():
    for p in _all_profiles():
        assert p.region in KNOWN_REGIONS, (
            f"{p.name}: region {p.region!r} not in the rate card's region "
            f"vocabulary {sorted(KNOWN_REGIONS)}")


def test_shop_profile_override_vocabulary_valid():
    """Every key a profile binds must resolve against real vocabulary."""
    for p in _all_profiles():
        for proc_name in (p.machine_rates or {}):
            assert proc_name in ProcessType.__members__, (
                f"{p.name}: machine_rates key {proc_name!r} is not a "
                f"ProcessType name")
        for mat_key in (p.material_prices or {}):
            if mat_key.startswith("@"):
                assert mat_key[1:] in KNOWN_MATERIAL_CLASSES, (
                    f"{p.name}: unknown material class {mat_key!r}")
            else:
                assert mat_key in MATERIAL_FAMILY, (
                    f"{p.name}: material {mat_key!r} not in the cost "
                    f"engine's MATERIAL_FAMILY vocabulary")


def test_shop_profile_rates_sane():
    for p in _all_profiles():
        for field_name in ("margin", "overhead", "utilization"):
            v = getattr(p, field_name)
            if v is not None:
                assert 0 < v < 1, f"{p.name}: {field_name}={v} out of (0,1)"
        if p.labor_rate is not None:
            assert 1 <= p.labor_rate <= 500, (
                f"{p.name}: labor_rate {p.labor_rate} implausible")
        for proc_name, rate in (p.machine_rates or {}).items():
            assert 1 <= rate <= 1000, (
                f"{p.name}: machine rate {proc_name}={rate} implausible")


def test_shop_profile_region_double_count_pinned():
    """A profile with an absolute loaded labor_rate must pin region labor=1.0
    (documented in shop_profile.py: the loaded rate already encodes region)."""
    for p in _all_profiles():
        if p.labor_rate is not None:
            assert (p.region_multipliers or {}).get("labor") == 1.0, (
                f"{p.name}: sets absolute labor_rate but does not pin "
                f"region_multipliers.labor=1.0 -> regional factor would be "
                f"charged twice")


def test_shop_profile_overrides_bind_through_rate_card():
    """End-to-end: flatten a profile and confirm the rate card accepts every
    key as SHOP-provenance (no silent drops)."""
    from src.costing.rates import build_rate_card
    for p in _all_profiles():
        overrides = p.to_shop_overrides()
        assert overrides, f"{p.name}: profile binds nothing"
        card = build_rate_card(shop_overrides=overrides, shop_name=p.name,
                               shop_region=p.region)
        for dotted in overrides:
            assert card.prov_tag(dotted).name == "SHOP", (
                f"{p.name}: override {dotted} did not bind as SHOP")


def test_no_shop_profile_claims_unverified_measured_provenance():
    for p in _all_profiles():
        src = (p.source or "").lower()
        assert "not a measured shop" in src, (
            f"{p.name}: measured provenance requires a verified source receipt; "
            f"current profile must remain an explicit modeled exemplar"
        )
        assert not any(claim in src for claim in (
            "shop accounting export", "supplier rfq packet", "measured rates",
        )), f"{p.name}: unverified measured-provenance claim: {p.source!r}"
