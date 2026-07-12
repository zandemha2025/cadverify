"""Sane routing — kills G2 (Inconel-for-plastic, turning-for-brackets).

The engine's score_process picks materials[0] positionally and never checks
rotational fit. The decision layer NEVER reuses recommended_material; it
re-derives a sane material per class and a sane process shortlist.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Optional

from src.analysis.models import ProcessType
from src.analysis.features.base import has_rotational_surface_evidence
from src.costing.makeability import environment_gate
from src.profiles.database import get_materials_for_process
from src.costing.rates import (
    COSTED_PROCESSES,
    MATERIAL_FAMILY,
    RateCard,
    process_family,
)

PT = ProcessType

DIE_CAST_CLASSES = {"aluminum", "steel", "stainless"}
SHEET_METAL_CLASSES = {"aluminum", "steel", "stainless", "copper"}
MAKE_NOW_FAMILIES = {"additive", "subtractive", "fabrication"}


# Inertia-eigenvalue tolerance for the rotational test. MUST match the CNC-turning
# DFM gate — cnc_turning.py calls check_rotational_symmetry(tolerance=0.15) — so
# routing and DFM share ONE definition of "rotational" and can never contradict
# each other (F2: a square lid that scored 0.97 bbox-"roundness" was headlined
# "turnable" while the engine's own DFM hard-failed it for lacking rotational
# symmetry; both now read the same eigenvalues).
ROTATIONAL_INERTIA_TOL = 0.15


def _inertia_axisymmetric(mesh, tolerance: float = ROTATIONAL_INERTIA_TOL) -> bool:
    """Authoritative axisymmetry test — IDENTICAL to the DFM gate
    (checks.check_rotational_symmetry): a part is rotationally symmetric when two
    of its three principal moments of inertia are approximately equal. Routing
    and DFM therefore agree by construction. Returns False (no positive
    rotational evidence) when the mesh / inertia tensor is unavailable, so a part
    is never *claimed* turnable without measured support.
    """
    if mesh is None:
        return False
    try:
        import numpy as np

        eig = np.sort(np.linalg.eigvalsh(mesh.moment_inertia))
        if eig[0] <= 0:
            return False
        ratio_01 = eig[0] / eig[1] if eig[1] > 0 else 0.0
        ratio_12 = eig[1] / eig[2] if eig[2] > 0 else 0.0
        return bool(
            abs(1.0 - ratio_01) < tolerance or abs(1.0 - ratio_12) < tolerance
        )
    except Exception:
        return False


def is_rotational(geometry, mesh=None, features=None):
    """Rotational predicate (spec §5.1) — CONSISTENT with the DFM gate by design.

    A part is routed to turning only when BOTH signals agree:

      1. cross-section roundness + a turnable aspect ratio (the bbox shape IS a
         round, lathe-friendly profile — this is what correctly separates a round
         ring from a flat bracket, which the inertia ratio alone does NOT: a flat
         bracket reads *more* axisymmetric than a ring under the loose eigenvalue
         tolerance), AND
      2. inertia-eigenvalue axisymmetry (`_inertia_axisymmetric`) — the SAME test
         `checks.check_rotational_symmetry` runs for CNC turning, at the SAME 0.15
         tolerance, AND
      3. a measured outer cylindrical surface covering at least 5% of the part's
         surface area. This rejects boxy L brackets and open enclosures whose
         similar extents and inertia moments otherwise mimic a round part.

    Requiring (2) makes `rotational ⟹ the engine's rotational-symmetry DFM check
    passes`, so routing can NEVER headline "turnable" on a part the DFM hard-fails
    for lacking rotational symmetry. That is the F2 fix: an 85×88mm lid scored
    0.97 bbox-roundness (so the old predicate called it rotational) while its DFM
    flagged FAIL on the inertia test — now (2) vetoes it and both agree.

    Returns (rotational: bool, axis_len_mm: float, cross_dia_mm: float).
    """
    d = sorted(geometry.bounding_box.dimensions)          # [d0 <= d1 <= d2]
    candidates = [
        (d[0], d[1], d[2]),   # axis = d0 -> cross (d1, d2)
        (d[1], d[0], d[2]),   # axis = d1 -> cross (d0, d2)
        (d[2], d[0], d[1]),   # axis = d2 -> cross (d0, d1)
    ]
    best = None
    for axis_len, c1, c2 in candidates:
        hi = max(c1, c2)
        roundness = (min(c1, c2) / hi) if hi > 0 else 0.0
        cross_dia = 0.5 * (c1 + c2)
        if best is None or roundness > best[0]:
            best = (roundness, axis_len, cross_dia)
    roundness, axis_len, cross_dia = best
    ld = (axis_len / cross_dia) if cross_dia > 0 else 0.0
    rotational = (
        (roundness >= 0.80)
        and _inertia_axisymmetric(mesh)
        and has_rotational_surface_evidence(
            features, float(getattr(geometry, "surface_area", 0.0) or 0.0)
        )
        and (cross_dia >= 5.0)
        and (0.25 <= ld <= 8.0)
    )
    return rotational, axis_len, cross_dia


def is_long_prismatic_bar(drivers, material_class: str) -> bool:
    """A slender prismatic solid — bar/rod stock. Saw-to-length + turn/3-axis,
    never 5-axis. Gate is DISJOINT from prismatic_block (block_aspect<=4.0),
    sheet_like, rotational, and thin_wall_enclosure so no other shape reclassifies
    (see F4: `d[2]/d[1] >= 4.0` forces `d[2]/d[0] >= 4.0` since d[0]<=d[1], so a
    bar never also qualifies as a compact prismatic_block)."""
    if material_class == "polymer":
        return False
    d = drivers.bbox_mm            # sorted ascending
    if drivers.bbox_volume_cm3 <= 0 or d[1] <= 0:
        return False
    solidity = drivers.volume_cm3 / drivers.bbox_volume_cm3
    bar_aspect = d[2] / d[1]       # longest / MIDDLE extent = slenderness
    cross_max = d[1]               # largest cross-section extent (mm)
    return solidity >= 0.6 and bar_aspect >= 4.0 and cross_max <= 60.0


def material_family(material_name: str) -> Optional[str]:
    return MATERIAL_FAMILY.get(material_name)


# DED/WAAM feedstock is the same family of metal alloys as powder-bed AM, but no
# MaterialProfile row lists DED/WAAM in its process_types — so borrow the metal-AM
# powder-bed / binder-jet pool for the class. This lets DED/WAAM leave feasibility-
# only with a real material $/kg; it is a routing convenience, not a claim that the
# exact alloy row is DED-qualified.
_DED_FEEDSTOCK_PROCS = (PT.DMLS, PT.SLM, PT.EBM, PT.BINDER_JET)


def _material_props(material) -> dict:
    if is_dataclass(material):
        return asdict(material)
    return {
        "name": getattr(material, "name", str(material)),
        "density": getattr(material, "density", None),
    }


def _env_preferred_materials(process: ProcessType, mats: list, env: dict | None) -> list:
    """Return the environment-valid subset when one exists.

    If the declared environment excludes every candidate, keep the original
    candidate pool so the downstream verification block can still cite exactly
    why the chosen route/material is invalid instead of hiding the route.
    """
    if not env or not mats:
        return mats
    props = {m.name: _material_props(m) for m in mats}
    valid, _ = environment_gate([process.value], [m.name for m in mats], env, props)
    valid_names = set(valid.get("materials") or [])
    if not valid_names:
        return mats
    return [m for m in mats if m.name in valid_names]


def _item_env_valid(item: dict, env: dict | None) -> bool:
    if not env:
        return True
    process = item["process"]
    mat = item["material"]
    props = {mat.name: _material_props(mat)}
    valid, _ = environment_gate([process.value], [mat.name], env, props)
    return (
        process.value in set(valid.get("routes") or [])
        and mat.name in set(valid.get("materials") or [])
    )


def select_material(process: ProcessType, material_class: str, rates: RateCard,
                    env: dict | None = None):
    """Cheapest material compatible with (process, material_class) — the sane
    default pick. No positional materials[0]; no superalloy on a polymer part.
    Returns a MaterialProfile or None (process not eligible for this class).
    """
    mats = [
        m for m in get_materials_for_process(process)
        if MATERIAL_FAMILY.get(m.name) == material_class
        and m.density and m.cost_per_kg
    ]
    if not mats and process in (PT.DED, PT.WAAM):
        # no material row declares DED/WAAM — fall back to the metal-AM alloy pool
        # for this class (dedup by name) so the deposition route can be costed.
        seen: set = set()
        for p in _DED_FEEDSTOCK_PROCS:
            for m in get_materials_for_process(p):
                if (m.name not in seen and MATERIAL_FAMILY.get(m.name) == material_class
                        and m.density and m.cost_per_kg):
                    seen.add(m.name)
                    mats.append(m)
    if not mats:
        return None
    mats = _env_preferred_materials(process, mats, env)
    return min(mats, key=lambda m: m.cost_per_kg)


def select_sheet_material(material_class: str, rates: RateCard,
                          env: dict | None = None):
    """Sheet metal is inherently metal. Prefer the requested class when it is a
    sheet family; otherwise fall back to the cheapest sheet stock (by blank cost
    = density × $/kg) as a clearly-stated default. Returns a MaterialProfile."""
    mats = [m for m in get_materials_for_process(PT.SHEET_METAL)
            if m.density and m.cost_per_kg]
    if not mats:
        return None
    in_class = [m for m in mats if MATERIAL_FAMILY.get(m.name) == material_class]
    pool = in_class if in_class else mats
    pool = _env_preferred_materials(PT.SHEET_METAL, pool, env)
    return min(pool, key=lambda m: m.density * m.cost_per_kg)


def _routing_sane(process: ProcessType, material_class: str, drivers) -> bool:
    if process == PT.CNC_TURNING:
        return bool(drivers.rotational)
    if process == PT.INJECTION_MOLDING:
        return material_class == "polymer"
    if process == PT.DIE_CASTING:
        return material_class in DIE_CAST_CLASSES
    if process == PT.SHEET_METAL:
        # only a genuine constant-gauge flat sheet (geometry-gated), never a box
        # or a rotational solid — this is the structural fix for the panel route
        return bool(getattr(drivers, "sheet_like", False))
    if process == PT.CNC_5AXIS and is_long_prismatic_bar(drivers, material_class):
        # F4: a slender bar's ordinary features can trip the 3-axis undercut
        # ERROR while turning is gated out (not rotational) — without this gate
        # 5-axis becomes the cheapest surviving costed route for plain bar stock.
        # Saw-to-length + turn/3-axis is the sane route; 5-axis is never it.
        return False
    return True


def eligible_processes(result, drivers, material_class: str, rates: RateCard,
                       strict_dfm: bool = False, env: dict | None = None):
    """Return the costable shortlist as a list of dicts:

        {process, material, score(ProcessScore)}

    A process is included when it is (a) in COSTED_PROCESSES, (b) routing-sane,
    and (c) material-compatible for the class. DFM verdict is attached but, by
    default, a "fail" verdict does NOT drop the process — it is costed and
    flagged dfm_ready=False with the engine's blocker messages (see note).

    Why relaxed-by-default: the real automotive parts here were modeled for 3D
    printing (no mold draft), so injection molding / die casting hard-fail DFM
    on every part. Dropping them (strict spec §5.3 rule #1) would mean the
    make-vs-buy / tooling-crossover wedge — the whole point of the layer —
    could never be shown on real geometry. Instead we cost the tooling route
    and clearly label it "requires design-for-molding". Set strict_dfm=True to
    get the literal spec §5.3 behavior (drop verdict=='fail').

    Routing-sanity (turning only when rotational; no superalloy on polymer) is
    enforced regardless of strict_dfm — gate G2 holds in both modes.
    """
    by_proc = {ps.process: ps for ps in result.process_scores}

    def build(env_for_materials: dict | None) -> list:
        out = []
        for process in COSTED_PROCESSES:
            ps = by_proc.get(process)
            if ps is None:
                continue
            if not _routing_sane(process, material_class, drivers):
                continue
            if process == PT.SHEET_METAL:
                # sheet metal is always a metal; pick metal stock regardless of the
                # (polymer) default class so the flat-panel route yields a real $.
                mat = select_sheet_material(material_class, rates,
                                            env=env_for_materials)
            else:
                mat = select_material(process, material_class, rates,
                                      env=env_for_materials)
            if mat is None:
                continue
            if strict_dfm and (ps.verdict == "fail" or ps.score <= 0):
                continue
            out.append({"process": process, "material": mat, "score": ps})
        return out

    legacy = build(None)
    if not env:
        return legacy

    # Preserve the legacy shortlist when it already contains at least one valid
    # make-as-is route. That keeps excluded alternatives visible and cited. If the
    # legacy cheapest-by-class picks would leave the user with no environment-valid
    # make route (the sour-service stainless failure), re-rank materials within
    # each process against the declared environment.
    has_env_valid_make = any(
        process_family(item["process"]) in MAKE_NOW_FAMILIES
        and _item_env_valid(item, env)
        for item in legacy
    )
    return legacy if has_env_valid_make else build(env)


# ──────────────────────────────────────────────────────────────────────────
# POSITIVE geometric routing — archetype recognition with surfaced reasoning.
#
# The DFM `score_process` ranks by ABSENCE of violations, so on a benign part
# every process ties at ~1.0 and the "best" process is noise (a 2mm flat panel
# reads as wire_edm / binder_jetting). This classifier instead asks the positive
# question a manufacturing engineer asks — "what SHAPE is this?" — and names the
# process that shape implies, with the measured drivers that decided it. It is
# advisory (surfaced as reasoning); the dollar make-vs-buy still ranks by cost.
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class RoutingRecommendation:
    archetype: str             # sheet_panel | rotational | long_prismatic_bar |
                               # prismatic_block | thin_wall_enclosure | bulk_solid
    process: str               # primary recommended ProcessType.value
    eval_family: str           # sheet_metal | subtractive | additive | injection_molding
    material_hint: str         # suggested material class for this archetype
    confidence: float          # 0..1, geometry-evidence strength
    reasoning: str             # the measured drivers + the rule that fired
    alternatives: list = field(default_factory=list)   # other plausible processes


# process.value -> evaluation family (for the routing card metadata when the
# headline is demoted to a DFM-clean alternative — see _avoid_dfm_failed_headline).
_EVAL_FAMILY = {
    PT.SHEET_METAL.value: "sheet_metal",
    PT.CNC_TURNING.value: "subtractive",
    PT.CNC_3AXIS.value: "subtractive",
    PT.CNC_5AXIS.value: "subtractive",
    PT.WIRE_EDM.value: "subtractive",
    PT.INJECTION_MOLDING.value: "injection_molding",
    PT.DIE_CASTING.value: "casting",
    PT.SAND_CASTING.value: "casting",
    PT.INVESTMENT_CASTING.value: "casting",
    PT.FORGING.value: "forging",
}


def _family_of(proc_value: str) -> str:
    return _EVAL_FAMILY.get(proc_value, "additive")


def _avoid_dfm_failed_headline(rec: "RoutingRecommendation",
                               dfm_failed, dfm_clean=None) -> "RoutingRecommendation":
    """F2 invariant: the routing HEADLINE is never a process the engine's own DFM
    hard-fails on this part.

    If the archetype's primary process hard-fails as-modeled (e.g. a printed-for-
    3DP cover whose injection-molding DFM fails for lack of draft, or a round part
    whose CNC-turning DFM fails on L/D), promote a DFM-clean process to the
    headline — first an offered alternative, else (rare: the engine hard-fails
    every offered alternative too) the best DFM-clean process from `dfm_clean`
    (ordered costed-first) — and keep the original as the at-volume / design-for-
    process route in the reasoning + alternatives.

    The make-vs-buy tooling crossover (the wedge) is untouched: process selection
    for costing is `eligible_processes`, which is independent of this — injection
    molding is still costed and still surfaced as the volume crossover in the
    decision card. Only the headline badge stops contradicting the DFM matrix
    shown in the same panel.
    """
    failed = {p.value for p in (dfm_failed or set())}
    if rec.process not in failed:
        return rec
    replacement = next((a for a in rec.alternatives if a not in failed), None)
    if replacement is None:
        # No offered alternative is DFM-clean — fall back to the best DFM-clean
        # process overall (a part may hard-fail every printable/machinable route
        # as-modeled and pass only, e.g., sheet metal). estimate.py reconciles a
        # non-costed headline with its existing "feasibility-only" note.
        replacement = next((p for p in (dfm_clean or []) if p not in failed), None)
    if replacement is None:
        # The engine hard-fails EVERY process as-modeled — there is no
        # non-contradictory option to promote. Leave the geometric rec; the panel
        # is uniformly DFM-not-ready (dfm_ready=False on every estimate), so the
        # headline is contextualized, not a selective contradiction.
        return rec
    demoted = rec.process
    new_alts = [demoted] + [a for a in rec.alternatives if a != replacement]
    note = (f" As-modeled the {demoted} route hard-fails the engine's DFM "
            f"(design-for-process required) — that is the at-volume path, costed "
            f"and shown as the make-vs-buy crossover below; the DFM-clean "
            f"{replacement} route is headlined as what you can make as-is.")
    return RoutingRecommendation(
        archetype=rec.archetype,
        process=replacement,
        eval_family=_family_of(replacement),
        material_hint=rec.material_hint,
        confidence=rec.confidence,
        reasoning=rec.reasoning + note,
        alternatives=new_alts,
    )


def recommend_routing(drivers, material_class: str = "polymer",
                      dfm_failed=None, dfm_clean=None) -> RoutingRecommendation:
    """Classify the part's manufacturing archetype, then guarantee the headline
    is never a process the engine's own DFM hard-fails (F2).

    `dfm_failed` is the set of ProcessTypes the engine's DFM hard-fails (verdict
    == "fail", an ERROR-level blocker) on THIS part; `dfm_clean` is the ordered
    (costed-first) list of DFM-clean process values used as the last-resort
    headline when the engine hard-fails every offered alternative too.
    `_classify_archetype` names the shape-implied process; then
    `_avoid_dfm_failed_headline` demotes that headline to a DFM-clean process if
    the engine's own DFM fails it, so the routing card and the DFM matrix in the
    same panel can never contradict each other.
    """
    rec = _classify_archetype(drivers, material_class)
    return _avoid_dfm_failed_headline(rec, dfm_failed, dfm_clean)


def _classify_archetype(drivers, material_class: str = "polymer") -> RoutingRecommendation:
    """Pure geometry classifier (no DFM coupling). Priority mirrors how a process
    engineer eliminates options:
      1. constant-gauge flat sheet  -> sheet metal / stamping
      2. axisymmetric (turnable)    -> CNC turning
      3. thin-wall non-flat shell   -> injection molding (vol) / AM (proto)
      4. slender prismatic bar      -> saw-to-length + turn / 3-axis mill (F4)
      5. compact prismatic block    -> CNC milling
      6. bulky / freeform solid     -> AM or CNC by size
    """
    d = drivers.bbox_mm
    gauge = drivers.sheet_gauge_mm
    wall = drivers.nominal_wall_mm
    aspect = drivers.planar_aspect

    # 1) SHEET PANEL ----------------------------------------------------------
    if drivers.sheet_like:
        bends = drivers.bend_count
        op = "flat laser/punch blank" if bends == 0 else f"blank + {bends} press-brake bend(s)"
        return RoutingRecommendation(
            archetype="sheet_panel",
            process=PT.SHEET_METAL.value,
            eval_family="sheet_metal",
            material_hint=(material_class if material_class in SHEET_METAL_CLASSES else "aluminum"),
            confidence=0.85,
            reasoning=(
                f"Constant ~{wall:.1f}mm wall over a {d[1]:.0f}×{d[2]:.0f}mm planar "
                f"footprint (thinnest extent {d[0]:.1f}mm ≈ gauge, planar aspect "
                f"{aspect:.0f}:1) → a flat sheet, not a printed/cut solid. Route to "
                f"sheet-metal / stamping: {op}, {drivers.outline_perimeter_mm:.0f}mm cut "
                f"length. Powder-bed/MJF here is a prototyping fallback, not the "
                f"production route."),
            alternatives=[PT.CNC_3AXIS.value, PT.MJF.value],
        )

    # 2) ROTATIONAL -----------------------------------------------------------
    if drivers.rotational:
        return RoutingRecommendation(
            archetype="rotational",
            process=PT.CNC_TURNING.value,
            eval_family="subtractive",
            material_hint=(material_class if material_class != "polymer" else "aluminum"),
            confidence=0.8,
            reasoning=(
                f"Axisymmetric cross-section (round, turnable): axis "
                f"{drivers.rot_axis_len_mm:.0f}mm × Ø{drivers.rot_cross_dia_mm:.0f}mm "
                f"→ CNC turning / mill-turn. A round metal part is rarely powder-bed "
                f"printed at production volume."),
            alternatives=[PT.CNC_5AXIS.value, PT.MJF.value],
        )

    # bulk / wall / shape descriptors for the remaining classes
    solidity = (drivers.volume_cm3 / drivers.bbox_volume_cm3) if drivers.bbox_volume_cm3 else 0.0
    block_aspect = d[2] / d[0] if d[0] > 0 else 0.0

    # 3) THIN-WALL ENCLOSURE (hollow box / cover with depth, NOT a flat sheet) -
    if wall <= 3.5 and solidity < 0.45 and d[0] > 8.0:
        if material_class == "polymer":
            return RoutingRecommendation(
                archetype="thin_wall_enclosure",
                process=PT.INJECTION_MOLDING.value,
                eval_family="injection_molding",
                material_hint="polymer",
                confidence=0.6,
                reasoning=(
                    f"Thin-wall hollow shell (~{wall:.1f}mm wall, {solidity*100:.0f}% of "
                    f"bbox filled, {d[0]:.0f}mm depth) — a cover/enclosure with draft, "
                    f"not a flat sheet. At volume this is injection molding; at proto "
                    f"volume, MJF/SLS."),
                alternatives=[PT.MJF.value, PT.SLS.value],
            )
        return RoutingRecommendation(
            archetype="thin_wall_enclosure",
            process=PT.MJF.value, eval_family="additive", material_hint=material_class,
            confidence=0.5,
            reasoning=(
                f"Thin-wall hollow shell (~{wall:.1f}mm wall, {solidity*100:.0f}% filled) "
                f"in a metal class — sheet-fab or AM depending on intent."),
            alternatives=[PT.SHEET_METAL.value, PT.CNC_3AXIS.value],
        )

    # 4) LONG PRISMATIC BAR (slender bar/rod stock) — F4 -----------------------
    # Placed BEFORE prismatic_block; disjoint from it by construction (a bar's
    # d[2]/d[1] >= 4.0 forces d[2]/d[0] >= 4.0, which fails the block's <= 4.0
    # ceiling), so no compact block is reclassified. `drivers.rotational` is
    # already handled by branch (2) above and is always False here — this check
    # is kept for robustness in case classification order ever changes.
    if is_long_prismatic_bar(drivers, material_class):
        if drivers.rotational:
            return RoutingRecommendation(
                archetype="long_prismatic_bar",
                process=PT.CNC_TURNING.value, eval_family="subtractive",
                material_hint=material_class, confidence=0.7,
                reasoning=(
                    f"Slender round bar ({d[2]:.0f}mm long × Ø{d[1]:.0f}mm): saw to "
                    f"length, then turn — 5-axis is not warranted for bar stock."),
                alternatives=[PT.CNC_3AXIS.value],
            )
        return RoutingRecommendation(
            archetype="long_prismatic_bar",
            process=PT.CNC_3AXIS.value, eval_family="subtractive",
            material_hint=material_class, confidence=0.7,
            reasoning=(
                f"Slender prismatic bar ({d[2]:.0f}mm long × {d[1]:.0f}×{d[0]:.0f}mm "
                f"cross-section): saw to length, then 3-axis mill — 5-axis is not "
                f"warranted for bar stock."),
            alternatives=[PT.CNC_TURNING.value],
        )

    # 5) PRISMATIC BLOCK (compact, machinable from billet) --------------------
    if solidity >= 0.5 and block_aspect <= 4.0 and material_class != "polymer":
        return RoutingRecommendation(
            archetype="prismatic_block",
            process=PT.CNC_3AXIS.value, eval_family="subtractive",
            material_hint=material_class, confidence=0.6,
            reasoning=(
                f"Compact prismatic solid ({solidity*100:.0f}% of bbox filled, "
                f"{block_aspect:.1f}:1 aspect) in metal → machine from billet "
                f"(CNC 3-/5-axis)."),
            alternatives=[PT.CNC_5AXIS.value],
        )

    # 6) BULK / FREEFORM default ---------------------------------------------
    return RoutingRecommendation(
        archetype="bulk_solid",
        process=PT.MJF.value if material_class == "polymer" else PT.CNC_3AXIS.value,
        eval_family="additive" if material_class == "polymer" else "subtractive",
        material_hint=material_class, confidence=0.4,
        reasoning=(
            f"General solid ({solidity*100:.0f}% of bbox filled, ~{wall:.1f}mm mean "
            f"wall) with no dominant sheet/rotational/prismatic signature → "
            f"{'additive (MJF/SLS) for a polymer prototype' if material_class=='polymer' else 'CNC machining for a metal part'}."),
        alternatives=[PT.SLS.value, PT.CNC_3AXIS.value],
    )
