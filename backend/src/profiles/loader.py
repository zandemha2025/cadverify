"""YAML-based material database loader.

Loads structured material definitions from YAML files in the materials/
directory and merges them with the hardcoded MATERIALS list for backward
compatibility.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from src.analysis.models import ProcessType
from src.profiles.models import MaterialProfile

logger = logging.getLogger(__name__)

_MATERIALS_DIR = Path(__file__).parent / "materials"

# Map YAML process strings to ProcessType enum values
_PROCESS_MAP: dict[str, ProcessType] = {pt.value: pt for pt in ProcessType}


def _parse_yaml_material(data: dict) -> MaterialProfile:
    """Convert a parsed YAML dict into a MaterialProfile."""
    mech = data.get("mechanical", {})
    dfm = data.get("dfm", {})
    compliance_raw = data.get("compliance", {})

    # Build process_types list from YAML process strings
    process_types: list[ProcessType] = []
    for p in data.get("processes", []):
        pt = _PROCESS_MAP.get(p)
        if pt is not None:
            process_types.append(pt)
        else:
            logger.warning("Unknown process type '%s' in material '%s'", p, data.get("name"))

    # Resolve cost_per_kg: use first available value from cost dict
    cost_data = dfm.get("cost_per_kg_usd", {})
    cost_per_kg: Optional[float] = None
    if isinstance(cost_data, dict) and cost_data:
        cost_per_kg = next(iter(cost_data.values()))
    elif isinstance(cost_data, (int, float)):
        cost_per_kg = float(cost_data)

    # Normalize compliance to dict[str, bool] (filter out non-bool entries like lists)
    compliance: dict[str, bool] = {}
    for k, v in compliance_raw.items():
        if isinstance(v, bool):
            compliance[k] = v

    return MaterialProfile(
        name=data["name"],
        process_types=process_types,
        min_wall_thickness=dfm.get("min_wall_mm", 1.0),
        max_temperature=mech.get("max_temperature_c"),
        tensile_strength=mech.get("tensile_mpa"),
        elongation=mech.get("elongation_pct"),
        density=mech.get("density_g_cm3"),
        cost_per_kg=cost_per_kg,
        notes=data.get("notes", ""),
        alloy_designation=data.get("alloy_designation"),
        standards=data.get("standards", []),
        compliance=compliance,
        min_wall_by_process=dfm.get("min_wall_by_process", {}),
        machinability_index=mech.get("machinability_index"),
        thermal_conductivity=mech.get("thermal_conductivity_w_mk"),
        hardness_hrc=mech.get("hardness_hrc"),
    )


def load_yaml_materials() -> list[MaterialProfile]:
    """Load all YAML material files from the materials directory.

    Returns an empty list if PyYAML is not installed or the directory
    does not exist.
    """
    try:
        import yaml  # noqa: F811
    except ImportError:
        logger.info("PyYAML not installed; skipping YAML material loading")
        return []

    if not _MATERIALS_DIR.is_dir():
        logger.info("Materials directory not found: %s", _MATERIALS_DIR)
        return []

    materials: list[MaterialProfile] = []
    for filepath in sorted(_MATERIALS_DIR.glob("*.yaml")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and isinstance(data, dict):
                mat = _parse_yaml_material(data)
                materials.append(mat)
        except Exception:
            logger.exception("Failed to load material from %s", filepath.name)

    logger.info("Loaded %d materials from YAML files", len(materials))
    return materials


def merge_materials(
    hardcoded: list[MaterialProfile],
    yaml_materials: list[MaterialProfile],
) -> list[MaterialProfile]:
    """Merge YAML materials into the hardcoded list.

    YAML entries override hardcoded entries with the same name (case-insensitive).
    Hardcoded entries not present in YAML are preserved.
    YAML entries not present in hardcoded are appended.
    """
    # Index yaml materials by lowercase name for override lookup
    yaml_by_name: dict[str, MaterialProfile] = {
        m.name.lower(): m for m in yaml_materials
    }

    merged: list[MaterialProfile] = []
    seen_names: set[str] = set()

    # Walk hardcoded list; replace with YAML version if available
    for hc in hardcoded:
        key = hc.name.lower()
        if key in yaml_by_name:
            merged.append(yaml_by_name[key])
        else:
            merged.append(hc)
        seen_names.add(key)

    # Append YAML-only materials not in the hardcoded list
    for ym in yaml_materials:
        if ym.name.lower() not in seen_names:
            merged.append(ym)
            seen_names.add(ym.name.lower())

    return merged


# Eagerly load at import time
_YAML_MATERIALS: list[MaterialProfile] = load_yaml_materials()

#: Structured materials from YAML only (for new code that wants rich data)
MATERIALS_STRUCTURED: list[MaterialProfile] = list(_YAML_MATERIALS)
