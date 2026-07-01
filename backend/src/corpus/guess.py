"""Optional, engine-independent ``process_family_guess`` heuristic (spec §2.7).

This is a deliberately **simple, documented, weak** heuristic used ONLY to drive a
coverage dashboard (which manufacturing families look thin) so the gatherer can
deliberately add diversity. It is tagged ``source: "heuristic_v1"`` and stamped as
an UNVERIFIED HEURISTIC.

Hard rules it must honor:
- It is **NOT** a label. The ground-truth ``label`` is human-applied only.
- It is **independent of the routing engine** (does not import the analyzers /
  ``rank_processes``) — using the engine here would make the eval circular.

It derives a family guess from raw geometry only: sorted bbox dims, watertightness,
and convex-hull solidity. Returns one of the 5 manufacturable family keys.
"""

from __future__ import annotations

from typing import Optional

import trimesh

from src.analysis.models import GeometryInfo

_NOTE = "UNVERIFIED HEURISTIC — not a label, not for metrics"


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def process_family_guess(mesh: trimesh.Trimesh, geo: GeometryInfo) -> Optional[dict]:
    """Best-effort family guess from raw geometry. Never a label (spec §2.7)."""
    dims = sorted((float(d) for d in geo.bounding_box.dimensions), reverse=True)
    if len(dims) != 3 or dims[0] <= 0.0:
        return None
    d1, d2, d3 = dims  # d1 >= d2 >= d3
    watertight = bool(geo.is_watertight)

    # Convex-hull solidity is robust even when the mesh is not watertight for the
    # hull itself; geo.volume is 0.0 for non-watertight meshes (engine convention).
    try:
        hull_vol = float(mesh.convex_hull.volume)
    except Exception:
        hull_vol = 0.0
    vol = abs(float(geo.volume))
    solidity = _clip(vol / hull_vol, 0.0, 1.0) if hull_vol > 1e-9 else 0.0

    min_over_median = d3 / d2 if d2 > 0 else 1.0
    squareness = d2 / d1            # 1.0 == as wide as it is long
    thirdness = d3 / d1

    # sheet-ish: one dim << other two, and a closed thin shell -> sheet_metal
    if min_over_median < 0.12 and watertight:
        family = "sheet_metal"
    # blocky/solid: fills its convex hull -> machined-from-stock lean (subtractive)
    elif solidity > 0.6:
        family = "subtractive"
    # chunky cube/round prism, reasonably solid -> subtractive lean
    elif watertight and solidity > 0.35 and squareness > 0.85 and thirdness > 0.7:
        family = "subtractive"
    # shelled / thin / non-watertight print-shaped -> additive (also the default)
    else:
        family = "additive"

    return {"family": family, "source": "heuristic_v1", "note": _NOTE}
