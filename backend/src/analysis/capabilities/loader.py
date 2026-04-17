"""Capability table loader — maps process types to achievable tolerances.

Reads process_tolerances.yaml once, caches in memory, and provides
validation functions for tolerance achievability assessment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.analysis.models import ProcessType

logger = logging.getLogger("cadverify.capability_loader")

_YAML_PATH = Path(__file__).parent / "process_tolerances.yaml"


@dataclass
class ProcessCapability:
    """Achievable tolerance limits for a manufacturing process.

    Attributes:
        achievable_min: Maps tolerance_type value (e.g. "flatness") to
            minimum achievable tolerance zone width in mm.
        ra_min_um: Minimum achievable surface finish Ra in micrometers.
        ra_typical_um: Typical surface finish Ra in micrometers.
    """

    achievable_min: dict[str, float] = field(default_factory=dict)
    ra_min_um: float = 0.0
    ra_typical_um: float = 0.0


_CAPABILITIES: dict[str, ProcessCapability] | None = None


def load_capabilities() -> dict[str, ProcessCapability]:
    """Load and cache process capability tables from YAML.

    Reads process_tolerances.yaml from the same directory, flattens the
    nested category structure into a flat achievable_min dict per process,
    and validates that all 21 ProcessType enum values have entries.

    Returns:
        Dict mapping process type value (str) to ProcessCapability.
    """
    global _CAPABILITIES

    if _CAPABILITIES is not None:
        return _CAPABILITIES

    with open(_YAML_PATH, "r") as f:
        raw = yaml.safe_load(f)

    capabilities: dict[str, ProcessCapability] = {}

    for process_key, sections in raw.items():
        if not isinstance(sections, dict):
            logger.warning("Skipping non-dict entry in YAML: %s", process_key)
            continue

        flat: dict[str, float] = {}
        ra_min = 0.0
        ra_typical = 0.0

        for category, values in sections.items():
            if not isinstance(values, dict):
                continue

            if category == "surface_finish":
                ra_min = float(values.get("ra_min_um", 0.0))
                ra_typical = float(values.get("ra_typical_um", 0.0))
            else:
                # Flatten: form.flatness -> "flatness"
                for tol_name, tol_value in values.items():
                    flat[tol_name] = float(tol_value)

        capabilities[process_key] = ProcessCapability(
            achievable_min=flat,
            ra_min_um=ra_min,
            ra_typical_um=ra_typical,
        )

    # Validate coverage of all ProcessType enum values
    for pt in ProcessType:
        if pt.value not in capabilities:
            logger.warning(
                "No capability entry for ProcessType.%s (%s)",
                pt.name,
                pt.value,
            )

    _CAPABILITIES = capabilities
    return _CAPABILITIES


def get_capability(process_type: ProcessType) -> ProcessCapability | None:
    """Return capability data for a process type, or None if missing.

    Loads capabilities on first call (lazy init).

    Args:
        process_type: Manufacturing process to look up.

    Returns:
        ProcessCapability or None if no entry exists.
    """
    caps = load_capabilities()
    return caps.get(process_type.value)


def validate_tolerance(
    tolerance_value_mm: float,
    process_type: ProcessType,
    tolerance_type_str: str,
) -> tuple[str, float, float]:
    """Assess whether a process can achieve a given tolerance.

    Args:
        tolerance_value_mm: Specified tolerance zone width in mm.
        process_type: Manufacturing process to evaluate.
        tolerance_type_str: Tolerance type name (e.g. "flatness").

    Returns:
        Tuple of (verdict, capability_min, margin) where:
        - verdict: "achievable", "marginal", "not_achievable", or "unknown"
        - capability_min: Process minimum achievable tolerance (mm)
        - margin: tolerance_value_mm - capability_min (positive = room)
    """
    cap = get_capability(process_type)
    if cap is None:
        return ("unknown", 0.0, 0.0)

    capability_min = cap.achievable_min.get(tolerance_type_str)
    if capability_min is None:
        return ("unknown", 0.0, 0.0)

    margin = tolerance_value_mm - capability_min

    if tolerance_value_mm >= capability_min * 2:
        verdict = "achievable"
    elif tolerance_value_mm >= capability_min:
        verdict = "marginal"
    else:
        verdict = "not_achievable"

    return (verdict, capability_min, margin)
