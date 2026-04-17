"""Tolerance data model for GD&T/PMI extraction (ISO 1101 types).

Defines structured representations of geometric tolerances, datums,
dimensional tolerances, and surface finish annotations extracted from
STEP AP242 PMI data. Used by the GD&T extractor and downstream
achievability analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.analysis.models import ProcessType


class ToleranceType(str, Enum):
    """ISO 1101 geometric tolerance types (14 categories)."""

    # Form tolerances
    FLATNESS = "flatness"
    STRAIGHTNESS = "straightness"
    CIRCULARITY = "circularity"
    CYLINDRICITY = "cylindricity"

    # Orientation tolerances
    PARALLELISM = "parallelism"
    PERPENDICULARITY = "perpendicularity"
    ANGULARITY = "angularity"

    # Location tolerances
    POSITION = "position"
    CONCENTRICITY = "concentricity"
    SYMMETRY = "symmetry"

    # Profile tolerances
    PROFILE_OF_SURFACE = "profile_of_surface"
    PROFILE_OF_LINE = "profile_of_line"

    # Runout tolerances
    CIRCULAR_RUNOUT = "circular_runout"
    TOTAL_RUNOUT = "total_runout"


class AchievabilityVerdict(str, Enum):
    """Whether a tolerance can be achieved by a given manufacturing process."""

    ACHIEVABLE = "achievable"
    MARGINAL = "marginal"
    NOT_ACHIEVABLE = "not_achievable"


@dataclass
class ToleranceEntry:
    """A single geometric tolerance extracted from PMI data.

    Attributes:
        tolerance_id: Auto-generated ID (e.g., "TOL-001").
        tolerance_type: ISO 1101 tolerance category.
        value_mm: Tolerance zone width in millimeters.
        upper_deviation: Upper deviation (for dimensional tolerances).
        lower_deviation: Lower deviation (for dimensional tolerances).
        datum_refs: Datum reference labels (e.g., ["A", "B"]).
        feature_description: Human-readable description of the toleranced feature.
        surface_finish_ra_um: Surface finish Ra in micrometers, if associated.
    """

    tolerance_id: str
    tolerance_type: ToleranceType
    value_mm: float
    upper_deviation: float | None = None
    lower_deviation: float | None = None
    datum_refs: list[str] = field(default_factory=list)
    feature_description: str = ""
    surface_finish_ra_um: float | None = None


@dataclass
class ToleranceAchievability:
    """Achievability assessment of a tolerance for a specific process.

    Attributes:
        tolerance_id: References ToleranceEntry.tolerance_id.
        process: Manufacturing process assessed.
        verdict: Whether the tolerance is achievable.
        process_capability_mm: Best tolerance the process can hold (mm).
        margin_mm: Positive = achievable with room, negative = not achievable.
    """

    tolerance_id: str
    process: ProcessType
    verdict: AchievabilityVerdict
    process_capability_mm: float
    margin_mm: float


@dataclass
class ToleranceReport:
    """Complete tolerance extraction and achievability report.

    Attributes:
        has_pmi: Whether the source document contained PMI data.
        pmi_note: Optional note about PMI quality or completeness.
        tolerances: Extracted tolerance entries.
        achievability: Per-tolerance, per-process achievability assessments.
        summary_score: Overall tolerance achievability score (0-100).
    """

    has_pmi: bool
    pmi_note: str | None = None
    tolerances: list[ToleranceEntry] = field(default_factory=list)
    achievability: list[ToleranceAchievability] = field(default_factory=list)
    summary_score: float = 0.0
