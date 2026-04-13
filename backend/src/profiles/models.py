"""Profile data models for machines, materials, and processes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.analysis.models import ProcessType


@dataclass
class MaterialProfile:
    name: str
    process_types: list[ProcessType]
    min_wall_thickness: float          # mm
    max_temperature: Optional[float]   # °C
    tensile_strength: Optional[float]  # MPa
    elongation: Optional[float]        # %
    density: Optional[float]           # g/cm³
    cost_per_kg: Optional[float]       # USD/kg (approximate)
    notes: str = ""
    # Enhanced DFM fields (v2)
    alloy_designation: Optional[str] = None
    standards: list[str] = field(default_factory=list)
    compliance: dict[str, bool] = field(default_factory=dict)
    min_wall_by_process: dict[str, float] = field(default_factory=dict)
    machinability_index: Optional[float] = None
    thermal_conductivity: Optional[float] = None  # W/m·K
    hardness_hrc: Optional[float] = None


@dataclass
class MachineProfile:
    name: str
    manufacturer: str
    process_type: ProcessType
    build_volume: tuple[float, float, float]  # X, Y, Z in mm
    min_layer_height: Optional[float] = None  # mm (additive)
    max_layer_height: Optional[float] = None  # mm (additive)
    resolution_xy: Optional[float] = None     # mm
    materials: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class PrintProfile:
    """Recommended print/manufacturing parameters."""
    process: ProcessType
    material: str
    machine: Optional[str]
    layer_height: Optional[float]       # mm
    infill_percent: Optional[int]       # 0-100
    supports_needed: bool
    estimated_time_hours: Optional[float]
    estimated_cost_usd: Optional[float]
    orientation_suggestion: Optional[str]
    notes: str = ""
