"""Canonical JSON serialization for :class:`~src.analysis.models.Issue`.

One source of truth for turning an ``Issue`` into an API dict, shared by the
analysis response (``routes._issue_to_dict``) and the cost view (cost-model DFM
blockers). Centralising it means the two never drift and every consumer sees the
same untruncated face list, structured citation, and honest scope.

Design notes (the four findings-API fixes this file carries):

* **Untruncated faces.** The analyzers no longer clip ``affected_faces`` to 100.
  ``affected_face_count`` is therefore the TRUE total. The serialized
  ``affected_faces_sample`` carries up to ``MAX_SERIALIZED_AFFECTED_FACES``
  indices — large enough that the defect region is recoverable in the 3D
  viewer, bounded so a pathological part cannot bloat the response. When the
  true count exceeds the cap we set ``affected_faces_truncated: true`` — the
  list is capped, never silently dropped (the honest total is always present).
* **Structured citation.** ``issue.citation`` (a :class:`Citation`) serializes
  to ``{standard?, clause?, text?, rule_id?}`` — omitting null fields so an
  uncited issue stays genuinely uncited.
* **Honest scope.** ``scope`` is ``"localized"`` when the finding has faces or a
  region center, else ``"whole_part"`` — unlocalizable findings (DECIMATED_MESH,
  EXCEEDS_BUILD_VOLUME, NOT_ROTATIONALLY_SYMMETRIC, …) are marked as applying to
  the whole part rather than faking a location.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from src.analysis.models import Citation, Issue

# Documented cap on how many affected-face indices ride in a single serialized
# issue. Chosen well above the old 20/100 clips so a defect region is
# reconstructable, yet bounded so worst-case response size stays sane. Override
# only with a matching update to the truncation contract below.
MAX_SERIALIZED_AFFECTED_FACES = 2000


def serialize_citation(citation: Optional[Citation]) -> Optional[dict]:
    """Serialize a Citation to ``{standard?, clause?, text?, rule_id?}`` or None.

    Null fields are dropped so the object never carries empty keys. Returns
    ``None`` when there is no citation OR when the citation parsed to nothing
    inspectable (all fields empty) — no empty object masquerading as a source.
    """
    if citation is None:
        return None
    out: dict = {}
    if citation.standard:
        out["standard"] = citation.standard
    if citation.clause:
        out["clause"] = citation.clause
    if citation.text:
        out["text"] = citation.text
    if citation.rule_id:
        out["rule_id"] = citation.rule_id
    return out or None


def serialize_issue(
    issue: Issue,
    *,
    max_faces: int = MAX_SERIALIZED_AFFECTED_FACES,
) -> dict:
    """Serialize one Issue to a JSON-ready dict (canonical, shared)."""
    d: dict[str, Any] = {
        "code": issue.code,
        "severity": issue.severity.value,
        "message": issue.message,
        "fix_suggestion": issue.fix_suggestion,
    }
    if issue.process:
        d["process"] = issue.process.value

    if issue.affected_faces:
        total = len(issue.affected_faces)
        d["affected_face_count"] = total           # TRUE total (no longer clipped)
        d["affected_faces_sample"] = list(issue.affected_faces[:max_faces])
        if total > max_faces:
            # The list is capped for response size; the honest total is above in
            # affected_face_count, so nothing is silently dropped.
            d["affected_faces_truncated"] = True

    if issue.region_center:
        d["region_center"] = [round(c, 2) for c in issue.region_center]
    if issue.measured_value is not None:
        d["measured_value"] = round(issue.measured_value, 3)
    if issue.required_value is not None:
        d["required_value"] = issue.required_value

    citation = serialize_citation(issue.citation)
    if citation is not None:
        d["citation"] = citation

    # Honest localization: a finding with neither faces nor a region center
    # applies to the whole part; say so rather than inventing a location.
    d["scope"] = "localized" if (issue.affected_faces or issue.region_center) else "whole_part"
    return d


def serialize_wall_thickness(
    wall_thickness: Sequence[float],
    *,
    decimation: Optional[dict] = None,
) -> dict:
    """Serialize the per-face wall-thickness array for an opt-in heatmap.

    ``values[i]`` is the inward-ray wall thickness (mm) of analyzed-mesh face
    ``i`` — the SAME face-index space as ``Issue.affected_faces_sample`` — or
    ``null`` where thickness is uncomputable (open/degenerate face; the engine
    stores ``inf`` there). If the mesh was decimated for analysis, ``n_faces``
    reflects the decimated mesh and ``decimated`` echoes that so a consumer knows
    the indices map to the approximated geometry, not the original upload.
    """
    import numpy as np

    arr = np.asarray(wall_thickness, dtype=float)
    values = [
        (None if not np.isfinite(v) else round(float(v), 4))
        for v in arr.tolist()
    ]
    payload: dict[str, Any] = {
        "n_faces": int(arr.size),
        "units": "mm",
        "values": values,
        "note": (
            "Per-face inward-ray wall thickness aligned to the analyzed mesh "
            "face indices (same index space as issue.affected_faces_sample). "
            "null = uncomputable (open/degenerate face)."
        ),
    }
    if decimation and decimation.get("succeeded"):
        payload["decimated"] = True
        payload["original_faces"] = int(decimation.get("original_faces", 0))
    return payload
