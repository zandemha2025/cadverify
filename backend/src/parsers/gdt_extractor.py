"""GD&T/PMI extraction from STEP AP242 documents using OCP XDE DimTolTool.

Traverses an AP242Document's DimTolTool to extract geometric tolerances,
datums, dimensional tolerances, and surface finish annotations. Produces
structured ToleranceEntry objects for downstream achievability analysis.

Feature-gated: gracefully degrades when OCP XDE modules are not installed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.analysis.tolerance_models import ToleranceEntry, ToleranceType

if TYPE_CHECKING:
    from src.parsers.step_ap242_parser import AP242Document

logger = logging.getLogger("cadverify.gdt_extractor")

# ── Feature gate: OCP XDE DimTol modules ──────────────────────
_HAS_XDE = False
try:
    from OCP.XCAFDimTolObjects import (
        XCAFDimTolObjects_GeomToleranceObject,
        XCAFDimTolObjects_DimensionObject,
        XCAFDimTolObjects_DatumObject,
    )
    from OCP.XCAFDoc import XCAFDoc_DimTolTool
    from OCP.TDF import TDF_LabelSequence

    _HAS_XDE = True
except ImportError:
    pass

# ── OCP GeomToleranceType → ToleranceType mapping ─────────────
# Maps OCP integer enum values to our ISO 1101 ToleranceType.
# OCP enum: XCAFDimTolObjects_GeomToleranceType values.
_OCP_TYPE_MAP: dict[int, ToleranceType] = {
    # Form
    0: ToleranceType.FLATNESS,
    1: ToleranceType.STRAIGHTNESS,
    2: ToleranceType.CIRCULARITY,
    3: ToleranceType.CYLINDRICITY,
    # Orientation
    4: ToleranceType.PARALLELISM,
    5: ToleranceType.PERPENDICULARITY,
    6: ToleranceType.ANGULARITY,
    # Location
    7: ToleranceType.POSITION,
    8: ToleranceType.CONCENTRICITY,
    9: ToleranceType.SYMMETRY,
    # Profile
    10: ToleranceType.PROFILE_OF_SURFACE,
    11: ToleranceType.PROFILE_OF_LINE,
    # Runout
    12: ToleranceType.CIRCULAR_RUNOUT,
    13: ToleranceType.TOTAL_RUNOUT,
}

# String-based fallback map for tolerance type name matching
_NAME_TYPE_MAP: dict[str, ToleranceType] = {
    "flatness": ToleranceType.FLATNESS,
    "straightness": ToleranceType.STRAIGHTNESS,
    "circularity": ToleranceType.CIRCULARITY,
    "cylindricity": ToleranceType.CYLINDRICITY,
    "parallelism": ToleranceType.PARALLELISM,
    "perpendicularity": ToleranceType.PERPENDICULARITY,
    "angularity": ToleranceType.ANGULARITY,
    "position": ToleranceType.POSITION,
    "concentricity": ToleranceType.CONCENTRICITY,
    "symmetry": ToleranceType.SYMMETRY,
    "profile_of_a_surface": ToleranceType.PROFILE_OF_SURFACE,
    "profile_of_surface": ToleranceType.PROFILE_OF_SURFACE,
    "profile_of_a_line": ToleranceType.PROFILE_OF_LINE,
    "profile_of_line": ToleranceType.PROFILE_OF_LINE,
    "circular_runout": ToleranceType.CIRCULAR_RUNOUT,
    "total_runout": ToleranceType.TOTAL_RUNOUT,
}


def _resolve_tolerance_type(
    raw_type: int | str | None,
) -> ToleranceType | None:
    """Resolve an OCP tolerance type enum or name to ToleranceType.

    Args:
        raw_type: OCP integer enum value, string name, or None.

    Returns:
        Matching ToleranceType or None if unrecognized.
    """
    if isinstance(raw_type, int):
        return _OCP_TYPE_MAP.get(raw_type)
    if isinstance(raw_type, str):
        return _NAME_TYPE_MAP.get(raw_type.lower().strip())
    return None


def extract_gdt(
    ap242_doc: AP242Document,
) -> tuple[list[ToleranceEntry], list[str]]:
    """Extract GD&T tolerances from an AP242 document's DimTolTool.

    Traverses GDT labels and extracts geometric tolerances, dimensional
    tolerances, and datum references. Individual annotation failures are
    caught and recorded as warnings — extraction continues for remaining
    annotations (partial extraction support).

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

    # Collect GDT labels
    gdt_labels = TDF_LabelSequence()
    dim_tol_tool.GetGDTLabels(gdt_labels)

    if gdt_labels.Length() == 0:
        logger.info("No GDT labels found in AP242 document")
        return tolerances, warnings

    logger.info("Found %d GDT labels in AP242 document", gdt_labels.Length())

    # Collect datum labels for reference resolution
    datum_map: dict[str, str] = {}  # label tag -> datum letter
    _collect_datums(dim_tol_tool, datum_map, warnings)

    tol_counter = 0

    for i in range(1, gdt_labels.Length() + 1):
        label = gdt_labels.Value(i)
        try:
            entry = _extract_single_tolerance(
                dim_tol_tool, label, datum_map
            )
            if entry is not None:
                tol_counter += 1
                entry.tolerance_id = f"TOL-{tol_counter:03d}"
                tolerances.append(entry)
        except Exception as exc:
            tol_counter += 1
            tol_id = f"TOL-{tol_counter:03d}"
            msg = f"{tol_id}: Failed to extract annotation at label index {i}: {exc}"
            logger.warning(msg)
            warnings.append(msg)

    logger.info(
        "Extracted %d tolerances with %d warnings",
        len(tolerances),
        len(warnings),
    )
    return tolerances, warnings


def _collect_datums(
    dim_tol_tool: object,
    datum_map: dict[str, str],
    warnings: list[str],
) -> None:
    """Collect datum label mappings from the DimTolTool.

    Args:
        dim_tol_tool: XCAFDoc_DimTolTool instance.
        datum_map: Output dict mapping label tags to datum letters.
        warnings: Warning accumulator.
    """
    try:
        datum_labels = TDF_LabelSequence()
        dim_tol_tool.GetDatumLabels(datum_labels)

        for i in range(1, datum_labels.Length() + 1):
            try:
                label = datum_labels.Value(i)
                datum_obj = XCAFDimTolObjects_DatumObject()
                if dim_tol_tool.GetDatum(label, datum_obj):
                    name = str(datum_obj.GetName()) if datum_obj.GetName() else ""
                    tag = str(label.Tag()) if hasattr(label, "Tag") else str(i)
                    if name:
                        datum_map[tag] = name
            except Exception as exc:
                warnings.append(f"Failed to extract datum at index {i}: {exc}")
    except Exception as exc:
        warnings.append(f"Failed to enumerate datum labels: {exc}")


def _extract_single_tolerance(
    dim_tol_tool: object,
    label: object,
    datum_map: dict[str, str],
) -> ToleranceEntry | None:
    """Extract a single tolerance entry from a GDT label.

    Attempts geometric tolerance first, then dimensional tolerance.

    Args:
        dim_tol_tool: XCAFDoc_DimTolTool instance.
        label: TDF_Label for this annotation.
        datum_map: Datum letter lookup.

    Returns:
        ToleranceEntry if extraction succeeded, None if label is not
        a tolerance (e.g., a standalone datum).
    """
    # Try geometric tolerance
    geom_tol = XCAFDimTolObjects_GeomToleranceObject()
    if dim_tol_tool.GetGeomTolerance(label, geom_tol):
        raw_type = geom_tol.GetType()
        tol_type = _resolve_tolerance_type(raw_type)
        if tol_type is None:
            tol_type = _resolve_tolerance_type(str(raw_type))
        if tol_type is None:
            logger.warning("Unrecognized tolerance type: %s", raw_type)
            tol_type = ToleranceType.POSITION  # fallback

        value_mm = float(geom_tol.GetValue()) if geom_tol.GetValue() else 0.0

        # Extract datum references
        datum_refs = _extract_datum_refs(dim_tol_tool, label, datum_map)

        # Feature description from label name if available
        desc = ""
        try:
            name = label.GetLabelName() if hasattr(label, "GetLabelName") else ""
            desc = str(name) if name else ""
        except Exception:
            pass

        return ToleranceEntry(
            tolerance_id="",  # filled by caller
            tolerance_type=tol_type,
            value_mm=value_mm,
            datum_refs=datum_refs,
            feature_description=desc,
        )

    # Try dimensional tolerance
    dim_obj = XCAFDimTolObjects_DimensionObject()
    if dim_tol_tool.GetDimension(label, dim_obj):
        upper = None
        lower = None
        value = 0.0

        try:
            upper = float(dim_obj.GetUpperTolValue())
            lower = float(dim_obj.GetLowerTolValue())
            value = abs(upper - lower) if upper is not None and lower is not None else 0.0
        except Exception:
            pass

        return ToleranceEntry(
            tolerance_id="",
            tolerance_type=ToleranceType.POSITION,  # dimensional → position as proxy
            value_mm=value,
            upper_deviation=upper,
            lower_deviation=lower,
            feature_description="Dimensional tolerance",
        )

    # Label is a datum or unrecognized — skip
    return None


def _extract_datum_refs(
    dim_tol_tool: object,
    tol_label: object,
    datum_map: dict[str, str],
) -> list[str]:
    """Extract datum reference letters linked to a tolerance label.

    Args:
        dim_tol_tool: XCAFDoc_DimTolTool instance.
        tol_label: The tolerance's TDF_Label.
        datum_map: Tag-to-letter mapping from _collect_datums.

    Returns:
        List of datum letters (e.g., ["A", "B"]).
    """
    refs: list[str] = []
    try:
        datum_labels = TDF_LabelSequence()
        dim_tol_tool.GetRefDatum(tol_label, datum_labels)
        for i in range(1, datum_labels.Length() + 1):
            datum_label = datum_labels.Value(i)
            tag = str(datum_label.Tag()) if hasattr(datum_label, "Tag") else str(i)
            letter = datum_map.get(tag, chr(64 + i))  # fallback: A, B, C...
            refs.append(letter)
    except Exception as exc:
        logger.debug("Could not extract datum refs: %s", exc)
    return refs


def extract_surface_finish(
    ap242_doc: AP242Document,
) -> list[tuple[str, float]]:
    """Extract surface finish (Ra) annotations from AP242 PMI data.

    Attempts to read surface finish annotations from the document's
    PMI layer. Surface finish is typically encoded as Ra (arithmetic
    average roughness) in micrometers.

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

    # Surface finish annotations are typically stored as dimension annotations
    # with specific subtypes in AP242. Attempt to read them from GDT labels.
    try:
        gdt_labels = TDF_LabelSequence()
        dim_tol_tool.GetGDTLabels(gdt_labels)

        for i in range(1, gdt_labels.Length() + 1):
            try:
                label = gdt_labels.Value(i)
                # Check if this label carries surface finish information
                # OCP stores surface finish as a specific annotation type
                dim_obj = XCAFDimTolObjects_DimensionObject()
                if dim_tol_tool.GetDimension(label, dim_obj):
                    # Check for surface finish qualifier
                    desc = ""
                    try:
                        name = str(dim_obj.GetDescription()) if hasattr(dim_obj, "GetDescription") else ""
                        if name and "ra" in name.lower():
                            value = float(dim_obj.GetValue()) if hasattr(dim_obj, "GetValue") else 0.0
                            if value > 0:
                                results.append((name, value))
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception as exc:
        logger.debug("Surface finish extraction failed: %s", exc)

    logger.info("Extracted %d surface finish annotations", len(results))
    return results
