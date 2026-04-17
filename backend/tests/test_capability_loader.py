"""Tests for capability table loader (11-03).

Validates YAML coverage, validation logic, and surface finish data.
"""
from __future__ import annotations

import pytest

from src.analysis.capabilities.loader import (
    ProcessCapability,
    get_capability,
    load_capabilities,
    validate_tolerance,
)
from src.analysis.models import ProcessType


def test_load_capabilities_all_processes():
    """All 21 ProcessType enum values must have entries in YAML."""
    caps = load_capabilities()
    for pt in ProcessType:
        assert pt.value in caps, f"Missing capability entry for {pt.name} ({pt.value})"
    assert len(caps) == 21


def test_load_capabilities_structure():
    """Each capability has a non-empty achievable_min dict and positive Ra."""
    caps = load_capabilities()
    for process_key, cap in caps.items():
        assert isinstance(cap, ProcessCapability)
        assert len(cap.achievable_min) > 0, f"{process_key} has empty achievable_min"
        assert cap.ra_min_um > 0, f"{process_key} has non-positive ra_min_um"
        assert cap.ra_typical_um > 0, f"{process_key} has non-positive ra_typical_um"


def test_validate_tolerance_achievable():
    """Value well above 2x min -> achievable with positive margin."""
    verdict, cap_min, margin = validate_tolerance(0.1, ProcessType.CNC_3AXIS, "flatness")
    assert verdict == "achievable"
    assert cap_min == 0.005
    assert margin > 0


def test_validate_tolerance_marginal():
    """Value between min and 2x min -> marginal."""
    verdict, cap_min, margin = validate_tolerance(0.008, ProcessType.CNC_3AXIS, "flatness")
    assert verdict == "marginal"
    assert cap_min == 0.005
    assert margin > 0


def test_validate_tolerance_not_achievable():
    """Value below min -> not_achievable with negative margin."""
    verdict, cap_min, margin = validate_tolerance(0.001, ProcessType.FDM, "flatness")
    assert verdict == "not_achievable"
    assert margin < 0


def test_validate_tolerance_unknown_type():
    """Unknown tolerance type string -> unknown verdict."""
    verdict, cap_min, margin = validate_tolerance(0.01, ProcessType.CNC_3AXIS, "nonexistent_type")
    assert verdict == "unknown"
    assert cap_min == 0.0
    assert margin == 0.0


def test_surface_finish_values_present():
    """Every process must have positive ra_min_um."""
    caps = load_capabilities()
    for process_key, cap in caps.items():
        assert cap.ra_min_um > 0, f"{process_key} missing ra_min_um"
        assert cap.ra_typical_um >= cap.ra_min_um, (
            f"{process_key}: ra_typical_um ({cap.ra_typical_um}) < ra_min_um ({cap.ra_min_um})"
        )


def test_get_capability_valid():
    """get_capability returns ProcessCapability for known process."""
    cap = get_capability(ProcessType.WIRE_EDM)
    assert cap is not None
    assert "flatness" in cap.achievable_min
    assert cap.ra_min_um == 0.2


def test_tolerance_categories_complete():
    """Each process should have all 14 ISO 1101 tolerance types."""
    expected_types = {
        "flatness", "straightness", "circularity", "cylindricity",
        "parallelism", "perpendicularity", "angularity",
        "position", "concentricity", "symmetry",
        "profile_of_surface", "profile_of_line",
        "circular_runout", "total_runout",
    }
    caps = load_capabilities()
    for process_key, cap in caps.items():
        missing = expected_types - set(cap.achievable_min.keys())
        assert not missing, f"{process_key} missing tolerance types: {missing}"
