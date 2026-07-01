"""The 6-button label ontology and the ProcessType -> family map (spec §1.2).

This is the **single source of truth** for the eval taxonomy. The frontend mirrors
the same 6 keys in ``frontend/src/lib/ontology.ts`` and the corpus
``process_family_guess`` uses the same 5 manufacturable keys.

Note the engine's internal 3-family taxonomy (ADDITIVE / SUBTRACTIVE / FORMATIVE)
is **not** the eval taxonomy: FORMATIVE splits into
``injection_molding`` / ``sheet_metal`` / ``casting`` here.
"""

from __future__ import annotations

from src.analysis.models import ProcessType

# The 6 ontology keys, in fixed button order (spec §5.2). ``unsure_other`` is a
# human-only label — the engine never emits it.
LABELS: list[str] = [
    "additive",
    "subtractive",
    "injection_molding",
    "sheet_metal",
    "casting",
    "unsure_other",
]

# The 5 *manufacturable* keys an engine route can map to (everything except the
# human-only "unsure_other"). Confusion-matrix rows/cols use these.
MANUFACTURABLE: list[str] = LABELS[:5]

# Sentinel column for "the engine produced no route" (best_process is None).
NO_ROUTE = "no_route"

# Every one of the 21 ProcessType members -> exactly one manufacturable family.
FAMILY_OF: dict[ProcessType, str] = {
    # ── ADDITIVE -> "additive" (3D Print) ──────────────────────────────
    ProcessType.FDM: "additive",
    ProcessType.SLA: "additive",
    ProcessType.DLP: "additive",
    ProcessType.SLS: "additive",
    ProcessType.MJF: "additive",
    ProcessType.DMLS: "additive",
    ProcessType.SLM: "additive",
    ProcessType.EBM: "additive",
    ProcessType.BINDER_JET: "additive",
    ProcessType.DED: "additive",
    ProcessType.WAAM: "additive",
    # ── SUBTRACTIVE -> "subtractive" (CNC Machining) ───────────────────
    ProcessType.CNC_3AXIS: "subtractive",
    ProcessType.CNC_5AXIS: "subtractive",
    ProcessType.CNC_TURNING: "subtractive",
    ProcessType.WIRE_EDM: "subtractive",
    # ── FORMATIVE splits three ways here ───────────────────────────────
    ProcessType.INJECTION_MOLDING: "injection_molding",
    ProcessType.DIE_CASTING: "injection_molding",
    ProcessType.SHEET_METAL: "sheet_metal",
    ProcessType.INVESTMENT_CASTING: "casting",
    ProcessType.SAND_CASTING: "casting",
    ProcessType.FORGING: "casting",
}

# Fail loudly at import time if a new ProcessType is added but not mapped, so the
# eval can never silently drop a process into an unknown family.
_missing = [p for p in ProcessType if p not in FAMILY_OF]
if _missing:  # pragma: no cover - guards against future enum drift
    raise RuntimeError(
        "ontology.FAMILY_OF is missing a mapping for ProcessType(s): "
        + ", ".join(p.value for p in _missing)
    )


def family_of(process: ProcessType | None) -> str:
    """Return the eval family key for an engine ProcessType.

    ``None`` (engine produced no route) maps to the ``no_route`` sentinel.
    """
    if process is None:
        return NO_ROUTE
    return FAMILY_OF[process]
