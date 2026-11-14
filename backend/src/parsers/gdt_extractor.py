"""GD&T/PMI extraction from STEP AP242 documents using OCP XDE DimTolTool.

Reads an AP242Document's geometric tolerances, dimensional tolerances, datum
references and surface finish annotations into structured ToleranceEntry
objects for downstream achievability analysis.

OCCT keeps each annotation as an attribute on its own label
(XCAFDoc_GeomTolerance, XCAFDoc_Dimension, XCAFDoc_Datum); the DimTolTool only
enumerates the labels. This module is written against that API as shipped in
cadquery-ocp 7.9.x. tests/test_gdt_extractor.py runs it on a real NIST AP242
file, because a mock of the binding cannot tell when the binding moves: the
previous version called tool methods (GetGDTLabels, GetGeomTolerance,
GetRefDatum) that this OCP does not have, and its mocked tests stayed green.

Feature-gated: gracefully degrades when OCP XDE modules are not installed.
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any, Callable, TYPE_CHECKING

from src.analysis.tolerance_models import ToleranceEntry, ToleranceType

if TYPE_CHECKING:
    from src.parsers.step_ap242_parser import AP242Document

logger = logging.getLogger("cadverify.gdt_extractor")

# ── Feature gate: OCP XDE DimTol modules ──────────────────────
_HAS_XDE = False
XCAFDoc_DimTolTool: Any = None
XCAFDoc_GeomTolerance: Any = None
XCAFDoc_Dimension: Any = None
XCAFDoc_Datum: Any = None
TDF_LabelSequence: Any = None
try:
    _xcaf_doc = importlib.import_module("OCP.XCAFDoc")
    XCAFDoc_DimTolTool = getattr(_xcaf_doc, "XCAFDoc_DimTolTool")
    XCAFDoc_GeomTolerance = getattr(_xcaf_doc, "XCAFDoc_GeomTolerance")
    XCAFDoc_Dimension = getattr(_xcaf_doc, "XCAFDoc_Dimension")
    XCAFDoc_Datum = getattr(_xcaf_doc, "XCAFDoc_Datum")
    TDF_LabelSequence = getattr(importlib.import_module("OCP.TDF"), "TDF_LabelSequence")

    _HAS_XDE = True
except (ImportError, AttributeError):
    pass

# ── OCP GeomToleranceType name → ToleranceType ────────────────
# Keyed by the enum member's NAME, lower-cased with underscores removed. The
# integer values differ between OCCT releases (Position is 10 in 7.9, not 7),
# so they are never used.
_GEOM_TYPE_BY_NAME: dict[str, ToleranceType] = {
    "flatness": ToleranceType.FLATNESS,
    "straightness": ToleranceType.STRAIGHTNESS,
    "circularity": ToleranceType.CIRCULARITY,
    "roundness": ToleranceType.CIRCULARITY,
    "circularityorroundness": ToleranceType.CIRCULARITY,
    "cylindricity": ToleranceType.CYLINDRICITY,
    "parallelism": ToleranceType.PARALLELISM,
    "perpendicularity": ToleranceType.PERPENDICULARITY,
    "angularity": ToleranceType.ANGULARITY,
    "position": ToleranceType.POSITION,
    "concentricity": ToleranceType.CONCENTRICITY,
    "coaxiality": ToleranceType.CONCENTRICITY,
    "symmetry": ToleranceType.SYMMETRY,
    "profileofsurface": ToleranceType.PROFILE_OF_SURFACE,
    "profileofasurface": ToleranceType.PROFILE_OF_SURFACE,
    "profileofline": ToleranceType.PROFILE_OF_LINE,
    "profileofaline": ToleranceType.PROFILE_OF_LINE,
    "circularrunout": ToleranceType.CIRCULAR_RUNOUT,
    "totalrunout": ToleranceType.TOTAL_RUNOUT,
}

_RA = re.compile(r"\bra\b", re.IGNORECASE)


def _enum_name(raw: Any) -> str:
    """An OCP enum member (or its name) as a bare lower-case word.

    ``XCAFDimTolObjects_GeomToleranceType.XCAFDimTolObjects_GeomToleranceType_ProfileOfSurface``
    and ``profile_of_surface`` both become ``profileofsurface``.
    """
    return str(raw).rsplit("Type_", 1)[-1].replace("_", "").strip().lower()


def _resolve_tolerance_type(raw_type: Any) -> ToleranceType | None:
    """The ISO 1101 type an OCP geometric tolerance type names, or None."""
    if raw_type is None:
        return None
    return _GEOM_TYPE_BY_NAME.get(_enum_name(raw_type))


# ── OCP access (the only functions that touch the binding) ────


def _labels(fill: Callable[[Any], Any]) -> list[Any]:
    """The labels a DimTolTool enumerator (``tool.GetDimensionLabels``…) yields."""
    seq = TDF_LabelSequence()
    fill(seq)
    return [seq.Value(i) for i in range(1, seq.Length() + 1)]


def _geom_tolerance_object(label: Any) -> Any:
    # Set_s is OCAF's find-or-add: on a label the tool enumerated as a geometric
    # tolerance it returns the attribute already there.
    return XCAFDoc_GeomTolerance.Set_s(label).GetObject()


def _dimension_object(label: Any) -> Any:
    return XCAFDoc_Dimension.Set_s(label).GetObject()


def _ascii(value: Any) -> str:
    """A TCollection string handle (or None) as text."""
    if value is None:
        return ""
    to_c = getattr(value, "ToCString", None)
    return str(to_c() if callable(to_c) else value).strip()


def _datum_name(label: Any) -> str:
    return _ascii(XCAFDoc_Datum.Set_s(label).GetObject().GetName())


def _datum_refs(tol_label: Any) -> list[str]:
    """The datum letters a tolerance references, in order, without repeats."""
    refs: list[str] = []
    try:
        seq = TDF_LabelSequence()
        if not XCAFDoc_DimTolTool.GetDatumOfTolerLabels_s(tol_label, seq):
            return refs
        for i in range(1, seq.Length() + 1):
            name = _datum_name(seq.Value(i))
            if name and name not in refs:
                refs.append(name)
    except Exception as exc:
        logger.debug("Could not read datum references: %s", exc)
    return refs


# ── Extraction ────────────────────────────────────────────────


def _geom_entry(label: Any) -> ToleranceEntry | None:
    """A geometric tolerance as an entry; None when the file gives it no value.

    Some AP242 files carry a tolerance as graphics only (the frame is drawn, the
    zone width is not stored semantically). There is no number to report or to
    check a process against, so such a tolerance is counted by the caller, never
    reported as a zero.
    """
    obj = _geom_tolerance_object(label)
    raw_type = obj.GetType()
    tol_type = _resolve_tolerance_type(raw_type)
    if tol_type is None:
        raise ValueError(f"unrecognized geometric tolerance type {raw_type}")
    value_mm = float(obj.GetValue() or 0.0)
    if value_mm <= 0:
        return None
    return ToleranceEntry(
        tolerance_id="",  # filled by caller
        tolerance_type=tol_type,
        value_mm=value_mm,
        datum_refs=_datum_refs(label),
        feature_description=_ascii(obj.GetSemanticName()),
    )


def _dimension_entry(label: Any) -> ToleranceEntry | None:
    """A toleranced dimension as an entry; None for a dimension with no tolerance.

    A plus/minus dimension keeps its deviations as magnitudes (35 +0/-0.2 is
    upper 0.0, lower 0.2); a range dimension keeps its two bounds.
    """
    obj = _dimension_object(label)
    if obj.IsDimWithPlusMinusTolerance():
        upper = float(obj.GetUpperTolValue() or 0.0)
        lower = -abs(float(obj.GetLowerTolValue() or 0.0))
        nominal = float(obj.GetValue() or 0.0)
    elif obj.IsDimWithRange():
        low_bound = float(obj.GetLowerBound())
        high_bound = float(obj.GetUpperBound())
        nominal = (low_bound + high_bound) / 2
        upper = high_bound - nominal
        lower = low_bound - nominal
    else:
        return None
    # Six decimals of a millimetre is far below any drawing tolerance and drops
    # the float noise a range's midpoint leaves; "+ 0.0" also clears a -0.0.
    upper = round(upper, 6) + 0.0
    lower = round(lower, 6) + 0.0
    spread = round(upper - lower, 6)
    if spread <= 0:
        return None

    kind = _enum_name(obj.GetType())
    unit = "mm"
    if "angular" in kind:
        tol_type, unit, description = ToleranceType.ANGULAR_SIZE, "deg", f"{nominal:g}°"
    elif "diameter" in kind:
        tol_type, description = ToleranceType.DIAMETER, f"⌀{nominal:g} mm"
    else:
        tol_type, description = ToleranceType.LINEAR_SIZE, f"{nominal:g} mm"
    return ToleranceEntry(
        tolerance_id="",
        tolerance_type=tol_type,
        value_mm=spread,
        upper_deviation=upper,
        lower_deviation=lower,
        feature_description=description,
        unit=unit,
    )


def extract_gdt(
    ap242_doc: AP242Document,
) -> tuple[list[ToleranceEntry], list[str]]:
    """Extract the tolerances an AP242 document's PMI carries.

    Reads geometric tolerances (with their datum references) and toleranced
    dimensions. One annotation failing is recorded as a warning and the rest
    are still read (partial extraction).

    Args:
        ap242_doc: Parsed AP242 document with dim_tol_tool.

    Returns:
        Tuple of (successfully extracted tolerances, warning messages).
    """
    tolerances: list[ToleranceEntry] = []
    warnings: list[str] = []

    if not _HAS_XDE:
        warnings.append("OCP XDE modules not available — GD&T extraction skipped")
        return tolerances, warnings

    dim_tol_tool = ap242_doc.dim_tol_tool
    if dim_tol_tool is None:
        warnings.append("No DimTolTool found in document")
        return tolerances, warnings

    geom_labels = _labels(dim_tol_tool.GetGeomToleranceLabels)
    dimension_labels = _labels(dim_tol_tool.GetDimensionLabels)
    if not geom_labels and not dimension_labels:
        logger.info("No tolerance annotations found in AP242 document")
        return tolerances, warnings

    logger.info(
        "Found %d geometric tolerance and %d dimension labels in AP242 document",
        len(geom_labels),
        len(dimension_labels),
    )

    counter = 0
    without_value = 0
    for read, labels in ((_geom_entry, geom_labels), (_dimension_entry, dimension_labels)):
        for index, label in enumerate(labels, start=1):
            try:
                entry = read(label)
            except Exception as exc:
                counter += 1
                msg = f"TOL-{counter:03d}: Failed to extract annotation at label index {index}: {exc}"
                logger.warning(msg)
                warnings.append(msg)
                continue
            if entry is None:
                if read is _geom_entry:
                    without_value += 1
                continue
            counter += 1
            entry.tolerance_id = f"TOL-{counter:03d}"
            tolerances.append(entry)

    if without_value:
        warnings.append(
            f"{without_value} geometric tolerance{'s are' if without_value != 1 else ' is'} "
            "drawn in this file without a stored value and could not be read"
        )

    logger.info("Extracted %d tolerances with %d warnings", len(tolerances), len(warnings))
    return tolerances, warnings


def extract_surface_finish(
    ap242_doc: AP242Document,
) -> list[tuple[str, float]]:
    """Extract surface finish (Ra) annotations from AP242 PMI data.

    AP242 has no dedicated roughness entity in XDE; exporters that carry Ra put
    it on a dimension whose description names it. Only a description that says
    "Ra" as a word counts.

    Args:
        ap242_doc: Parsed AP242 document.

    Returns:
        List of (feature_description, ra_um) tuples. Empty if no
        surface finish annotations are found.
    """
    results: list[tuple[str, float]] = []

    if not _HAS_XDE:
        logger.debug("OCP XDE not available — surface finish extraction skipped")
        return results

    dim_tol_tool = ap242_doc.dim_tol_tool
    if dim_tol_tool is None:
        return results

    try:
        for label in _labels(dim_tol_tool.GetDimensionLabels):
            try:
                obj = _dimension_object(label)
                if not obj.HasDescriptions():
                    continue
                for n in range(int(obj.NbDescriptions())):
                    text = f"{_ascii(obj.GetDescriptionName(n))} {_ascii(obj.GetDescription(n))}".strip()
                    value = float(obj.GetValue() or 0.0)
                    if _RA.search(text) and value > 0:
                        results.append((text, value))
            except Exception:
                continue
    except Exception as exc:
        logger.debug("Surface finish extraction failed: %s", exc)

    logger.info("Extracted %d surface finish annotations", len(results))
    return results
