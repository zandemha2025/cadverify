"""Tests for GD&T/PMI extractor (STEP-02).

Tests cover tolerance data model completeness, extraction with mocked OCP
objects, partial failure resilience, and surface finish extraction.
OCP-dependent tests are skipped when XDE modules are not available.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.tolerance_models import ToleranceEntry, ToleranceType
from src.parsers.gdt_extractor import (
    _HAS_XDE,
    _OCP_TYPE_MAP,
    extract_gdt,
    extract_surface_finish,
)

# When OCP is not installed, the module-level names (TDF_LabelSequence etc.)
# don't exist. We must use patch(..., create=True) to inject them for testing.


# ── Data model coverage ──────────────────────────────────────


def test_ocp_type_map_covers_all_tolerance_types():
    """_OCP_TYPE_MAP must map to every ToleranceType enum value."""
    mapped_types = set(_OCP_TYPE_MAP.values())
    all_types = set(ToleranceType)
    missing = all_types - mapped_types
    assert not missing, f"ToleranceType values missing from _OCP_TYPE_MAP: {missing}"


def test_tolerance_type_has_14_values():
    """ISO 1101 defines 14 geometric tolerance types."""
    assert len(ToleranceType) == 14


# ── Mocked extraction tests ──────────────────────────────────


@patch("src.parsers.gdt_extractor._HAS_XDE", False)
def test_extract_gdt_no_xde():
    """When OCP XDE is unavailable, extract_gdt returns empty with warning."""
    doc = MagicMock()
    tolerances, warnings = extract_gdt(doc)
    assert tolerances == []
    assert len(warnings) == 1
    assert "not available" in warnings[0].lower()


@patch("src.parsers.gdt_extractor._HAS_XDE", True)
@patch("src.parsers.gdt_extractor.XCAFDimTolObjects_DatumObject", MagicMock(), create=True)
@patch("src.parsers.gdt_extractor.XCAFDimTolObjects_GeomToleranceObject", MagicMock(), create=True)
@patch("src.parsers.gdt_extractor.XCAFDimTolObjects_DimensionObject", MagicMock(), create=True)
def test_extract_gdt_empty_document():
    """AP242 document with no GDT labels returns ([], [])."""
    mock_label_seq = MagicMock()
    mock_label_seq.Length.return_value = 0

    with patch("src.parsers.gdt_extractor.TDF_LabelSequence", return_value=mock_label_seq, create=True):
        doc = MagicMock()
        doc.dim_tol_tool = MagicMock()
        doc.dim_tol_tool.GetGDTLabels = MagicMock(side_effect=lambda seq: None)
        doc.dim_tol_tool.GetDatumLabels = MagicMock(side_effect=lambda seq: None)

        tolerances, warnings = extract_gdt(doc)
        assert tolerances == []
        assert warnings == []


@patch("src.parsers.gdt_extractor._HAS_XDE", True)
def test_extract_gdt_partial_failure():
    """One label extracts OK, next raises -- partial extraction continues."""
    doc = MagicMock()
    dim_tol_tool = MagicMock()
    doc.dim_tol_tool = dim_tol_tool

    # GDT label sequence with 2 labels
    mock_gdt_seq = MagicMock()
    mock_gdt_seq.Length.return_value = 2
    label1 = MagicMock()
    label1.Tag.return_value = 1
    label2 = MagicMock()
    label2.Tag.return_value = 2
    mock_gdt_seq.Value.side_effect = lambda i: label1 if i == 1 else label2

    # Datum sequence: empty
    mock_datum_seq = MagicMock()
    mock_datum_seq.Length.return_value = 0

    seq_instances = [mock_gdt_seq, mock_datum_seq]
    seq_iter = iter(seq_instances)

    # Geom tolerance object mock
    geom_tol_obj = MagicMock()
    geom_tol_obj.GetType.return_value = 0  # FLATNESS
    geom_tol_obj.GetValue.return_value = 0.05

    call_count = [0]

    def get_geom_tol_side_effect(label, obj):
        call_count[0] += 1
        if call_count[0] == 1:
            obj.GetType = geom_tol_obj.GetType
            obj.GetValue = geom_tol_obj.GetValue
            return True
        raise RuntimeError("Corrupted annotation")

    dim_tol_tool.GetGeomTolerance = MagicMock(side_effect=get_geom_tol_side_effect)

    # Datum ref extraction: empty
    ref_datum_seq = MagicMock()
    ref_datum_seq.Length.return_value = 0
    dim_tol_tool.GetRefDatum = MagicMock(
        side_effect=lambda label, seq: setattr(seq, 'Length', ref_datum_seq.Length) or setattr(seq, 'Value', ref_datum_seq.Value)
    )

    with patch("src.parsers.gdt_extractor.TDF_LabelSequence", side_effect=lambda: next(seq_iter), create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_GeomToleranceObject", return_value=geom_tol_obj, create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_DatumObject", MagicMock(), create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_DimensionObject", MagicMock(), create=True):

        tolerances, warnings = extract_gdt(doc)

    assert len(tolerances) == 1
    assert tolerances[0].tolerance_type == ToleranceType.FLATNESS
    assert len(warnings) >= 1
    assert any("Failed to extract" in w for w in warnings)


@patch("src.parsers.gdt_extractor._HAS_XDE", True)
def test_tolerance_id_auto_generation():
    """Auto-generated IDs follow TOL-001, TOL-002, TOL-003 pattern."""
    doc = MagicMock()
    dim_tol_tool = MagicMock()
    doc.dim_tol_tool = dim_tol_tool

    # 3 GDT labels
    mock_gdt_seq = MagicMock()
    mock_gdt_seq.Length.return_value = 3
    labels = [MagicMock() for _ in range(3)]
    for idx, lbl in enumerate(labels):
        lbl.Tag.return_value = idx + 1
    mock_gdt_seq.Value.side_effect = lambda i: labels[i - 1]

    mock_datum_seq = MagicMock()
    mock_datum_seq.Length.return_value = 0

    seq_instances = [mock_gdt_seq, mock_datum_seq]
    seq_iter = iter(seq_instances)

    geom_tol_obj = MagicMock()
    geom_tol_obj.GetType.return_value = 7  # POSITION
    geom_tol_obj.GetValue.return_value = 0.1

    def get_geom_tol_ok(label, obj):
        obj.GetType = geom_tol_obj.GetType
        obj.GetValue = geom_tol_obj.GetValue
        return True

    dim_tol_tool.GetGeomTolerance = MagicMock(side_effect=get_geom_tol_ok)

    ref_datum_seq = MagicMock()
    ref_datum_seq.Length.return_value = 0
    dim_tol_tool.GetRefDatum = MagicMock(
        side_effect=lambda label, seq: setattr(seq, 'Length', ref_datum_seq.Length) or setattr(seq, 'Value', ref_datum_seq.Value)
    )

    with patch("src.parsers.gdt_extractor.TDF_LabelSequence", side_effect=lambda: next(seq_iter), create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_GeomToleranceObject", return_value=geom_tol_obj, create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_DatumObject", MagicMock(), create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_DimensionObject", MagicMock(), create=True):

        tolerances, warnings = extract_gdt(doc)

    assert len(tolerances) == 3
    assert tolerances[0].tolerance_id == "TOL-001"
    assert tolerances[1].tolerance_id == "TOL-002"
    assert tolerances[2].tolerance_id == "TOL-003"


@patch("src.parsers.gdt_extractor._HAS_XDE", True)
def test_tolerance_entry_fields():
    """Extracted ToleranceEntry has all required fields properly typed."""
    doc = MagicMock()
    dim_tol_tool = MagicMock()
    doc.dim_tol_tool = dim_tol_tool

    mock_gdt_seq = MagicMock()
    mock_gdt_seq.Length.return_value = 1
    label = MagicMock()
    label.Tag.return_value = 1
    mock_gdt_seq.Value.return_value = label

    mock_datum_seq = MagicMock()
    mock_datum_seq.Length.return_value = 0

    seq_instances = [mock_gdt_seq, mock_datum_seq]
    seq_iter = iter(seq_instances)

    geom_tol_obj = MagicMock()
    geom_tol_obj.GetType.return_value = 2  # CIRCULARITY
    geom_tol_obj.GetValue.return_value = 0.02

    def get_geom_tol_ok(label, obj):
        obj.GetType = geom_tol_obj.GetType
        obj.GetValue = geom_tol_obj.GetValue
        return True

    dim_tol_tool.GetGeomTolerance = MagicMock(side_effect=get_geom_tol_ok)

    ref_datum_seq = MagicMock()
    ref_datum_seq.Length.return_value = 0
    dim_tol_tool.GetRefDatum = MagicMock(
        side_effect=lambda label, seq: setattr(seq, 'Length', ref_datum_seq.Length) or setattr(seq, 'Value', ref_datum_seq.Value)
    )

    with patch("src.parsers.gdt_extractor.TDF_LabelSequence", side_effect=lambda: next(seq_iter), create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_GeomToleranceObject", return_value=geom_tol_obj, create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_DatumObject", MagicMock(), create=True), \
         patch("src.parsers.gdt_extractor.XCAFDimTolObjects_DimensionObject", MagicMock(), create=True):

        tolerances, warnings = extract_gdt(doc)

    assert len(tolerances) == 1
    entry = tolerances[0]
    assert isinstance(entry.tolerance_type, ToleranceType)
    assert entry.tolerance_type == ToleranceType.CIRCULARITY
    assert isinstance(entry.value_mm, float)
    assert entry.value_mm > 0
    assert isinstance(entry.datum_refs, list)
    assert isinstance(entry.tolerance_id, str)
    assert entry.tolerance_id.startswith("TOL-")


@patch("src.parsers.gdt_extractor._HAS_XDE", False)
def test_extract_surface_finish_empty():
    """Empty list returned when OCP XDE unavailable for surface finish."""
    doc = MagicMock()
    results = extract_surface_finish(doc)
    assert results == []


@patch("src.parsers.gdt_extractor._HAS_XDE", True)
def test_extract_surface_finish_no_annotations():
    """Empty list returned when document has no surface finish annotations."""
    doc = MagicMock()
    doc.dim_tol_tool = MagicMock()

    mock_seq = MagicMock()
    mock_seq.Length.return_value = 0

    with patch("src.parsers.gdt_extractor.TDF_LabelSequence", return_value=mock_seq, create=True):
        results = extract_surface_finish(doc)
        assert results == []
