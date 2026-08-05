"""Honest "material read from CAD" slice — no-kernel STEP text scan.

Proves, in order:
  1. ``scan_step_material`` finds the declared material in the material-bearing
     fixture, and returns None for both a no-material STEP (``cube.step``) and a
     real-world NIST part with no material annotation (``nist_periodic_ctc05.stp``).
  2. ``map_material_to_class`` resolves both MATERIAL_FAMILY exact names and a
     small alias layer, and never invents a class outside MATERIAL_FAMILY's
     values.
  3. End-to-end through ``estimate_decision``: an undeclared material_class on a
     material-bearing STEP fills from the CAD file and is tagged CAD provenance;
     an explicit USER declaration always wins and stays USER; a no-material STEP
     is untouched (DEFAULT, unchanged pre-existing behaviour).

No network, no DB — pure local fixtures. The end-to-end block uses the real
gmsh STEP mesher (skips cleanly if gmsh/OCC is unavailable in this environment).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.costing.provenance import Provenance
from src.costing.rates import MATERIAL_FAMILY
from src.parsers.step_material import (
    map_material_to_class,
    material_class_from_step,
    scan_step_material,
)

_ASSETS = Path(__file__).parent / "assets"
_MATERIAL_STEP = _ASSETS / "cube_with_material.step"
_PLAIN_STEP = _ASSETS / "cube.step"
_NIST_STEP = _ASSETS / "nist_periodic_ctc05.stp"


# ══════════════════════════════════════════════════════════════════════════
# 1) scan_step_material — raw text scan
# ══════════════════════════════════════════════════════════════════════════
def test_scan_finds_material_in_material_bearing_fixture():
    data = _MATERIAL_STEP.read_bytes()
    assert scan_step_material(data) == "6061-T6 Aluminum"


def test_scan_returns_none_for_plain_cube():
    data = _PLAIN_STEP.read_bytes()
    assert scan_step_material(data) is None


def test_scan_returns_none_for_nist_part_with_no_material():
    data = _NIST_STEP.read_bytes()
    assert scan_step_material(data) is None


def test_scan_never_raises_on_garbage_bytes():
    assert scan_step_material(b"") is None
    assert scan_step_material(b"\x00\x01\xff not a step file at all") is None
    assert scan_step_material(None) is None  # type: ignore[arg-type]


def test_scan_does_not_pick_up_translator_software_names():
    """cube.step's HEADER carries 'Open CASCADE' / 'STEP translator' strings —
    those must never be mistaken for a material."""
    data = _PLAIN_STEP.read_bytes()
    text = data.decode("latin-1")
    assert "Open CASCADE" in text  # sanity: the noise really is present
    assert scan_step_material(data) is None


# ══════════════════════════════════════════════════════════════════════════
# 2) map_material_to_class — MATERIAL_FAMILY exact + alias layer
# ══════════════════════════════════════════════════════════════════════════
def test_map_exact_material_family_names():
    assert map_material_to_class("6061-T6 Aluminum") == "aluminum"
    assert map_material_to_class("AISI 4140") == "steel"
    assert map_material_to_class("Inconel 718") == "nickel"
    assert map_material_to_class("SS316L") == "stainless"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("AL 6061", "aluminum"),
        ("Aluminium", "aluminum"),
        ("Steel", "steel"),
        ("carbon steel", "steel"),
        ("Ti-6Al-4V", "titanium"),
        ("Titanium", "titanium"),
        ("Inconel 718", "nickel"),
        ("Hastelloy C276", "nickel"),
        ("Stainless Steel 304", "stainless"),
        ("ABS", "polymer"),
        ("Nylon", "polymer"),
    ],
)
def test_map_alias_layer(raw, expected):
    assert map_material_to_class(raw) == expected


@pytest.mark.parametrize("junk", ["", None, "asdfqwerty1234", "Widget Model X",
                                   "Open CASCADE 7.8"])
def test_map_unmappable_returns_none(junk):
    assert map_material_to_class(junk) is None


def test_map_only_returns_classes_present_in_material_family():
    """Never invent a class the engine doesn't actually cost."""
    available = set(MATERIAL_FAMILY.values())
    samples = ["6061-T6 Aluminum", "AL 6061", "Steel", "Ti-6Al-4V", "Inconel 718",
               "SS316L", "ABS", "Brass", "Zinc Alloy", "CoCr"]
    for s in samples:
        cls = map_material_to_class(s)
        if cls is not None:
            assert cls in available, f"{s!r} mapped to unknown class {cls!r}"


def test_material_class_from_step_composes_scan_and_map():
    assert material_class_from_step(_MATERIAL_STEP.read_bytes()) == "aluminum"
    assert material_class_from_step(_PLAIN_STEP.read_bytes()) is None
    assert material_class_from_step(_NIST_STEP.read_bytes()) is None


# ══════════════════════════════════════════════════════════════════════════
# 3) end-to-end — the real /validate/cost route (real gmsh STEP mesh)
# ══════════════════════════════════════════════════════════════════════════
def _skip_if_no_step_support():
    from src.parsers.step_mesher import is_step_supported

    if not is_step_supported():
        pytest.skip("gmsh/OCC STEP support unavailable in this environment")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import importlib

    import main

    importlib.reload(main)  # conftest re-applies the auth/DB bypass on reload
    from fastapi.testclient import TestClient

    return TestClient(main.app)


def _post(client, path: Path, **form):
    return client.post(
        "/api/v1/validate/cost",
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
        data=form,
    )


def _material_assumption(body: dict) -> dict:
    for a in body["assumptions"]:
        if a["name"] == "material_class":
            return a
    raise AssertionError("no material_class assumption in response")


def test_e2e_undeclared_material_fills_from_cad_with_cad_provenance(client):
    _skip_if_no_step_support()
    r = _post(client, _MATERIAL_STEP, qty="50")  # material_class left at DEFAULT
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["material_class"] == "aluminum"
    a = _material_assumption(body)
    assert a["unit"] == "aluminum"  # material_class Driver carries the class in `unit`
    assert a["provenance"] == Provenance.CAD.value


def test_e2e_explicit_user_declaration_overrides_cad(client):
    _skip_if_no_step_support()
    r = _post(client, _MATERIAL_STEP, qty="50", material_class="steel")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["material_class"] == "steel"
    a = _material_assumption(body)
    assert a["unit"] == "steel"
    assert a["provenance"] == Provenance.USER.value


def test_e2e_no_material_step_stays_default_unchanged(client):
    _skip_if_no_step_support()
    r = _post(client, _PLAIN_STEP, qty="50")  # material_class left at DEFAULT
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["material_class"] == "polymer"
    a = _material_assumption(body)
    assert a["unit"] == "polymer"
    assert a["provenance"] == Provenance.DEFAULT.value
