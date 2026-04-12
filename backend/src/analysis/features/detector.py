"""Feature-detection orchestrator.

Runs every deterministic detector and concatenates results. Phase 2 adds
fillet / chamfer / pocket / rib / thread detectors; they plug in here.
"""

from __future__ import annotations

import trimesh

from src.analysis.features.base import Feature
from src.analysis.features.cylinders import detect_cylinders
from src.analysis.features.flats import detect_flats


def detect_all(mesh: trimesh.Trimesh) -> list[Feature]:
    """Run every registered detector and return a flat feature list."""
    features: list[Feature] = []
    features.extend(detect_flats(mesh))
    features.extend(detect_cylinders(mesh))
    return features
