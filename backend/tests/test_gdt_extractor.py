"""Tests for the GD&T/PMI extractor (STEP-02).

Two kinds. The unit tests replace the three functions that touch the OCP
binding (``_labels``, ``_geom_tolerance_object``, ``_dimension_object``) and
check the extractor's own logic. The NIST tests run the real binding on a real
AP242 file: a mock of the binding passes whether or not the binding still has
the methods it mocks, which is how an extractor that crashed on every file
(``GetGDTLabels`` is not in cadquery-ocp 7.9) once shipped green.
"""

from __future__ import annotations

import gzip
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.tolerance_models import ToleranceEntry, ToleranceType
from src.parsers import gdt_extractor
from src.parsers.gdt_extractor import (
    _GEOM_TYPE_BY_NAME,
    _resolve_tolerance_type,
    extract_gdt,
    extract_surface_finish,
)

NIST_CTC_01 = Path(__file__).parent / "assets" / "nist_ctc_01_asme1_ap242-e1.stp.gz"

# ISO 1101's fourteen geometric characteristics; the rest are dimensional.
GEOMETRIC = {
    ToleranceType.FLATNESS, ToleranceType.STRAIGHTNESS, ToleranceType.CIRCULARITY,
    ToleranceType.CYLINDRICITY, ToleranceType.PARALLELISM, ToleranceType.PERPENDICULARITY,
    ToleranceType.ANGULARITY, ToleranceType.POSITION, ToleranceType.CONCENTRICITY,
    ToleranceType.SYMMETRY, ToleranceType.PROFILE_OF_SURFACE, ToleranceType.PROFILE_OF_LINE,
    ToleranceType.CIRCULAR_RUNOUT, ToleranceType.TOTAL_RUNOUT,
}
DIMENSIONAL = {ToleranceType.DIAMETER, ToleranceType.LINEAR_SIZE, ToleranceType.ANGULAR_SIZE}


# ── Type resolution ──────────────────────────────────────────


def test_every_geometric_type_is_reachable_by_name():
    assert set(_GEOM_TYPE_BY_NAME.values()) == GEOMETRIC
    assert set(ToleranceType) == GEOMETRIC | DIMENSIONAL


@pytest.mark.parametrize(
    "raw, expected",
    [
        # As cadquery-ocp 7.9 stringifies its enum members.
        ("XCAFDimTolObjects_GeomToleranceType.XCAFDimTolObjects_GeomToleranceType_Position", ToleranceType.POSITION),
        ("XCAFDimTolObjects_GeomToleranceType.XCAFDimTolObjects_GeomToleranceType_ProfileOfSurface", ToleranceType.PROFILE_OF_SURFACE),
        ("XCAFDimTolObjects_GeomToleranceType.XCAFDimTolObjects_GeomToleranceType_CircularityOrRoundness", ToleranceType.CIRCULARITY),
        ("XCAFDimTolObjects_GeomToleranceType.XCAFDimTolObjects_GeomToleranceType_Coaxiality", ToleranceType.CONCENTRICITY),
        ("profile_of_surface", ToleranceType.PROFILE_OF_SURFACE),
        ("Flatness", ToleranceType.FLATNESS),
    ],
)
def test_type_resolves_by_name(raw, expected):
    assert _resolve_tolerance_type(raw) is expected


@pytest.mark.parametrize("raw", [None, 7, 10, "XCAFDimTolObjects_GeomToleranceType_None", "sizediameter"])
def test_type_never_resolves_from_an_integer_or_a_non_tolerance(raw):
    """The enum's integers differ between OCCT releases (Position is 10 in 7.9), so none is trusted."""
    assert _resolve_tolerance_type(raw) is None


# ── Extraction logic, binding replaced ───────────────────────


def _geom(type_name="Position", value=0.1, semantic=""):
    return SimpleNamespace(
        GetType=lambda: f"XCAFDimTolObjects_GeomToleranceType_{type_name}",
        GetValue=lambda: value,
        GetSemanticName=lambda: semantic,
    )


def _dim(kind="Size_Diameter", nominal=35.0, upper=0.0, lower=0.2, plus_minus=True, bounds=None):
    return SimpleNamespace(
        GetType=lambda: f"XCAFDimTolObjects_DimensionType_{kind}",
        GetValue=lambda: nominal,
        IsDimWithPlusMinusTolerance=lambda: plus_minus,
        IsDimWithRange=lambda: bounds is not None,
        GetUpperTolValue=lambda: upper,
        GetLowerTolValue=lambda: lower,
        GetLowerBound=lambda: bounds[0],
        GetUpperBound=lambda: bounds[1],
    )


def _extract(geoms=(), dims=(), datum_refs=None):
    """Run extract_gdt over objects standing in for what the binding returns."""
    tool = SimpleNamespace(GetGeomToleranceLabels="geom", GetDimensionLabels="dim")

    def obj_or_raise(obj):
        if isinstance(obj, Exception):
            raise obj
        return obj

    with patch.object(gdt_extractor, "_HAS_XDE", True), \
         patch.object(gdt_extractor, "_labels", side_effect=lambda fill: list(geoms) if fill == "geom" else list(dims)), \
         patch.object(gdt_extractor, "_geom_tolerance_object", side_effect=obj_or_raise), \
         patch.object(gdt_extractor, "_dimension_object", side_effect=obj_or_raise), \
         patch.object(gdt_extractor, "_datum_refs", return_value=list(datum_refs or [])):
        return extract_gdt(SimpleNamespace(dim_tol_tool=tool))


@patch("src.parsers.gdt_extractor._HAS_XDE", False)
def test_extract_gdt_no_xde():
    tolerances, warnings = extract_gdt(MagicMock())
    assert tolerances == []
    assert len(warnings) == 1
    assert "not available" in warnings[0].lower()


@patch("src.parsers.gdt_extractor._HAS_XDE", True)
def test_extract_gdt_without_a_dimtol_tool():
    tolerances, warnings = extract_gdt(SimpleNamespace(dim_tol_tool=None))
    assert tolerances == []
    assert warnings == ["No DimTolTool found in document"]


def test_extract_gdt_empty_document():
    assert _extract() == ([], [])


def test_a_geometric_tolerance_keeps_its_type_value_datums_and_name():
    tolerances, warnings = _extract(geoms=[_geom("Position", 0.1, "boss position")], datum_refs=["A", "B"])
    assert warnings == []
    (entry,) = tolerances
    assert entry == ToleranceEntry(
        tolerance_id="TOL-001", tolerance_type=ToleranceType.POSITION, value_mm=0.1,
        datum_refs=["A", "B"], feature_description="boss position",
    )


def test_a_geometric_tolerance_without_a_value_is_counted_not_reported_as_zero():
    tolerances, warnings = _extract(geoms=[_geom("Flatness", 0.0), _geom("Position", 0.0), _geom("Flatness", 0.05)])
    assert [t.value_mm for t in tolerances] == [0.05]
    assert warnings == ["2 geometric tolerances are drawn in this file without a stored value and could not be read"]


def test_one_bad_annotation_does_not_stop_the_rest():
    tolerances, warnings = _extract(geoms=[_geom("Flatness", 0.05), RuntimeError("Corrupted annotation"), _geom("Position", 0.1)])
    assert [t.tolerance_type for t in tolerances] == [ToleranceType.FLATNESS, ToleranceType.POSITION]
    assert len(warnings) == 1
    assert "Failed to extract annotation at label index 2: Corrupted annotation" in warnings[0]


def test_an_unrecognized_type_is_a_warning_never_a_guess():
    tolerances, warnings = _extract(geoms=[_geom("None", 0.1)])
    assert tolerances == []
    assert "unrecognized geometric tolerance type" in warnings[0]


def test_ids_run_in_order_across_geometric_and_dimensional():
    tolerances, _ = _extract(geoms=[_geom("Flatness", 0.05), _geom("Position", 0.1)], dims=[_dim()])
    assert [t.tolerance_id for t in tolerances] == ["TOL-001", "TOL-002", "TOL-003"]


def test_a_plus_minus_diameter_keeps_its_deviations_as_signed_values():
    """35 +0/-0.2 is stored as magnitudes (upper 0.0, lower 0.2)."""
    (entry,), _ = _extract(dims=[_dim("Size_Diameter", 35.0, upper=0.0, lower=0.2)])
    assert entry.tolerance_type is ToleranceType.DIAMETER
    assert (entry.upper_deviation, entry.lower_deviation, entry.value_mm) == (0.0, -0.2, 0.2)
    assert entry.feature_description == "⌀35 mm"
    assert entry.unit == "mm"
    assert str(entry.upper_deviation) == "0.0"  # never -0.0


def test_an_angular_dimension_is_in_degrees():
    (entry,), _ = _extract(dims=[_dim("Location_Angular", 60.0, upper=0.5, lower=0.5)])
    assert entry.tolerance_type is ToleranceType.ANGULAR_SIZE
    assert (entry.unit, entry.value_mm, entry.feature_description) == ("deg", 1.0, "60°")


def test_a_range_dimension_reports_deviations_from_its_midpoint():
    (entry,), _ = _extract(dims=[_dim("Size_Thickness", 0.0, plus_minus=False, bounds=(9.8, 10.2))])
    assert entry.tolerance_type is ToleranceType.LINEAR_SIZE
    assert (entry.upper_deviation, entry.lower_deviation, entry.value_mm) == (0.2, -0.2, 0.4)
    assert entry.feature_description == "10 mm"


@pytest.mark.parametrize(
    "dim",
    [
        _dim("Location_None", 0.0, upper=0.0, lower=0.0, plus_minus=False),  # a basic dimension
        _dim("Size_Diameter", 35.0, upper=0.0, lower=0.0),  # plus/minus, both zero
    ],
)
def test_a_dimension_with_no_tolerance_is_not_a_tolerance(dim):
    assert _extract(dims=[dim]) == ([], [])


# ── Surface finish ───────────────────────────────────────────


@patch("src.parsers.gdt_extractor._HAS_XDE", False)
def test_extract_surface_finish_no_xde():
    assert extract_surface_finish(MagicMock()) == []


def test_extract_surface_finish_needs_ra_as_a_word():
    """"Ra 1.6" is a roughness; "radius" and "diameter" are not."""
    def described(text, value):
        return SimpleNamespace(
            HasDescriptions=lambda: True, NbDescriptions=lambda: 1,
            GetDescriptionName=lambda n: "", GetDescription=lambda n: text, GetValue=lambda: value,
        )
    dims = [described("Ra 1.6", 1.6), described("radius", 5.0), described("diameter", 35.0), SimpleNamespace(HasDescriptions=lambda: False)]
    with patch.object(gdt_extractor, "_HAS_XDE", True), \
         patch.object(gdt_extractor, "_labels", return_value=dims), \
         patch.object(gdt_extractor, "_dimension_object", side_effect=lambda o: o):
        assert extract_surface_finish(SimpleNamespace(dim_tol_tool=SimpleNamespace(GetDimensionLabels="dim"))) == [("Ra 1.6", 1.6)]


# ── The real binding, on a real AP242 file ───────────────────


@pytest.fixture(scope="module")
def nist_ctc_01() -> bytes:
    pytest.importorskip("OCP.XCAFDoc", reason="needs cadquery-ocp (requirements-prod.txt)")
    return gzip.decompress(NIST_CTC_01.read_bytes())


def test_nist_ctc_01_reads_through_the_real_binding(nist_ctc_01):
    """NIST CTC-01 carries its numbers on dimensions; its six feature control frames are graphics only."""
    from src.parsers.step_ap242_parser import parse_ap242_from_bytes

    doc = parse_ap242_from_bytes(nist_ctc_01, "nist_ctc_01_asme1_ap242-e1.stp")
    assert doc.has_pmi

    tolerances, warnings = extract_gdt(doc)

    assert [t.tolerance_id for t in tolerances] == [f"TOL-{n:03d}" for n in range(1, len(tolerances) + 1)]
    by_type = {t: sum(1 for e in tolerances if e.tolerance_type is t) for t in DIMENSIONAL}
    assert by_type == {ToleranceType.DIAMETER: 7, ToleranceType.ANGULAR_SIZE: 1, ToleranceType.LINEAR_SIZE: 0}
    assert all(t.value_mm > 0 and t.upper_deviation >= 0 >= t.lower_deviation for t in tolerances)
    # ⌀35 +0/-0.2, as the drawing gives it.
    assert any((t.feature_description, t.upper_deviation, t.lower_deviation) == ("⌀35 mm", 0.0, -0.2) for t in tolerances)
    assert warnings == ["6 geometric tolerances are drawn in this file without a stored value and could not be read"]
    assert extract_surface_finish(doc) == []


def test_nist_ctc_01_report_lists_dimensions_without_scoring_them(nist_ctc_01):
    """A dimensional tolerance has no ISO 1101 capability row: it is listed, never called unachievable."""
    from src.analysis.models import ProcessType
    from src.services.tolerance_service import analyze_tolerances, tolerance_report_to_dict

    report = tolerance_report_to_dict(
        analyze_tolerances(nist_ctc_01, "nist_ctc_01_asme1_ap242-e1.stp", [ProcessType.CNC_3AXIS, ProcessType.CNC_TURNING])
    )

    assert report["has_pmi"] is True
    assert len(report["entries"]) == 8
    assert all(e["process_verdicts"] == [] for e in report["entries"])
    assert report["summary_score"] == 0.0
    assert [e.get("unit", "mm") for e in report["entries"]].count("deg") == 1
    assert report["pmi_note"] == "6 geometric tolerances are drawn in this file without a stored value and could not be read"
