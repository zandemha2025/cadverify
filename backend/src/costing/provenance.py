"""Provenance model — the tagging *is* the product.

Every number the decision layer emits carries one of four provenance tags so a
manufacturing engineer can trace where it came from:

    MEASURED  — extracted from the CAD (volume, area, bbox). Not assumable.
    USER      — buyer-supplied for THIS quote (quantities, material class, ad-hoc
                rate overrides). Authoritative, overrides the shop default.
    SHOP      — sourced from the ACTIVE calibrated shop profile (this shop's real
                labor/machine/material/margin). The shop's own measured reality.
    DEFAULT   — our stated generic assumption (rate card). Always visible, always
                overridable; the clearly-labeled fallback when no shop is bound.

No naked numbers anywhere in the output: every Driver has a non-empty `source`
string explaining how it was produced (gate G6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Provenance(str, Enum):
    MEASURED = "MEASURED"   # extracted from the CAD — not assumable
    USER = "USER"           # buyer-supplied for this quote — authoritative
    SHOP = "SHOP"           # from the active calibrated shop profile — this shop's reality
    DEFAULT = "DEFAULT"     # our stated assumption — always visible, always overridable


@dataclass
class Driver:
    """A single, fully-traceable quantity feeding a cost or lead-time figure."""

    name: str                       # "material_cost", "machine_cost", "cycle_time", ...
    value: float
    unit: str                       # "kg", "$/hr", "hr", "$", "units", ...
    provenance: Provenance
    source: str                     # how this number was produced — never empty
    error_band_pct: Optional[float] = None   # +/- % for estimated drivers (None = exact)

    def __post_init__(self) -> None:
        if not self.source or not self.source.strip():
            raise ValueError(
                f"Driver {self.name!r} has an empty source — naked numbers are "
                "forbidden (gate G6). Every figure must state its origin."
            )


@dataclass
class CostEstimate:
    """A should-cost for one (process, material, quantity), itemized and summable."""

    process: str
    material: str
    quantity: int
    unit_cost_usd: float            # == sum of line_items.values()
    fixed_cost_usd: float           # setup_labor + tooling (amortized over qty)
    variable_cost_usd: float        # per-unit material + machine + labor (qty-independent)
    drivers: list[Driver]           # every line item, each tagged
    line_items: dict                # {"amortized_fixed":.., "material":.., "machine":.., "labor":..}
    est_error_band_pct: float       # rolled-up band (dominant cost line)
    dfm_ready: bool = True          # engine DFM verdict != "fail"
    dfm_verdict: str = "pass"       # engine verdict: pass | issues | fail
    dfm_score: float = 1.0
    dfm_blockers: list = field(default_factory=list)   # ERROR-severity issue messages
    # Structured counterpart to dfm_blockers: the FULL serialized Issue for each
    # ERROR blocker (code, affected_faces, region_center, measured/required,
    # process, citation, scope) so the cost view can LOCATE a blocker on the
    # part — not just print its message. Same order as dfm_blockers.
    dfm_blocker_details: list = field(default_factory=list)

    def assert_sums(self, tol: float = 0.01) -> None:
        """Hard invariant (gate G3): unit cost == sum of line items, or it is a bug."""
        s = sum(self.line_items.values())
        if abs(self.unit_cost_usd - s) >= tol:
            raise AssertionError(
                f"{self.process}/{self.material} qty {self.quantity}: "
                f"unit_cost {self.unit_cost_usd:.4f} != Σ line_items {s:.4f}"
            )
