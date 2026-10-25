"""ProcessAnalyzer protocol + module-level registry.

Phase 2 will drop one class per ProcessType into the additive/subtractive/
formative subpackages. Each class is decorated with @register so it becomes
discoverable via get_analyzer(ProcessType). routes.py dispatches through
this registry; any process without a registered class falls through to the
legacy function-based analyzer adapter until the new class ships.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType


@runtime_checkable
class ProcessAnalyzer(Protocol):
    """Contract every real analyzer must satisfy.

    Attributes:
        process: the ProcessType this analyzer owns.
        standards: citations (AMS / ASTM / ISO / NADCA / NACE / API / OEM)
            that inform this analyzer's thresholds. Emitted in the response
            audit trail so enterprise customers can verify every check.
    """

    process: ProcessType
    standards: list[str]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        ...


_REGISTRY: dict[ProcessType, ProcessAnalyzer] = {}


def register(cls: type) -> type:
    """Class decorator that instantiates and registers an analyzer."""
    instance = cls()
    if not isinstance(instance, ProcessAnalyzer):
        raise TypeError(
            f"{cls.__name__} does not satisfy the ProcessAnalyzer protocol "
            "(missing `process`, `standards`, or `analyze`)"
        )
    raw = instance.analyze

    def analyze(ctx: GeometryContext, _raw=raw) -> list[Issue]:
        issues = _raw(ctx)
        count_cad_faces(issues, ctx)
        return issues

    instance.analyze = analyze
    _REGISTRY[instance.process] = instance
    return cls


def count_cad_faces(issues: list[Issue], ctx: GeometryContext) -> list[Issue]:
    """Give each finding the CAD faces its triangles lie on (STEP/IGES meshed by ScaleCAD).

    A STEP's 11 faces are the faces its CAD tool shows; the 247,114 triangles
    ScaleCAD meshed them into are not. Left unset for an STL (it has no faces
    but triangles) or when the mesh no longer lines up with the B-rep.
    """
    try:
        ids = ctx.cad_face_ids
    except Exception:
        ids = None
    if ids is None:
        return issues
    for issue in issues:
        if issue.affected_faces and issue.cad_face_count is None:
            faces = np.asarray(issue.affected_faces, dtype=np.int64)
            faces = faces[(faces >= 0) & (faces < len(ids))]
            if len(faces):
                issue.cad_face_count = int(len(np.unique(ids[faces])))
    return issues


def get_analyzer(process: ProcessType) -> ProcessAnalyzer | None:
    """Return the analyzer for a process, or None if not yet registered."""
    return _REGISTRY.get(process)


def registered_processes() -> list[ProcessType]:
    """List every ProcessType that has a registered analyzer."""
    return list(_REGISTRY.keys())


def clear_registry() -> None:
    """Test helper: drop all registered analyzers. Do not call in production."""
    _REGISTRY.clear()
