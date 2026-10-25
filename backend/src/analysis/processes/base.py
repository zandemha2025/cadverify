"""ProcessAnalyzer protocol + module-level registry.

Phase 2 will drop one class per ProcessType into the additive/subtractive/
formative subpackages. Each class is decorated with @register so it becomes
discoverable via get_analyzer(ProcessType). routes.py dispatches through
this registry; any process without a registered class falls through to the
legacy function-based analyzer adapter until the new class ships.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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
    _REGISTRY[instance.process] = instance
    return cls


def get_analyzer(process: ProcessType) -> ProcessAnalyzer | None:
    """Return the analyzer for a process, or None if not yet registered."""
    return _REGISTRY.get(process)


def registered_processes() -> list[ProcessType]:
    """List every ProcessType that has a registered analyzer."""
    return list(_REGISTRY.keys())


def clear_registry() -> None:
    """Test helper: drop all registered analyzers. Do not call in production."""
    _REGISTRY.clear()
