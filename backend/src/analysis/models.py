"""Data models for analysis results across all manufacturing processes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.analysis.tolerance_models import ToleranceReport


class Severity(str, Enum):
    ERROR = "error"        # Cannot manufacture — must fix
    WARNING = "warning"    # Can manufacture but quality/reliability risk
    INFO = "info"          # Optimization suggestion


class ProcessType(str, Enum):
    # Additive
    FDM = "fdm"
    SLA = "sla"
    DLP = "dlp"
    SLS = "sls"
    MJF = "mjf"
    DMLS = "dmls"
    SLM = "slm"
    EBM = "ebm"
    BINDER_JET = "binder_jetting"
    DED = "ded"
    WAAM = "waam"
    # Subtractive
    CNC_3AXIS = "cnc_3axis"
    CNC_5AXIS = "cnc_5axis"
    CNC_TURNING = "cnc_turning"
    WIRE_EDM = "wire_edm"
    # Formative
    INJECTION_MOLDING = "injection_molding"
    DIE_CASTING = "die_casting"
    INVESTMENT_CASTING = "investment_casting"
    SAND_CASTING = "sand_casting"
    SHEET_METAL = "sheet_metal"
    FORGING = "forging"


class FeatureType(str, Enum):
    HOLE = "hole"
    BOSS = "boss"
    RIB = "rib"
    FILLET = "fillet"
    CHAMFER = "chamfer"
    POCKET = "pocket"
    SLOT = "slot"
    THIN_WALL = "thin_wall"
    OVERHANG = "overhang"
    CHANNEL = "channel"
    THREAD = "thread"
    FLAT_SURFACE = "flat_surface"
    CURVED_SURFACE = "curved_surface"
    UNKNOWN = "unknown"


@dataclass
class BoundingBox:
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    @property
    def dimensions(self) -> tuple[float, float, float]:
        return (
            self.max_x - self.min_x,
            self.max_y - self.min_y,
            self.max_z - self.min_z,
        )

    @property
    def max_dimension(self) -> float:
        return max(self.dimensions)


@dataclass
class Issue:
    code: str                           # e.g. "THIN_WALL", "NO_DRAFT", "NON_MANIFOLD"
    severity: Severity
    message: str                        # Human-readable description
    process: Optional[ProcessType]      # None = universal, else process-specific
    affected_faces: list[int] = field(default_factory=list)  # Face indices
    region_center: Optional[tuple[float, float, float]] = None
    fix_suggestion: Optional[str] = None
    measured_value: Optional[float] = None    # e.g. actual wall thickness
    required_value: Optional[float] = None    # e.g. minimum wall thickness


@dataclass
class FeatureSegment:
    segment_id: int
    feature_type: FeatureType
    face_indices: list[int]
    centroid: tuple[float, float, float]
    confidence: float = 1.0             # SAM 3D confidence, 1.0 for heuristic


@dataclass
class GeometryInfo:
    vertex_count: int
    face_count: int
    volume: float                       # mm³
    surface_area: float                 # mm²
    bounding_box: BoundingBox
    is_watertight: bool
    is_manifold: bool
    euler_number: int
    center_of_mass: tuple[float, float, float]
    units: str = "mm"                   # Detected or assumed


@dataclass
class ProcessScore:
    process: ProcessType
    score: float                        # 0.0 = impossible, 1.0 = ideal
    verdict: str                        # "pass", "issues", "fail"
    issues: list[Issue] = field(default_factory=list)
    recommended_material: Optional[str] = None
    recommended_machine: Optional[str] = None
    estimated_cost_factor: Optional[float] = None  # Relative cost multiplier


@dataclass
class AnalysisResult:
    filename: str
    file_type: str                      # "stl" or "step"
    geometry: GeometryInfo
    segments: list[FeatureSegment] = field(default_factory=list)
    universal_issues: list[Issue] = field(default_factory=list)
    process_scores: list[ProcessScore] = field(default_factory=list)
    best_process: Optional[ProcessType] = None
    analysis_time_ms: float = 0.0
    tolerances: Optional["ToleranceReport"] = None

    @property
    def overall_verdict(self) -> str:
        if any(i.severity == Severity.ERROR for i in self.universal_issues):
            return "fail"
        if not self.process_scores:
            return "unknown"
        best = max(self.process_scores, key=lambda s: s.score)
        return best.verdict
