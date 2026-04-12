"""Deterministic manufacturing-feature recognition.

This package identifies first-class manufacturing features (holes, bosses,
flats, fillets, pockets, ribs, ...) from a raw triangle mesh. Analyzers in
src.analysis.processes.* consume these features instead of raw face arrays
so their checks can reason about intent ("this hole is 10mm deep") rather
than geometry ("these 47 triangles are curved").
"""

from src.analysis.features.base import Feature, FeatureKind
from src.analysis.features.detector import detect_all

__all__ = ["Feature", "FeatureKind", "detect_all"]
