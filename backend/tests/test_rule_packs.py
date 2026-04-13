"""Tests for industry rule packs — aerospace, automotive, oil_gas, medical."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.rules import available_rule_packs, get_rule_pack


def test_all_four_packs_registered():
    packs = available_rule_packs()
    assert "aerospace" in packs
    assert "automotive" in packs
    assert "oil_gas" in packs
    assert "medical" in packs


def test_aerospace_pack_structure():
    pack = get_rule_pack("aerospace")
    assert pack is not None
    assert pack.version == "1.0.0"
    assert len(pack.overrides) > 0
    assert len(pack.mandatory_issues) >= 3
    # Check TRACEABILITY_REQUIRED is mandatory
    codes = {i.code for i in pack.mandatory_issues}
    assert "TRACEABILITY_REQUIRED" in codes
    assert "SPECIAL_PROCESSES" in codes
    assert "FIRST_ARTICLE_INSPECTION" in codes


def test_oil_gas_pack_has_nace():
    pack = get_rule_pack("oil_gas")
    assert pack is not None
    codes = {i.code for i in pack.mandatory_issues}
    assert "NACE_MR0175_CHECK" in codes
    assert "HYDROSTATIC_TEST" in codes


def test_medical_pack_has_biocompatibility():
    pack = get_rule_pack("medical")
    assert pack is not None
    codes = {i.code for i in pack.mandatory_issues}
    assert "BIOCOMPATIBILITY_REQUIRED" in codes
    assert "STERILIZATION_VALIDATION" in codes


def test_aerospace_escalates_thin_wall_dmls():
    """Aerospace pack tightens DMLS wall from 0.4mm to 0.6mm."""
    pack = get_rule_pack("aerospace")
    # Simulate an issue at 0.5mm (passes default 0.4mm, fails aerospace 0.6mm)
    issue = Issue(
        code="THIN_WALL",
        severity=Severity.WARNING,
        message="test",
        process=ProcessType.DMLS,
        measured_value=0.5,
        required_value=0.4,
    )
    result = pack.apply([issue], ProcessType.DMLS)
    # Should be escalated to ERROR because 0.5 < 0.6 (stricter_value)
    thin = [i for i in result if i.code == "THIN_WALL"]
    assert len(thin) == 1
    assert thin[0].severity == Severity.ERROR
    assert thin[0].required_value == 0.6


def test_aerospace_adds_mandatory_issues():
    pack = get_rule_pack("aerospace")
    result = pack.apply([], ProcessType.FDM)
    codes = {i.code for i in result}
    assert "TRACEABILITY_REQUIRED" in codes


def test_rule_pack_unknown_returns_none():
    assert get_rule_pack("nonexistent") is None


def test_api_validate_with_rule_pack(monkeypatch, cube_10mm, stl_bytes_of):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    import main
    importlib.reload(main)
    client = TestClient(main.app)

    data = stl_bytes_of(cube_10mm)
    r = client.post(
        "/api/v1/validate?rule_pack=aerospace",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("rule_pack") == {"name": "aerospace", "version": "1.0.0"}
    # Mandatory aerospace issues should appear in priority_fixes
    fix_codes = {f["code"] for f in body["priority_fixes"]}
    assert "TRACEABILITY_REQUIRED" in fix_codes


def test_api_validate_without_rule_pack(monkeypatch, cube_10mm, stl_bytes_of):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    import main
    importlib.reload(main)
    client = TestClient(main.app)

    data = stl_bytes_of(cube_10mm)
    r = client.post(
        "/api/v1/validate",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "rule_pack" not in body


def test_api_invalid_rule_pack_returns_400(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    import main
    importlib.reload(main)
    client = TestClient(main.app)

    r = client.post(
        "/api/v1/validate?rule_pack=nonexistent",
        files={"file": ("cube.stl", b"\x00" * 100, "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "Unknown rule pack" in r.json()["detail"]


def test_api_rule_packs_endpoint(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    import main
    importlib.reload(main)
    client = TestClient(main.app)

    r = client.get("/api/v1/rule-packs")
    assert r.status_code == 200
    packs = r.json()["rule_packs"]
    names = {p["name"] for p in packs}
    assert names == {"aerospace", "automotive", "oil_gas", "medical"}
    for p in packs:
        assert "version" in p
        assert "description" in p
        assert p["override_count"] > 0
