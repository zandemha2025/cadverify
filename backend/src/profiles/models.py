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


# How a catalog machine's ``materials`` were read from its maker.
MAKER_SPEC = "maker_spec"            # the maker's own list or statement
MAKER_DESCRIBED = "maker_described"  # mapped conservatively from what the maker says it's for


@dataclass(frozen=True)
class MakerSpec:
    """What the maker publishes for a catalog machine, and where it says so.

    ``max_workpiece_kg`` is the maker's rated table, workpiece or chuck load.
    ``None`` means the maker publishes none (most printers): it is never
    estimated, and ``kg_note`` says so. ``materials_basis`` says how the
    profile's ``materials`` were read (``MAKER_SPEC`` or ``MAKER_DESCRIBED``),
    with the page in ``materials_url`` (else ``source_url``).
    """

    source_url: str
    max_workpiece_kg: Optional[float] = None
    kg_note: str = ""
    materials_basis: Optional[str] = None
    materials_url: Optional[str] = None
    materials_note: str = ""
    checked: str = ""  # ISO date the maker's page was read


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
    spec: Optional[MakerSpec] = None


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
