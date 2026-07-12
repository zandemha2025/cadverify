"""Feature-detection orchestrator.

Runs every deterministic detector and concatenates results. Phase 2 adds
fillet / chamfer / pocket / rib / thread detectors; they plug in here.
"""

from __future__ import annotations

import trimesh

from src.analysis.features.base import Feature
from src.analysis.features.chamfers import detect_chamfers
from src.analysis.features.cylinders import detect_cylinders
from src.analysis.features.fillets import detect_fillets
from src.analysis.features.flats import detect_flats
from src.analysis.features.threads import infer_tapped_holes


def detect_all(mesh: trimesh.Trimesh) -> list[Feature]:
    """Run every registered detector and return a flat feature list.

    Detection order: flats, cylinders, then chamfers/fillets (both operate
    on the facet graph independently of the cylinder/flat pass). Tapped-hole
    inference runs last and only ever *annotates* existing CYLINDER_HOLE
    features' metadata — it never adds, removes, or reclassifies a feature.
    """
    features: list[Feature] = []
    features.extend(detect_flats(mesh))
    features.extend(detect_cylinders(mesh))
    features.extend(detect_chamfers(mesh))
    features.extend(detect_fillets(mesh))
    infer_tapped_holes(features)
    return features
