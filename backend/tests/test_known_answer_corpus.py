"""The known-answer corpus gate.

Walks tests/assets/known-answer/manifest.json and enforces:
  1. SCHEMA: every entry carries provenance (a named source); pending
     contribution slots are declared — never a silent absence of the
     Fusion/SolidWorks exports and real weldment invoices the gates need.
  2. MEASUREMENT: every file entry is parsed by the engine's real mesh path
     and asserted against its recorded values (exact-by-construction,
     published, or dated baseline) within the stated tolerances.
  3. BAND POLICY (the interim gate): with zero paired real quotes for a
     family, its outputs MUST carry the uncalibrated label and the wide
     assumption band — coverage gating activates the day n>=3 REAL pairs
     exist (see tests/test_weldment_costing.py's TestBandCoverageGate).

Baselines are regression evidence stamped with date + engine commit; they
are explicitly NOT published truth. Where a published value exists (NIST
PMI ⌀35 +0/-0.2), the dedicated suite holds the pin and this manifest
references it.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

ASSETS = Path(__file__).parent / "assets"
MANIFEST = ASSETS / "known-answer" / "manifest.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def _parse(path: Path):
    from src.api.routes import _parse_mesh

    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return _parse_mesh(data, path.name.replace(".gz", ""))


class TestCorpusSchema:
    def test_every_entry_carries_provenance_with_a_named_source(self):
        m = _manifest()
        assert m["entries"], "the corpus must not be empty"
        for e in m["entries"]:
            prov = e.get("provenance") or {}
            assert prov.get("source", "").strip() > "", e["file"]

    def test_pending_fusion_and_solidworks_slots_are_declared(self):
        """No silent absence: the CAD-tool export gaps stay on the record."""
        slots = {p["slot"] for p in _manifest()["pending_contributions"]}
        assert "fusion360_export.step" in slots
        assert "solidworks_export.step" in slots
        assert "weldment_cut_lists_with_invoices" in slots


class TestCorpusMeasurement:
    def test_step_entries_match_recorded_values(self):
        m = _manifest()
        checked = 0
        for e in m["entries"]:
            f = e["file"]
            if not f.startswith("../"):
                continue  # generated fixtures are asserted in their own suites
            known = e["known"]
            mesh, _suffix = _parse((ASSETS / "known-answer" / f).resolve())
            a = known["asserts"]
            tol = known.get("tolerance", {})
            ext = sorted((float(x) for x in mesh.bounding_box.extents), reverse=True)
            want = sorted(a["bbox_mm"], reverse=True)
            for got, exp in zip(ext, want):
                assert got == pytest.approx(exp, rel=tol.get("bbox_pct", 0.5) / 100.0), (
                    f"{f} bbox {ext} vs recorded {want}")
            assert mesh.volume == pytest.approx(
                a["volume_mm3"], rel=tol.get("volume_pct", 1.0) / 100.0), f
            face_tol = tol.get("faces_pct", 2.0) / 100.0
            assert len(mesh.faces) == pytest.approx(a["faces"], rel=face_tol), (
                f"{f} faces {len(mesh.faces)} vs recorded {a['faces']}")
            assert mesh.is_watertight is a["watertight"], f
            checked += 1
        assert checked >= 3, "expected at least three real-file corpus entries"

    def test_nist_entry_pins_its_published_pmi_reference(self):
        e = next(x for x in _manifest()["entries"] if "nist" in x["file"])
        assert e["known"]["type"] == "published_pmi_plus_baseline"
        assert "⌀35 +0/-0.2" in e["known"]["published"]
        assert e["known"]["asserts"]["has_pmi"] is True

    def test_generated_exact_construction_entries_exist(self):
        kinds = {e["file"] for e in _manifest()["entries"]
                 if e["known"]["type"] == "exact_by_construction"}
        assert "generated:welded_frame_40x40x3" in kinds
        assert "generated:pressure_tube_od100_id80" in kinds
