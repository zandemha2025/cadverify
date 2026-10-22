"""The cost model (spec §6 + V1 fix-spec §4-§9) — explicit, itemized master formula.

This is NOT the toy cost_per_cm3 factor. Every dollar is the sum of named line
items, each backed by a provenance-tagged Driver with a source string. The hard
invariant `unit_cost == Σ line_items` (gate G3) is asserted before returning.

V1 changes (the 8 weaknesses):
  #1/#2  build-plate nesting for ADDITIVE: build_job machine time is amortized
         over parts_per_build; serial (FDM/SLA) stays honest per-part. Post-labor
         is split per-part finishing + per-build bulk (depowder) amortized over n.
  #3     per-lot minimum charge clamp (adds a line item only when it bites).
  #4     region split: three vectors (labor / material / tooling) per line item.
  #5     tooling cavity^exponent × complexity; per-shot machine ÷ n_cavities.
  #8     setup: once per order on a machine, mould or die; once per plate when printing.

    line_items = {amortized_fixed, material, machine, labor}   (4-key shape kept)
    unit_cost  = Σ line_items   (+ min_charge_floor when the order floor bites)
"""

from __future__ import annotations

import math
import os

from src.analysis.models import ProcessType
from src.analysis.process_names import process_label
from src.costing.drivers import basis_words, build_orientation, parts_per_build
from src.costing.learning import learning_words, lot_average_factor
from src.costing.provenance import TYPICAL, CostEstimate, Driver, Provenance
from src.costing.rates import (
    ADDITIVE, SUBTRACTIVE, FORMATIVE, FABRICATION, CASTING, FORGING_FAMILY, EDM,
    METAL_POWDER_BED, BINDER_JET_FAMILY, DED_FAMILY,
    RateCard, process_family,
)

PT = ProcessType

# Priced from the slicer-calibrated print model when the part's mesh was measured.
_PRINT_PROCESSES = {PT.FDM: "fdm", PT.SLA: "sla"}


def _print_note() -> str:
    from src.costing.print_model import CALIBRATION_NOTE

    return CALIBRATION_NOTE

# Master on/off for the volume/learning economics (S1 fix). Defaults ON. Set
# CADVERIFY_CNC_LEARNING=0 to recover the flat, volume-invariant conversion cost.
# (A learning_rate=1.0 rate override is the equivalent per-quote off-switch.)
_LEARNING_FAMILIES = {"subtractive", "fabrication"}


def _learning_multiplier(family, qty, ref_qty, rates: RateCard):
    """The lot-average learning factor an order of ``qty`` pays on its TOUCH LABOR.

    ce-03: the curve applies to the hand work and in-process inspection, never to
    the machine's cycle (the program sets it) or the tools that follow it, and an
    order pays the average over its parts, not its last part's factor. The rate
    card's hours are the first lot's standard (``ref_qty`` = lot_size), so nothing
    is credited at or below one lot. See ``src.costing.learning`` for the source
    and the arithmetic.

    Returns (multiplier, source_string); the rate is a DEFAULT assumption, not
    validated against real shop quotes.
    """
    if os.getenv("CADVERIFY_CNC_LEARNING", "1") == "0":
        return 1.0, None
    if family not in _LEARNING_FAMILIES:
        return 1.0, None
    rate = rates.g("learning_rate")
    if not rate or rate >= 1.0 or ref_qty <= 0 or qty <= ref_qty:
        return 1.0, None
    floor = rates.g("learning_floor")
    mult = lot_average_factor(rate, ref_qty, floor, qty)
    return mult, learning_words(rate, ref_qty, floor, qty, mult)


# ──────────────────────────────────────────────────────────────────────────
# MACHINE sub-models. Additive returns (machine_hr, parts_per_build, src);
# subtractive/formative return (cycle_hr, src) with parts_per_build = 1.
# ──────────────────────────────────────────────────────────────────────────
_CLASS_WORDS = {"polymer": "plastic", "stainless": "stainless steel", "nickel": "nickel alloy"}


class BuildEnvelopeError(ValueError):
    """No fitting setup established for the machine being priced."""


class BelowProcessSizeError(BuildEnvelopeError):
    """The part is smaller than the process is run for (wire-arc and metal
    deposition are large near-net routes): no price, like a part that doesn't fit."""


# The bead width and per-face machining stock each deposition route cites
# (src/analysis/processes/additive/{ded,waam}.py), said where its size floor bites.
_DEPOSITION_WHY = {
    PT.DED: ("lays 2–4 mm beads and leaves 2–5 mm to machine off every face"),
    PT.WAAM: ("lays 4–8 mm beads and leaves 3–5 mm to machine off every face"),
}


def check_process_size_floor(process, drivers, rates) -> None:
    """Raise ``BelowProcessSizeError`` when a deposition route's size floor rules the
    part out. The longest side is read from the smallest box found around the part,
    so it doesn't change with the file's orientation."""
    floor = rates.pget(process, "min_longest_side_mm") if process in DED_FAMILY else 0.0
    if not floor:
        return
    box = getattr(drivers, "billet_bbox_mm", None) or drivers.bbox_mm
    longest = max(float(d) for d in box)
    if longest >= floor:
        return
    raise BelowProcessSizeError(
        f"{process_label(process)} is for large near-net metal parts: it "
        f"{_DEPOSITION_WHY.get(process, 'leaves stock to machine off every face')}, so ScaleCAD "
        f"doesn't price it under {floor:g} mm on the longest side (this part: {longest:.0f} mm). "
        "A part this small is machined from bar or printed in a powder bed instead "
        "(size floor: typical value, not confirmed by a shop).")


def kg_text(kg: float) -> str:
    """A mass in kg for a derivation: 4 decimals, more under a gram so a tiny
    part never reads ``0.0000 kg`` (``0.0000412``); never scientific notation."""
    kg = float(kg)
    if kg >= 0.001 or kg <= 0:
        return f"{kg:.4f}"
    return f"{kg:.{2 - math.floor(math.log10(kg))}f}"


def _sig(x: float, digits: int = 6) -> float:
    """``x`` to ``digits`` significant figures: structured masses keep a tiny part's grams."""
    return float(f"{float(x):.{digits}g}")


def _tier_size_text(size_mm: float, tier: str) -> str:
    """The size a tooling tier was read from, to 0.1 mm ("990.6", not "990.599976"),
    with the decimals that show why it sits in its tier when 0.1 mm would hide it
    ("300.0001" is tier XL; "300.0" reads tier L)."""
    from src.costing.rates import family_to_size_tier

    text = f"{size_mm:.1f}"
    if family_to_size_tier(float(text)) != tier:
        text = f"{size_mm:.4f}".rstrip("0").rstrip(".")
    return text


def mm_dims(dims) -> str:
    """``(318.2004, 405.0, 559.3769)`` → ``"318.2 × 405 × 559.4"``: sizes in sentences, to 0.1 mm."""
    return " × ".join(f"{round(float(d), 1):g}" for d in dims)


def _additive_machine(process, drivers, rates: RateCard, machine_override=None):
    """Build-plate nesting model (weaknesses #1, #2).

    build_job (powder-bed laser/fuse, DLP whole-layer): the machine sweeps every
    layer regardless of part count, so per-part machine time = full-build job
    duration ÷ parts_per_build. This is the structural fix for the 82%-machine
    artifact.

    serial (FDM single nozzle, SLA laser trace): XY-nested plate (R2). The single
    nozzle/laser must lay every part's material, so deposition (V/rate) is
    genuinely per-part and irreducible. But all nested parts build up TOGETHER
    layer by layer, so the Z-axis plate sweep (build_h/vert) is a per-PLATE cost
    that V1 wrongly charged per part; amortizing it over the XY nest is the
    physically-honest fix that collapses the medium-part over-cost.
    """
    bbox = getattr(drivers, "billet_bbox_mm", None) or drivers.bbox_mm
    shrink = rates.p(process, "shrinkage_linear") if process in BINDER_JET_FAMILY else 0
    bbox = tuple(d * (1 + shrink) for d in bbox)
    cylinder = getattr(drivers, "enclosing_cylinder_mm", None)
    if cylinder is not None:
        cylinder = tuple(d * (1 + shrink) for d in cylinder)
    envelope = (machine_override or {}).get("build_env_mm") or rates.build_env(process)
    orientation = build_orientation(bbox, envelope)
    basis = drivers.billet_basis
    if orientation is None:
        orientation = build_orientation(bbox, envelope, cylinder)
        basis = "measured enclosing cylinder"
    n = parts_per_build(process, bbox, rates, envelope, cylinder)
    if orientation is None or n == 0:
        raise BuildEnvelopeError(
            f"{process_label(process)}: price withheld — no fitting orientation established for "
            f"the {mm_dims(bbox)} mm enclosing box in the priced build "
            f"envelope {mm_dims(envelope)} mm. Confirm a build setup or select a larger "
            "machine; this is not proof that every possible orientation fails.")
    mode = rates.nesting_mode(process)
    if mode == "build_job":
        Z = envelope[2]
        vert = rates.p(process, "vert")
        build_job_hr = Z / vert                       # full-build duration (height-driven)
        machine_hr = build_job_hr / n                 # this part's amortized share
        src = (f"build-job {Z:g}mm ÷ {vert:g}mm/hr = {build_job_hr:.1f}hr full build "
               f"÷ {n} parts/build (packing {rates.packing_density(process):g}, "
               f"env {tuple(envelope)}) = {machine_hr:.3f}hr/part")
    else:  # serial (FDM single nozzle / SLA laser): XY-nested plate
        dep = rates.p(process, "deposition")
        vert = rates.p(process, "vert")
        build_h = orientation[2]
        deposition_hr = drivers.volume_cm3 / dep      # per-part — single nozzle/laser, irreducible
        sweep_hr = (build_h / vert) / n               # per-PLATE Z-climb, amortized over the XY nest
        machine_hr = deposition_hr + sweep_hr
        who = ("the laser traces each part in turn" if process in (PT.SLA, PT.DLP)
               else "one nozzle lays each part in turn")
        src = (f"parts side by side on one plate: deposition V/{dep:g} = {drivers.volume_cm3:.2f}/{dep:g} "
               f"= {deposition_hr:.4g}hr/part ({who}) + Z-sweep "
               f"({build_h:.1f}/{vert:g})÷{n} parts/plate = {sweep_hr:.3f}hr/part "
               f"(plate Z-climb amortized; XY packing {rates.xy_packing_density(process):g}, "
               f"plate {envelope[0]:g}×{envelope[1]:g}mm) "
               f"= {machine_hr:.3f}hr/part")
    src += (f"; laid out {' × '.join(f'{round(d, 6):g}' for d in orientation)} mm "
            f"({basis_words(basis)}); parts per build from a spaced grid, an estimate, "
            "not a planned nest")
    if shrink:
        src += f"; green dimensions ×{1 + shrink:g} for sinter shrinkage"
    if (machine_override or {}).get("build_env_mm"):
        src += f"; work area declared for '{(machine_override or {}).get('machine_name')}'"
    return machine_hr, n, src


def _cnc_cycle(process, drivers, material_class, rates: RateCard):
    """Material-removal model: rough (remove billet→part) + finish (surface area)."""
    if process == PT.CNC_TURNING:
        allow = rates.g("stock_allowance")
        stock_vol = drivers.turning_stock_volume_cm3(allow)
        stock_src = (f"bounding cylinder π·({drivers.rot_cross_dia_mm:.1f}/2)²·"
                     f"{drivers.rot_axis_len_mm:.1f} mm × {allow:.2f} stock allowance "
                     f"= {stock_vol:.1f} cm³ (typical value, not confirmed by a shop)")
    else:
        # E-now #1: mill from a rectangular BILLET (bounding box), not a hull —
        # a pocketed part is cut from a solid block, so more is roughed away.
        from src.costing.drivers import bbox_billet_enabled
        allow = rates.g("stock_allowance")
        stock_vol = drivers.billet_volume_cm3(allow)
        if bbox_billet_enabled():
            stock_src = (f"a billet the size of {basis_words(drivers.billet_basis)}, "
                         f"{drivers.billet_volume_cm3(1):.1f} cm³ × {allow:.2f} "
                         f"= {stock_vol:.1f} cm³ (typical value, not confirmed by a shop)")
        else:
            stock_src = (f"hull {drivers.hull_volume_cm3:.1f} cm³ × {allow:.2f} "
                         f"= {stock_vol:.1f} cm³")
    removed = max(0.0, stock_vol - drivers.volume_cm3)
    mrr = rates.mrr(material_class)            # cm³/min
    rough_hr = removed / (mrr * 60.0)
    finish_rate = rates.p(process, "finish")   # cm²/hr
    finish_hr = drivers.surface_area_cm2 / finish_rate
    cycle = rough_hr + finish_hr
    src = (f"rough {removed:.1f} cm³ ÷ ({mrr:g} cm³/min·60) = {rough_hr:.3f} hr "
           f"+ finish {drivers.surface_area_cm2:.1f} cm² ÷ {finish_rate:g} cm²/hr "
           f"= {finish_hr:.3f} hr (stock: {stock_src}; removal rate for {_CLASS_WORDS.get(material_class, material_class)})")
    # finish_hr is returned separately so the declared tolerance-class input
    # (Aramco gap #4) can scale ONLY the finish-pass share of machine time, not
    # roughing (roughing is not tolerance-driven).
    return cycle, finish_hr, src


def _sheet_cycle(process, drivers, rates: RateCard):
    """Fabrication cycle (laser/punch blank + press-brake bend) — a physics model,
    not a magic $/cm³.

      cut    = outline perimeter (MEASURED: outer outline + every cutout edge)
               ÷ cut speed. Cut speed falls with gauge (thicker = slower), so the
               effective feed is base_speed × ref_gauge / gauge.
      bend   = bend_count (distinct fold lines) × seconds-per-brake-hit.
      handle = fixed load/unload/locate per part.

    Every term is an inspectable driver; nothing is a fitted constant.
    """
    t = max(drivers.sheet_gauge_mm, 0.1)
    base_speed = rates.p(process, "cut_speed_mm_min")
    ref = rates.p(process, "ref_gauge_mm")
    speed_eff = base_speed * (ref / max(t, ref))
    perim = drivers.outline_perimeter_mm
    cut_hr = (perim / speed_eff) / 60.0
    n_bends = int(drivers.bend_count)
    sec_per_bend = rates.p(process, "sec_per_bend")
    bend_hr = n_bends * sec_per_bend / 3600.0
    handling_hr = rates.p(process, "handling_hr")
    cycle = cut_hr + bend_hr + handling_hr
    src = (f"cut {perim:.0f}mm ÷ {speed_eff:.0f}mm/min "
           f"(laser {base_speed:g}mm/min @ {ref:g}mm, ×{ref:g}/{t:.2f}mm gauge) "
           f"= {cut_hr * 60:.2f}min + bends {n_bends}×{sec_per_bend:g}s "
           f"= {bend_hr * 60:.2f}min + handling {handling_hr * 60:.1f}min "
           f"= {cycle:.4f} hr")
    return cycle, src


def _formative_cycle(process, drivers, rates: RateCard):
    """Cooling ∝ wall² + shot overhead. Per-shot machine cost is small; tooling
    dominates fixed cost."""
    coef = rates.g("cooling_coef")
    overhead = rates.g("shot_overhead_s")
    cooling_s = coef * drivers.nominal_wall_mm ** 2
    cycle_s = cooling_s + overhead
    cycle_hr = cycle_s / 3600.0
    src = (f"cooling {coef:g}·wall² = {coef:g}·{drivers.nominal_wall_mm:.2f}² "
           f"= {cooling_s:.1f}s + shot {overhead:g}s = {cycle_s:.1f}s "
           f"= {cycle_hr:.4f} hr  [wall = 2V/A proxy, ±50%]")
    return cycle_hr, src


def _casting_cycle(process, drivers, material, rates: RateCard):
    """Foundry pour cycle: pour/handling + solidification cool (∝ poured mass).

    Poured mass = net part mass × (1 + yield_loss) (gating + risers). The mould
    machine-cycle is the ladle pour plus the solidification/cool the part must sit
    in the mould before knockout — cool time scales with the metal poured. Knockout
    / fettle / clean is LABOR (post_hr_part), not machine time. Every constant is a
    DEFAULT foundry assumption, NOT validated.
    """
    net_mass = drivers.mass_kg(material.density)
    yl = rates.p(process, "yield_loss")
    poured = net_mass * (1.0 + yl)
    cool_min_per_kg = rates.p(process, "cool_min_per_kg")
    pour_hr = rates.p(process, "pour_hr")
    cool_hr = poured * cool_min_per_kg / 60.0
    cycle = pour_hr + cool_hr
    src = (f"pour {pour_hr:g}hr + solidify/cool {poured:.3f}kg poured "
           f"(net {net_mass:.3f}kg × 1+{yl:g} yield) × {cool_min_per_kg:g}min/kg "
           f"= {cool_hr * 60:.1f}min = {cycle:.4f} hr  "
           f"(typical value, not confirmed by a shop)")
    return cycle, src


def _forging_cycle(process, drivers, material, rates: RateCard):
    """Closed-die forging cycle: furnace heat (∝ billet mass) + press/hammer
    strokes + flash-trim.

    Billet mass = net part mass × (1 + flash_loss) (flash web + scale). Heat time
    to forging temperature scales with billet mass; press and trim are per-part
    fixed operations. NOTE: a forging is a near-net BLANK — downstream finish
    machining is USUALLY required and is deliberately NOT bundled here (a caveat,
    not a hidden CNC pass). Every constant is a DEFAULT assumption, NOT validated.
    """
    net_mass = drivers.mass_kg(material.density)
    fl = rates.p(process, "flash_loss")
    billet = net_mass * (1.0 + fl)
    heat_min_per_kg = rates.p(process, "heat_min_per_kg")
    press_hr = rates.p(process, "press_hr")
    trim_hr = rates.p(process, "trim_hr")
    heat_hr = billet * heat_min_per_kg / 60.0
    cycle = heat_hr + press_hr + trim_hr
    src = (f"heat {billet:.3f}kg billet (net {net_mass:.3f}kg × 1+{fl:g} flash/scale) "
           f"× {heat_min_per_kg:g}min/kg = {heat_hr * 60:.1f}min + press {press_hr:g}hr "
           f"+ trim {trim_hr:g}hr = {cycle:.4f} hr  (a near-net blank: finish machining "
           f"is not included; typical value, not confirmed by a shop)")
    return cycle, src


def _edm_cycle(process, drivers, material_class, rates: RateCard):
    """Wire-EDM cut-path model: swept cross-section AREA ÷ a very slow EDM cut rate,
    plus wire-threading per contour.

      swept area = cut-path length × stock thickness.
                   PROXY: cut-path length = drivers.outline_perimeter_mm (the
                   MEASURED 2D outline/cutout length); stock thickness = the
                   smallest candidate-billet extent (the plate the wire cuts through). This is
                   an APPROXIMATION — there is no true 3D cut-perimeter driver — and
                   is flagged as such in the source string.
      cut time   = swept area ÷ edm_cut_rate(material) (mm²/hr — slow, material-set).
      thread     = n_threads contours × thread_min (auto-wire-thread + re-reference).

    Returns (machine_hr, swept_area_mm2, cut_hr, src). Wire consumable is costed
    separately (∝ cut time). All constants DEFAULT, un-validated.
    """
    from src.costing.drivers import bbox_billet_enabled
    blank = drivers.billet_bbox_mm if bbox_billet_enabled() else None
    dd = sorted(blank or drivers.bbox_mm)        # same candidate stock as the material model
    thickness = max(dd[0], 0.1)
    cut_len = max(drivers.outline_perimeter_mm, 2.0 * (dd[1] + dd[2]))  # measured outline, floored at bbox rect
    swept_area = cut_len * thickness             # mm² of cross-section the wire erodes
    cut_rate = rates.edm_cut_rate(material_class)     # mm²/hr (SLOW)
    cut_hr = swept_area / cut_rate
    n_threads = int(rates.p(process, "n_threads"))
    thread_min = rates.p(process, "thread_min")
    thread_hr = n_threads * thread_min / 60.0
    cycle = cut_hr + thread_hr
    src = (f"wire-EDM cut path {cut_len:.0f}mm × {thickness:.1f}mm stock "
           f"= {swept_area:.0f}mm² swept ÷ {cut_rate:g}mm²/hr ({material_class}, slow) "
           f"= {cut_hr * 60:.1f}min + thread {n_threads}×{thread_min:g}min "
           f"= {cycle:.4f} hr  (cut path estimated as the outline length × the thinnest "
           f"stock side, {basis_words(drivers.billet_basis if blank else 'file-axis fallback')}, "
           f"not a measured 3D path; typical value, not confirmed by a shop)")
    return cycle, swept_area, cut_hr, src


def _metal_am_post(process, n, rates: RateCard):
    """Metal powder-bed POST-PROCESSING that polymer AM never pays.

    Returns a list of (line_key, driver_name, hr_per_part, source) components:
      * build-plate removal  — cut the parts off the build plate (wire-EDM/bandsaw),
                               per part.
      * support removal      — grind/break metal supports off, per part.
      * stress-relief furnace— a per-BUILD furnace batch (relieve residual stress
                               from the melt), amortized over the n parts on the plate.

    Each is emitted as its own inspectable Driver + line item. NOTE (caveat carried
    in the stress-relief source): HIP, solution heat-treat and CNC finishing of
    critical surfaces are part-specific and deliberately NOT bundled here. Every
    constant is a DEFAULT assumption, not shop-validated.
    """
    plate_hr = rates.p(process, "plate_removal_hr")
    support_hr = rates.p(process, "support_removal_hr")
    sr_build = rates.p(process, "stress_relief_hr_build")
    sr_per_part = sr_build / n if n else sr_build
    return [
        ("plate_removal", "plate_removal_cost", plate_hr,
         (f"build-plate removal (wire-EDM/bandsaw off the plate) {plate_hr:g}hr/part "
          f"(typical value, not confirmed by a shop)")),
        ("support_removal", "support_removal_cost", support_hr,
         (f"metal support removal (grind/break-off) {support_hr:g}hr/part "
          f"(typical value, not confirmed by a shop)")),
        ("stress_relief", "stress_relief_cost", sr_per_part,
         (f"stress-relief furnace {sr_build:g}hr/build ÷ {n} parts/build "
          f"= {sr_per_part:.3f}hr/part (batch amortized). HIP / solution heat-treat / "
          f"CNC finish of critical surfaces are part-specific and not included "
          f"(typical value, not confirmed by a shop)")),
    ]


def _ded_cycle(process, drivers, material, rates: RateCard):
    """DED / WAAM deposition-rate cycle: deposited feedstock mass ÷ deposition rate.

    Directed-energy / wire-arc deposition is rate-driven, not layer-swept: the cell
    lays down feedstock at deposition_rate_kg_hr, so machine time = deposited mass ÷
    that rate. Deposited mass = net part mass × feedstock_mult (near-net overbuild
    that the downstream finish machining removes). This is a COARSE model — real DED/
    WAAM time is highly geometry/path/shop-specific — flagged in the source. Returns
    (machine_hr, deposited_kg, src).
    """
    net_mass = drivers.mass_kg(material.density)
    fm = rates.p(process, "feedstock_mult")
    deposited = net_mass * fm
    rate_kg_hr = rates.p(process, "deposition_rate_kg_hr")
    machine_hr = deposited / rate_kg_hr if rate_kg_hr > 0 else 0.0
    src = (f"deposit {deposited:.4f}kg (net {net_mass:.4f}kg × {fm:g} near-net overbuild) "
           f"÷ {rate_kg_hr:g}kg/hr deposition = {machine_hr:.4f}hr  (a rough deposition-rate "
           f"model: real deposition time depends on the part, the path and the shop; "
           f"typical value, not confirmed by a shop)")
    return machine_hr, deposited, src


# ──────────────────────────────────────────────────────────────────────────
# Master cost breakdown
# ──────────────────────────────────────────────────────────────────────────
def cost_breakdown(process, drivers, material, material_class, qty,
                   rates: RateCard, region: str, n_cavities: int = 1,
                   complexity: str = "moderate", process_score=None,
                   owned: bool = False, tolerance_class: str = "standard",
                   machine_override: dict = None) -> CostEstimate:
    family = process_family(process)
    labor_rate = rates.g("labor_rate")
    margin = rates.g("margin")
    overhead = rates.g("overhead")            # indirect burden on conversion cost (DEFAULT 0)
    utilization = rates.g("utilization")      # machine utilization (DEFAULT 1.0)
    scrap = rates.p(process, "scrap")
    band = rates.band_pct(process)
    # Declared tolerance class (Aramco gap #4): a COST multiplier (≥1.0) on the
    # tolerance-sensitive conversion terms + an absolute band widening. standard
    # ⇒ (1.0, 0.0) ⇒ byte-identical. reported_band is what the estimate exposes;
    # the per-driver family `band` stays the base family band (unchanged).
    tol_cost_mult, tol_band_add = rates.tolerance_factors(tolerance_class)
    reported_band = band + tol_band_add

    rl = rates.region_labor(region)
    rl_machine = rates.machine_region_mult(region)   # E-now #2: labor-only region scaling of the blended machine rate
    rm = rates.region_material(region)
    rt = rates.region_tooling(region)
    mgn = 1.0 + margin
    burden = 1.0 + overhead                   # applied to machine/labor/setup conversion cost
    util = utilization if utilization and utilization > 0 else 1.0
    # Sources must disclose the same multipliers as their displayed values.
    # `margin` is a markup on cost in this model (1 + margin), not gross margin.
    margin_note = f" × {mgn:g} markup" if mgn != 1.0 else ""
    burden_note = f" × {burden:g} overhead" if burden != 1.0 else ""
    conversion_note = margin_note + burden_note

    drivers_out: list[Driver] = []

    # ---- PRINT PLAN (FDM / SLA): slicer-calibrated, the part as checked ----
    # Time and material follow the part's orientation: layers, support under
    # what overhangs (FDM bridges excluded), resin supports and pad. Drivers
    # built without a mesh keep the volume model below.
    print_plan = None
    if process in _PRINT_PROCESSES and getattr(drivers, "print_features", None) is not None:
        from src.costing import print_model

        envelope = tuple((machine_override or {}).get("build_env_mm") or rates.build_env(process))
        print_plan = print_model.plan(_PRINT_PROCESSES[process], drivers, envelope,
                                      rates.part_spacing(process), rates.xy_packing_density(process))
        if print_plan is None:
            f = drivers.print_features
            raise BuildEnvelopeError(
                f"{process_label(process)}: price withheld — no way of laying the part on a side of its box "
                f"fits the {mm_dims(envelope)} mm work area (as checked {f.x_mm:.1f} × {f.y_mm:.1f} × "
                f"{f.height_mm:.1f} mm). Select a larger machine; this is not proof that every "
                "possible orientation fails.")

    # ---- MATERIAL --------------------------------------------------------
    if process == PT.CNC_TURNING:
        # Buy the same enclosing round bar used by the rough-machining model.
        input_mass = drivers.stock_mass_kg(material.density, rates.g("stock_allowance"))
        mass_src = drivers.stock_source(material.density, rates.g("stock_allowance"), material.name)
    elif process in SUBTRACTIVE:
        # E-now #1: milling billet = bounding-box block × allowance (was hull)
        input_mass = drivers.billet_mass_kg(material.density, rates.g("stock_allowance"))
        mass_src = drivers.billet_source(material.density, rates.g("stock_allowance"), material.name)
    elif process in FABRICATION:
        # you buy the rectangular blank (footprint × gauge), not just the net part
        blank = drivers.sheet_blank_mm or drivers.bbox_mm
        blank_volume = blank[0] * blank[1] * blank[2] / 1000.0
        input_mass = blank_volume * material.density / 1000.0
        mass_src = (f"sheet blank {blank[1]:.0f}×{blank[2]:.0f}×"
                    f"{drivers.sheet_gauge_mm:g}mm = {blank_volume:.2f} cm³ × "
                    f"{material.name} density {material.density:.2f} g/cm³ (rectangular blank)")
    elif process in CASTING:
        # poured metal = net part mass × (1 + yield_loss) for gating + risers
        net_mass = drivers.mass_kg(material.density)
        yl = rates.p(process, "yield_loss")
        input_mass = net_mass * (1.0 + yl)
        mass_src = (f"poured metal = net {kg_text(net_mass)} kg (CAD volume "
                    f"{drivers.volume_cm3:.2f} cm³ × {material.name} density "
                    f"{material.density:.2f} g/cm³) × (1+{yl:g} gating/riser yield) "
                    f"(typical value, not confirmed by a shop)")
    elif process in FORGING_FAMILY:
        # billet from bar stock = net part mass × (1 + flash/scale loss)
        net_mass = drivers.mass_kg(material.density)
        fl = rates.p(process, "flash_loss")
        input_mass = net_mass * (1.0 + fl)
        mass_src = (f"billet from bar = net {kg_text(net_mass)} kg (CAD volume "
                    f"{drivers.volume_cm3:.2f} cm³ × {material.name} density "
                    f"{material.density:.2f} g/cm³) × (1+{fl:g} flash/scale loss) "
                    f"(typical value, not confirmed by a shop)")
    elif process in EDM:
        # wire-EDM cuts the part from a solid billet plate (bbox block × allowance)
        input_mass = drivers.billet_mass_kg(material.density, rates.g("stock_allowance"))
        mass_src = drivers.billet_source(material.density, rates.g("stock_allowance"), material.name)
    elif process in METAL_POWDER_BED:
        # powder-bed metal = net part mass + support structure printed then removed.
        # Powder is priced at the material-DB $/kg (a KNOWN refinement — see powder mult
        # below — NOT silently inflated). Powder loss is the scrap term (recycled).
        net_mass = drivers.mass_kg(material.density)
        svf = rates.p(process, "support_vol_frac")
        input_mass = net_mass * (1.0 + svf)
        mass_src = (f"powder-bed metal = net {kg_text(net_mass)} kg (CAD volume "
                    f"{drivers.volume_cm3:.2f} cm³ × {material.name} density "
                    f"{material.density:.2f} g/cm³) × (1+{svf:g} support structure "
                    f"printed+removed); powder $/kg assumed at material-DB value "
                    f"(typical value, not confirmed by a shop)")
    elif process in BINDER_JET_FAMILY:
        # green part printed OVERSIZE for sinter shrinkage: material = net × (1+s)³ of
        # powder (net volume grows by the cube of the linear shrink factor).
        net_mass = drivers.mass_kg(material.density)
        shr = rates.p(process, "shrinkage_linear")
        oversize = (1.0 + shr) ** 3
        input_mass = net_mass * oversize
        mass_src = (f"green part = net {kg_text(net_mass)} kg × (1+{shr:g})³ = ×{oversize:.3f} "
                    f"sinter-shrink oversize (CAD volume {drivers.volume_cm3:.2f} cm³ × "
                    f"{material.name} density {material.density:.2f} g/cm³); powder $/kg at "
                    f"material-DB value (typical value, not confirmed by a shop)")
    elif process in DED_FAMILY:
        # feedstock (wire/powder) = net part mass × near-net overbuild, at material price
        net_mass = drivers.mass_kg(material.density)
        fm = rates.p(process, "feedstock_mult")
        input_mass = net_mass * fm
        mass_src = (f"feedstock (wire/powder) = net {kg_text(net_mass)} kg × {fm:g} near-net "
                    f"overbuild (CAD volume {drivers.volume_cm3:.2f} cm³ × {material.name} "
                    f"density {material.density:.2f} g/cm³) [DED/WAAM assumption, not "
                    f"shop-validated]")
    elif print_plan is not None:
        est, _placement = print_plan
        input_mass = est.material_cm3 * material.density / 1000.0
        mass_src = (f"{est.material_source} = {est.material_cm3:.2f} cm³ × {material.name} density "
                    f"{material.density:.2f} g/cm³ ({_print_note()})")
    else:
        input_mass = drivers.mass_kg(material.density)
        mass_src = drivers.mass_source(material.density, material.name)
    # shop lot price when the active profile binds one; else generic material-DB price
    price_per_kg, price_prov, price_note = rates.material_price(
        material.name, material_class, material.cost_per_kg)
    # metal powder-bed: a KNOWN, explicit powder-price refinement knob (DEFAULT 1.0 =
    # material-DB $/kg used as-is, NO silent inflation). Guarded to the new family so
    # every existing family's price path is byte-identical.
    if price_prov == Provenance.DEFAULT and getattr(material, "price_form", None):
        # The catalog prices each process at the form it buys (src.profiles.pricing).
        price_note = f"catalog {material.price_form} price, {TYPICAL}"
    if process in METAL_POWDER_BED:
        pmult = rates.p(process, "metal_am_powder_mult")
        if pmult != 1.0:
            price_per_kg = price_per_kg * pmult
            price_note = f"{price_note}; ×{pmult:g} powder price adjustment"
    material_cost = input_mass * price_per_kg * (1.0 + scrap)
    material_scaled = material_cost * rm * mgn
    # The same figures as fields, so a reader never parses the derivation text:
    # the part's own mass (CAD volume × density), the material the price is
    # charged on (stock cut from, printed with supports, poured), its density and
    # the $/kg. Six significant figures: a 0.04 g part keeps its grams.
    material_mass = {
        "part_kg": _sig(drivers.mass_kg(material.density)),
        "used_kg": _sig(input_mass),
        "density_g_cm3": float(material.density),
        "usd_per_kg": _sig(price_per_kg),
    }
    drivers_out.append(Driver(
        name="material_cost", value=round(material_scaled, 4), unit="$",
        provenance=price_prov,
        source=(f"{mass_src} = {kg_text(input_mass)} kg × ${price_per_kg:g}/kg ({price_note}) "
                f"× (1+{scrap:g} scrap) × region-material ×{rm:g}{margin_note}"),
        error_band_pct=5.0,
    ))
    # metal powder-bed: surface the support-structure powder as an inspectable adder
    # (already inside material_cost above; shown separately so it can be audited).
    if process in METAL_POWDER_BED:
        _svf = rates.p(process, "support_vol_frac")
        _support_mass = drivers.mass_kg(material.density) * _svf
        _support_cost = _support_mass * price_per_kg * (1.0 + scrap) * rm * mgn
        drivers_out.append(Driver(
            name="support_material", value=round(_support_cost, 4), unit="$",
            provenance=Provenance.DEFAULT,
            source=(f"support structure {_svf:g}×net = {_support_mass:.4f} kg powder "
                    f"× ${price_per_kg:g}/kg × (1+{scrap:g} scrap) "
                    f"× region-material ×{rm:g}{margin_note} "
                    f"printed then removed (already in the material cost above, shown "
                    f"separately; typical value, not confirmed by a shop)"),
            error_band_pct=band,
        ))

    # ---- MACHINE ---------------------------------------------------------
    finish_hr = 0.0     # CNC finish-pass share (set by _cnc_cycle); 0 for other families
    if family == "additive" and print_plan is not None:
        est, placement = print_plan
        machine_hr, n = est.hours_per_part, est.parts_per_plate
        cycle_src = f"{est.source}; {placement}"
        if (machine_override or {}).get("build_env_mm"):
            cycle_src += f"; work area declared for '{(machine_override or {}).get('machine_name')}'"
        drivers_out.append(Driver(
            name="parts_per_build", value=float(n), unit="parts",
            provenance=rates.prov_tag(f"xy_packing_density.{process.name}"),
            source=cycle_src,
        ))
    elif family == "additive":
        machine_hr, n, cycle_src = _additive_machine(process, drivers, rates, machine_override)
        pp_src = cycle_src
        pp_prov = rates.prov_tag(
            f"{'xy_packing_density' if rates.nesting_mode(process) == 'serial' else 'packing_density'}.{process.name}")
        drivers_out.append(Driver(
            name="parts_per_build", value=float(n), unit="parts",
            provenance=pp_prov,
            source=pp_src,
        ))
    elif family == "subtractive":
        machine_hr, finish_hr, cycle_src = _cnc_cycle(process, drivers, material_class, rates)
        n = 1
    elif family == "fabrication":
        machine_hr, cycle_src = _sheet_cycle(process, drivers, rates)
        n = 1
    elif family == "casting":
        machine_hr, cycle_src = _casting_cycle(process, drivers, material, rates)
        n = 1
    elif family == "forging":
        machine_hr, cycle_src = _forging_cycle(process, drivers, material, rates)
        n = 1
    elif family == "edm":
        machine_hr, edm_swept_mm2, edm_cut_hr, cycle_src = _edm_cycle(
            process, drivers, material_class, rates)
        n = 1
    elif family == "metal_powder_bed":
        # REUSE the build-job additive time model (full-build Z-sweep ÷ parts/build)
        # with metal params. Metal-only post (plate/support/stress-relief) added below.
        machine_hr, n, cycle_src = _additive_machine(process, drivers, rates, machine_override)
        if process in (PT.DMLS, PT.SLM):
            # de-20: two makers' names (EOS, SLM Solutions) for one process, so one price.
            cycle_src += ("; DMLS and SLM are two makers' names for laser powder-bed fusion, "
                          "so ScaleCAD prices them alike")
        drivers_out.append(Driver(
            name="parts_per_build", value=float(n), unit="parts",
            provenance=rates.prov_tag(f"packing_density.{process.name}"),
            source=cycle_src,
        ))
    elif family == "binder_jet":
        # green-part PRINT reuses the fast build-job model; debind+sinter added below.
        machine_hr, n, cycle_src = _additive_machine(process, drivers, rates, machine_override)
        drivers_out.append(Driver(
            name="parts_per_build", value=float(n), unit="parts",
            provenance=rates.prov_tag(f"packing_density.{process.name}"),
            source=cycle_src,
        ))
    elif family == "ded":
        machine_hr, ded_deposited_kg, cycle_src = _ded_cycle(process, drivers, material, rates)
        n = 1
    else:
        machine_hr, cycle_src = _formative_cycle(process, drivers, rates)
        n = 1

    # ---- lot model (weakness #8) + volume/learning economics (S1) -------
    # lot_size is the first production lot; it is the learning-curve anchor and
    # the per-lot setup basis, so compute it before machine/labor cost.
    setup_hr = rates.p(process, "setup_hr")
    lot_raw = rates.lot_size_raw(process)
    lot_size = n if lot_raw == "build" else int(lot_raw)
    # M14: the first lot pays a whole setup; past it, setups are shared per part
    # (parts beyond the last full build ride on a build shared with other work,
    # the full-plate assumption the machine time already makes). Rounding the
    # lot count up made 50 parts on 20-part plates pay three whole setups and
    # cost more each than 20: the price per part rose with quantity.
    # A machine, a mould or a die is set up once for the order and runs its
    # whole quantity (de-19: a 1,000-off order read "setup, shared over 1,000"
    # at the 100-off share, because it paid a setup every 100 parts). Printing
    # sets up each plate: setups follow the plates the order fills.
    per_plate = lot_raw == "build"
    n_setups = max(1.0, qty / lot_size) if per_plate else 1.0
    learn_mult, learn_src = _learning_multiplier(family, qty, lot_size, rates)

    # formative: a multi-cavity tool makes n_cavities parts per machine cycle
    cav_div = n_cavities if family == "formative" else 1
    # ── owned-equipment / in-house marginal machine rate (make-it-ourselves) ──
    # When the org OWNS this machine, its capital purchase/amortization is SUNK —
    # the marginal cost of one more part is material+energy+operator+consumables,
    # NOT the fully-loaded rate that recovers capital as if renting outside-shop
    # time. Cost the machine at machine_rate × (1 - machine_capital_frac); setup/
    # material/labor/finishing are unchanged. Gated on cap_frac > 0 so the
    # off-switch (machine_capital_frac=0.0) is byte-identical even when owned.
    # ── machine-SPECIFIC marginal rate (Phase C, spec §7 cost_breakdown) ──────
    # When a fitted OWNED machine from the org's declared inventory is handed in,
    # its OWN declared $/hr replaces the rate-card default and its OWN declared
    # capital_frac (or the card default when it declared none) drives the marginal
    # (make-it-ourselves) seam. The machine_cost driver is then tagged with the
    # machine's provenance (USER for a declared per-machine rate) and its source
    # NAMES the machine. machine_override is None on every generic call (no
    # inventory), so base_machine_rate / cap_frac / owned_here are UNCHANGED and
    # the whole path stays byte-identical.
    mo_rate = machine_override.get("hourly_rate_usd") if machine_override else None
    if machine_override is not None and isinstance(mo_rate, (int, float)) \
            and not isinstance(mo_rate, bool):
        base_machine_rate = float(mo_rate)
        _mo_cf = machine_override.get("capital_frac")
        cap_frac = (float(_mo_cf)
                    if isinstance(_mo_cf, (int, float)) and not isinstance(_mo_cf, bool)
                    else rates.g("machine_capital_frac"))
        owned_here = cap_frac > 0.0
        machine_name = machine_override.get("machine_name")
        machine_prov = machine_override.get("provenance") or Provenance.USER
    else:
        base_machine_rate = rates.p(process, "machine_rate")
        cap_frac = rates.g("machine_capital_frac")
        owned_here = bool(owned) and cap_frac > 0.0
        machine_name = None
        machine_prov = None
    eff_machine_rate = base_machine_rate * (1.0 - cap_frac) if owned_here else base_machine_rate
    machine_cost = machine_hr * eff_machine_rate / cav_div / util
    # ce-03: the machine's cycle is paced by its program and doesn't learn; only touch
    # labor (post-process hand work, in-process inspection) does (src.costing.learning).
    machine_scaled = machine_cost * rl_machine * mgn * burden   # E-now #2: labor-only region scaling
    owned_note = (f" × (1-{cap_frac:g}) on a machine you own: running cost only, the "
                  f"machine is already paid for (typical value, not confirmed by a shop)") if owned_here else ""
    cav_note = f" ÷ {n_cavities} cavities" if cav_div != 1 else ""
    util_note = f" ÷ {util:g} utilization" if util != 1.0 else ""
    learn_note = (f" × {learn_mult:.3f} learning (the average part of {qty:,}, from the first lot of "
                  f"{lot_size:g})") if learn_mult != 1.0 else ""
    if rl_machine != rl:
        _frac = rates.g("machine_labor_frac")
        region_mach_note = (f" × region-machine ×{rl_machine:g} (labor {_frac:g} of "
                            f"rate ×{rl:g}, capital global ×1) (typical value, not confirmed by a shop)")
    else:
        region_mach_note = f" × region-labor ×{rl_machine:g}"
    # machine-specific override: name the fitted machine, show its OWN rate, and
    # carry its provenance. No override => the card default rate + prov_tag,
    # byte-identical.
    if machine_name is not None:
        machine_prov_tag = machine_prov
        machine_rate_shown = base_machine_rate
        machine_name_note = f" (machine '{machine_name}', at its declared rate)"
    else:
        machine_prov_tag = rates.prov_tag(f"machine_rate.{process.name}")
        machine_rate_shown = rates.p(process, "machine_rate")
        machine_name_note = ""
    drivers_out.append(Driver(
        name="machine_cost", value=round(machine_scaled, 4), unit="$",
        provenance=machine_prov_tag,
        source=(f"{machine_hr:.4f} hr × ${machine_rate_shown:g}/hr{machine_name_note}"
                f"{owned_note}{cav_note}{util_note}{region_mach_note}{conversion_note}"
                f"; time: {cycle_src}"),
        error_band_pct=band,
    ))
    if owned_here:
        # First-class make-it-ourselves saving. The OWNED declaration is USER
        # (the org told us it owns this gear); the machine_capital_frac magnitude
        # removed is a DEFAULT assumption, not shop-validated. validated never
        # flips here — this is a structural sunk-cost adjustment, not a measured
        # number. Driver only (does not enter the line_items sum).
        _owned_subject = (f"machine '{machine_name}' you own"
                          if machine_name is not None else "a machine you own")
        _frac_prov = ("declared on the machine" if (machine_name is not None
                      and isinstance(machine_override.get("capital_frac"), (int, float))
                      and not isinstance(machine_override.get("capital_frac"), bool))
                      else "a typical value, not confirmed by a shop")
        drivers_out.append(Driver(
            name="owned_in_house", value=round(1.0 - cap_frac, 4), unit="×",
            provenance=Provenance.USER,
            source=(f"{_owned_subject}: machine time at the running-cost rate "
                    f"${eff_machine_rate:g}/hr = ${base_machine_rate:g}/hr × "
                    f"(1-{cap_frac:g} capital): the machine is already paid for, so its "
                    f"purchase isn't charged again. Ownership is as declared; the "
                    f"{cap_frac:g} capital share is {_frac_prov}"),
            error_band_pct=band,
        ))
    if rl_machine != rl:
        drivers_out.append(Driver(
            name="machine_region_split", value=round(rl_machine, 4), unit="×",
            provenance=Provenance.DEFAULT,
            source=(f"machine region multiplier ×{rl_machine:g}: only the labor share "
                    f"{rates.g('machine_labor_frac'):g} of the ${machine_rate_shown:g}/hr "
                    f"rate scales ×{rl:g}; capital/facility/energy stays global ×1 "
                    f"(fixes the whole-rate offshore over-discount) "
                    f"(typical value, not confirmed by a shop)"),
            error_band_pct=band,
        ))
    drivers_out.append(Driver(
        # Three significant figures under 0.01 hr: a tiny part's few seconds
        # rounded to 4 decimals read as "0.0 h" of machine time.
        name="cycle_time", value=(round(machine_hr, 4) if machine_hr >= 0.01
                                  else float(f"{machine_hr:.3g}")), unit="hr",
        provenance=Provenance.DEFAULT, source=cycle_src, error_band_pct=band,
    ))

    # ---- LABOR (post-process) — AM split, CNC/molding single ------------
    post_hr_part = rates.p(process, "post_hr_part")
    post_hr_build = rates.p(process, "post_hr_build")
    # FDM: support removal follows the surface the slicer supports, as checked (laid
    # another way with nothing to support, only the handling is left).
    support_cm2 = 0.0
    support_hr = 0.0
    if process == PT.FDM and print_plan is not None:
        support_cm2 = max(0.0, float(getattr(drivers.print_features, "fdm_need_cm2", 0.0) or 0.0))
        support_hr = rates.pget(process, "support_hr_per_cm2") * support_cm2
    elif process == PT.FDM:
        post_hr_part = rates.pget(process, "post_hr_part_unmeasured", post_hr_part)
    post_labor = (post_hr_part + support_hr + post_hr_build / n) * labor_rate
    post_labor_learned = post_labor * learn_mult         # touch labor learns (lot average, ce-03)
    labor_scaled = post_labor_learned * rl * mgn * burden
    support_note = ""
    if process == PT.FDM and print_plan is not None:
        support_note = (f" + support removal {rates.pget(process, 'support_hr_per_cm2'):g}hr/cm² × "
                        f"{support_cm2:.1f} cm² supported = {support_hr:.3g}hr" if support_cm2 > 0
                        else " + no support to remove")
        support_note += " (typical value, not confirmed by a shop)"
    if post_hr_build and n > 1:
        labor_src = (f"finish {post_hr_part:g}hr/part{support_note} + bulk {post_hr_build:g}hr/build "
                     f"÷ {n} ≈ {post_hr_part + support_hr + post_hr_build / n:.6g}hr × ${labor_rate:g}/hr"
                     f"{learn_note} × region-labor ×{rl:g}{conversion_note}")
    else:
        labor_src = (f"post-process {post_hr_part + support_hr + post_hr_build / n:.6g} hr{support_note} × "
                     f"${labor_rate:g}/hr{learn_note} × region-labor ×{rl:g}{conversion_note}")
    if family in ("casting", "forging"):
        # Said plainly: this time is per piece and doesn't grow with the part, so at
        # volume a casting or forging twice the size is barely dearer (the metal, which
        # does scale, is a small share of a small part's price).
        what = ("shakeout, fettling and cleaning" if family == "casting"
                else "descaling and flash cleanup")
        labor_src += (f"; {what} per piece, the same time at any size "
                      f"(typical value, not confirmed by a shop)")
    drivers_out.append(Driver(
        name="labor_cost", value=round(labor_scaled, 4), unit="$",
        provenance=rates.prov_tag("labor_rate"), source=labor_src, error_band_pct=20.0,
    ))

    # ---- learning-curve driver (glass box; only when it bites) ----------
    if learn_src is not None:
        drivers_out.append(Driver(
            name="learning_curve", value=round(learn_mult, 4), unit="×",
            provenance=Provenance.DEFAULT, source=learn_src, error_band_pct=band,
        ))

    # ---- SETUP per lot (weakness #8) ------------------------------------
    setup_per_unit = setup_hr * labor_rate * n_setups / qty
    setup_scaled = setup_per_unit * rl * mgn * burden
    drivers_out.append(Driver(
        name="setup_cost", value=round(setup_scaled, 4), unit="$",
        provenance=rates.prov_tag("labor_rate"),
        source=((f"setup {setup_hr:g}hr × ${labor_rate:g}/hr per plate × {qty}/{lot_size} parts a plate "
                 f"= {n_setups:.4g} plates (at least one) ÷ {qty} × region-labor ×{rl:g}{conversion_note}")
                if per_plate else
                (f"setup {setup_hr:g}hr × ${labor_rate:g}/hr once for the order ÷ {qty} "
                 f"× region-labor ×{rl:g}{conversion_note}")),
        error_band_pct=20.0,
    ))

    # ── E-now #3+#4: extra make-now cost lines (CNC scoped) ──────────────
    # These accumulate into the crossover fixed/variable split too.
    extra_fixed = 0.0          # one-time costs (amortize over the whole order) → fixed
    extra_variable = 0.0       # asymptotic per-unit (qty→∞) → variable

    # ---- E-now #3: CAM-programming NRE + FAI/inspection (qty-1 honesty) --
    # Today a qty-1 machined part is caught only by the min-charge floor. Real
    # shops charge a one-time CAM-programming/NRE plus first-article + in-process
    # inspection. Hours are DEFAULT assumptions, Zoox-caveated. CADVERIFY_CNC_NRE=0
    # removes both lines (byte-identical old cost).
    nre_scaled = 0.0
    inspection_scaled = 0.0
    fai_hr_order = 0.0   # first-article hours this order pays once (see the fixed split)
    if family == "subtractive" and os.getenv("CADVERIFY_CNC_NRE", "1") != "0":
        nre_hr = rates.pget(process, "nre_hr")
        fai_hr = rates.pget(process, "fai_hr")
        inspect_hr_part = rates.pget(process, "inspect_hr_part")
        if nre_hr > 0:
            nre_total = nre_hr * labor_rate * rl * mgn * burden      # one-time
            nre_scaled = nre_total / qty                              # amortized per unit
            extra_fixed += nre_total
            drivers_out.append(Driver(
                name="nre_cost", value=round(nre_scaled, 4), unit="$",
                provenance=rates.prov_tag(f"nre_hr.{process.name}"),
                source=(f"CAM programming/NRE {nre_hr:g}hr × ${labor_rate:g}/hr × "
                        f"region-labor ×{rl:g} ÷ {qty} order (one-time){conversion_note} "
                        f"(typical value, not confirmed by a shop)"),
                error_band_pct=40.0,
            ))
        inspect_part = inspect_hr_part * learn_mult                   # in-process inspection is touch labor: it learns
        fai_hr_order = fai_hr
        fai_per_unit = fai_hr * n_setups / qty                       # first article per setup
        insp_hr_per_unit = fai_per_unit + inspect_part
        if insp_hr_per_unit > 0:
            inspection_scaled = insp_hr_per_unit * labor_rate * rl * mgn * burden
            extra_variable += ((fai_hr / lot_size if per_plate else 0.0) + inspect_part) * labor_rate * rl * mgn * burden
            drivers_out.append(Driver(
                name="inspection_cost", value=round(inspection_scaled, 4), unit="$",
                provenance=rates.prov_tag(f"fai_hr.{process.name}"),
                source=(f"first-article {fai_hr:g}hr × {n_setups:.4g} setup(s) ÷ {qty} + in-process "
                        f"{inspect_hr_part:g}hr/part{learn_note} = {insp_hr_per_unit:.4f}hr × "
                        f"${labor_rate:g}/hr × region-labor ×{rl:g}{conversion_note} "
                        f"(typical value, not confirmed by a shop)"),
                error_band_pct=40.0,
            ))

    # ---- E-now #4a: perishable tooling / consumables (% of machine) -----
    consumables_scaled = 0.0
    if family == "subtractive" and os.getenv("CADVERIFY_PERISHABLE_TOOLING", "1") != "0":
        perishable_frac = rates.g("perishable_frac")
        if perishable_frac > 0:
            consumables_scaled = machine_scaled * perishable_frac
            extra_variable += consumables_scaled
            drivers_out.append(Driver(
                name="consumables_cost", value=round(consumables_scaled, 4), unit="$",
                provenance=Provenance.DEFAULT,
                source=(f"perishable tooling/consumables {perishable_frac:g} × machine "
                        f"${machine_scaled:.2f} (cutting tools, inserts, coolant) "
                        f"(typical value, not confirmed by a shop)"),
                error_band_pct=40.0,
            ))
    # ---- wire-EDM consumable: brass wire + dielectric/filter, ∝ cut time -----
    elif family == "edm":
        wire_per_hr = rates.p(process, "wire_cost_per_hr")
        if wire_per_hr > 0:
            # commodity consumable: regional material scaling + margin, no overhead burden
            consumables_scaled = edm_cut_hr * wire_per_hr * rm * mgn
            extra_variable += consumables_scaled
            drivers_out.append(Driver(
                name="consumables_cost", value=round(consumables_scaled, 4), unit="$",
                provenance=Provenance.DEFAULT,
                source=(f"wire-EDM consumable {edm_cut_hr:.3f} cut-hr × ${wire_per_hr:g}/hr "
                        f"(brass wire + dielectric/filter) × region-material ×{rm:g}{margin_note} "
                        f"(typical value, not confirmed by a shop)"),
                error_band_pct=40.0,
            ))

    # ---- E-now #4b: OUTSOURCED secondary finishing (lot + per-part) -----
    # Anodize / plate / heat-treat is bought from a vendor as a lot setup + a
    # per-part rate, NOT in-house labor hours. Default 0 (as-machined, no finish);
    # set finish_lot_charge / finish_per_part to enable. CADVERIFY_OUTSOURCED_FINISHING=0
    # forces it off even when configured (byte-identical old cost).
    finishing_scaled = 0.0
    fin_lot = rates.pget(process, "finish_lot_charge")
    fin_part = rates.pget(process, "finish_per_part")
    if (fin_lot > 0 or fin_part > 0) and os.getenv("CADVERIFY_OUTSOURCED_FINISHING", "1") != "0":
        fin_lot_per_unit = fin_lot * n_setups / qty
        finishing_per_unit = fin_lot_per_unit + fin_part
        finishing_scaled = finishing_per_unit * rl * mgn             # outsourced invoice: regional service + margin (no internal overhead burden)
        extra_variable += ((fin_lot / lot_size if per_plate else 0.0) + fin_part) * rl * mgn
        if not per_plate:
            extra_fixed += fin_lot * rl * mgn                         # one finishing lot for the order
        drivers_out.append(Driver(
            name="finishing_cost", value=round(finishing_scaled, 4), unit="$",
            provenance=rates.prov_tag(f"finish_per_part.{process.name}"),
            source=(f"outsourced finishing: lot ${fin_lot:g} × {n_setups:.4g} ÷ {qty} + "
                    f"${fin_part:g}/part = ${finishing_per_unit:.2f}/unit × region-labor ×{rl:g}{margin_note} "
                    f"(typical value, not confirmed by a shop)"),
            error_band_pct=40.0,
        ))

    # ── METAL-AM POST / FURNACE / FINISH (new families; pure additions) ──────
    # powder-bed: build-plate cut-off + support removal + stress-relief furnace
    #   (LABOR, each an inspectable line + driver) — the costs polymer AM never pays.
    # binder-jet: debind + SINTER furnace batch (furnace machine-time, batch-amortized).
    # DED/WAAM: a coarse finish-machining allowance (near-net ALWAYS needs finishing).
    # All feed extra_variable so the fixed/variable split and Σ line_items stay exact.
    metal_post_items: dict = {}     # powder-bed post-processing line items
    sinter_scaled = 0.0             # binder-jet debind+sinter furnace
    ded_finish_scaled = 0.0         # DED/WAAM finish-machining allowance
    if family == "metal_powder_bed":
        for line_key, drv_name, comp_hr, comp_src in _metal_am_post(process, n, rates):
            comp_cost = comp_hr * labor_rate * rl * mgn * burden
            metal_post_items[line_key] = round(comp_cost, 4)
            extra_variable += comp_cost
            drivers_out.append(Driver(
                name=drv_name, value=round(comp_cost, 4), unit="$",
                provenance=Provenance.DEFAULT,
                source=(f"{comp_src} × ${labor_rate:g}/hr × region-labor ×{rl:g}{conversion_note}"),
                error_band_pct=band,
            ))
    elif family == "binder_jet":
        sinter_hr_build = rates.p(process, "sinter_hr_build")
        sinter_rate = rates.p(process, "sinter_rate")
        psb_raw = rates.p(process, "parts_per_sinter_batch")
        n_sinter = int(psb_raw) if psb_raw and psb_raw > 0 else n
        sinter_per_part_hr = sinter_hr_build / n_sinter if n_sinter else sinter_hr_build
        sinter_cost = sinter_per_part_hr * sinter_rate
        sinter_scaled = sinter_cost * rl_machine * mgn * burden   # furnace = machine-like conversion
        extra_variable += sinter_scaled
        drivers_out.append(Driver(
            name="sinter_cost", value=round(sinter_scaled, 4), unit="$",
            provenance=Provenance.DEFAULT,
            source=(f"debind+sinter furnace {sinter_hr_build:g}hr/batch ÷ {n_sinter} parts/batch "
                    f"= {sinter_per_part_hr:.3f}hr × ${sinter_rate:g}/hr furnace × region-machine "
                    f"×{rl_machine:g}{conversion_note} (typical value, not confirmed by a shop)"),
            error_band_pct=band,
        ))
    elif family == "ded":
        # de-20: a deposited part is near-net (a bead surface, about ±1 mm): it is
        # finished on a 3-axis mill, priced as that mill prices it. Mill off the
        # overbuild and finish every surface, at the mill's rate, plus the mill's
        # setup and programming once for the order. (It was 30% of the deposition
        # cost, which put a wire-arc block level with milling it from solid.)
        mill = PT.CNC_3AXIS
        fm = rates.p(process, "feedstock_mult")
        overbuild_cm3 = drivers.volume_cm3 * max(fm - 1.0, 0.0)
        mrr = rates.mrr(material_class)
        rough_hr = overbuild_cm3 / (mrr * 60.0) if mrr > 0 else 0.0
        finish_hr = drivers.surface_area_cm2 / rates.p(mill, "finish")
        mill_hr = rough_hr + finish_hr
        mill_rate = rates.p(mill, "machine_rate")
        per_part = mill_hr * mill_rate * rl_machine * mgn * burden
        once_hr = rates.p(mill, "setup_hr") + rates.pget(mill, "nre_hr")
        once = once_hr * labor_rate * rl * mgn * burden
        ded_finish_scaled = per_part + once / qty
        extra_variable += per_part
        extra_fixed += once
        drivers_out.append(Driver(
            name="finish_machining", value=round(ded_finish_scaled, 4), unit="$",
            provenance=Provenance.DEFAULT,
            source=(f"finish machining on a 3-axis mill (a deposited part is near-net): mill off the "
                    f"{overbuild_cm3:.1f} cm³ overbuild ({rough_hr:.3f} hr) and finish {drivers.surface_area_cm2:.1f} cm² "
                    f"({finish_hr:.3f} hr) = {mill_hr:.3f} hr × ${mill_rate:g}/hr, + the mill's setup and "
                    f"programming {once_hr:g} hr × ${labor_rate:g}/hr once for the order ÷ {qty}{conversion_note} "
                    f"(typical value, not confirmed by a shop)"),
            error_band_pct=band,
        ))

    # ── DECLARED TOLERANCE CLASS (Aramco cost gap #4) ────────────────────
    # The caller DECLARED how tight this part is. Tighter tolerance means more
    # CNC finishing work + more inspection — the tolerance-SENSITIVE conversion
    # terms. Apply the DEFAULT multiplier to those terms ONLY: the finish-pass
    # share of machine time + inspection + any outsourced finishing. Roughing,
    # material and setup are NOT tolerance-driven and are deliberately excluded.
    # Non-machining families (additive/formative/fabrication) get NO honest
    # per-part cost surcharge in V0 — a molded/printed/sheet part's tolerance is
    # set by the tool/process, not by per-part finishing passes we can quantify —
    # so their cost is UNCHANGED (band still widens: uncertainty grows either
    # way). The DECLARATION is USER; the multiplier magnitude is a DEFAULT
    # assumption, not shop-validated. "standard" ⇒ mult 1.0, +0 band ⇒ NO line
    # item and NO driver ⇒ byte-identical to pre-change output. validated is
    # NEVER flipped here — this is an assumption multiplier, not a measurement.
    tolerance_surcharge = 0.0
    if family == "subtractive" and tol_cost_mult != 1.0:
        finish_machine_scaled = (machine_scaled * (finish_hr / machine_hr)
                                 if machine_hr > 0 else 0.0)
        tol_base = finish_machine_scaled + inspection_scaled + finishing_scaled
        tolerance_surcharge = tol_base * (tol_cost_mult - 1.0)
        extra_variable += tolerance_surcharge          # per-unit conversion cost
        drivers_out.append(Driver(
            name="tolerance_class", value=round(tol_cost_mult, 4), unit="×",
            provenance=Provenance.USER,
            source=(f"declared tolerance '{tolerance_class}' → ×{tol_cost_mult:g} on the "
                    f"tolerance-sensitive conversion terms (CNC finish pass "
                    f"${finish_machine_scaled:.2f} + inspection ${inspection_scaled:.2f}"
                    + (f" + finishing ${finishing_scaled:.2f}" if finishing_scaled else "")
                    + f" = ${tol_base:.2f}) = +${tolerance_surcharge:.2f}/unit; band widened "
                    f"+{tol_band_add:g}pts (uncertainty grows). You set the tolerance; the "
                    f"factor is a typical value, not confirmed by a shop"),
            error_band_pct=band,
        ))
    elif tol_cost_mult != 1.0 or tol_band_add != 0.0:
        drivers_out.append(Driver(
            name="tolerance_class", value=1.0, unit="×",
            provenance=Provenance.USER,
            source=(f"declared tolerance '{tolerance_class}': band widened +{tol_band_add:g}pts "
                    f"(uncertainty grows), but no per-part machining surcharge applies to a "
                    f"{family} part (its tolerance is set by the tool or process, not by "
                    f"per-part finishing passes), so the price is unchanged. You set the "
                    f"tolerance; typical value, not confirmed by a shop"),
            error_band_pct=band,
        ))

    # Reuse the part's enclosing stock candidate, not its uploaded-axis box.
    # Suppress transform roundoff at tier boundaries (six decimal places in mm).
    # M12: the tier reads the measured size, not the enclosing box's allowance
    # for STL coordinate rounding (2 × the coordinate error): a 300 mm STL cube
    # read 300.00005 mm and its tool jumped a tier, $30,000 to $60,000, against
    # the same part as STEP.
    tooling_size = (round(max(drivers.billet_bbox_mm) - float(getattr(drivers, "bbox_precision_mm", 0.0) or 0.0), 6)
                    if drivers.billet_bbox_mm else drivers.max_bbox_mm)
    tooling_basis = drivers.billet_basis if drivers.billet_bbox_mm else "file-axis fallback"
    # ponytail: size-tier proxy; a verified tool layout needs pull direction and allowances.
    tooling_note = "(estimated from the part's size; no tool was laid out; typical value, not confirmed by a shop)"
    # ---- TOOLING (formative only; cavity + complexity, weakness #5) -----
    if process in FORMATIVE:
        tooling_cost = rates.tooling_cost(process, tooling_size, n_cavities, complexity)
        flat = rates.data.get("_tooling_flat", {}).get(process) is not None
        if flat:
            tool_src = "your figure for the whole tool; ±60%"
        else:
            from src.costing.rates import family_to_size_tier
            tier = family_to_size_tier(tooling_size)
            cav = float(n_cavities) ** rates.data["cavity_exponent"]
            comp = rates.data["complexity_factor"][complexity]
            tool_src = (f"size tier {tier} (largest side {_tier_size_text(tooling_size, tier)}mm, {basis_words(tooling_basis)}) "
                        f"× {n_cavities} cav^{rates.data['cavity_exponent']:g} (={cav:.2f}) "
                        f"× {complexity} (={comp:.2f}) = ${tooling_cost:,.0f}; "
                        f"±60%, you can override it {tooling_note}")
        drivers_out.append(Driver(
            name="tooling_cost", value=round(tooling_cost, 2), unit="$",
            provenance=rates.prov_tag(f"tooling.{process.name}"),
            source=tool_src, error_band_pct=60.0,
        ))
    elif family in ("casting", "forging"):
        # ---- TOOLING (casting pattern / wax die+shell / forging die) --------
        # Size-tier base × family multiplier × complexity. Ordering: sand pattern
        # < investment (wax die + shell) < forging die. Amortized over qty below.
        tooling_cost = rates.casting_forging_tooling(process, tooling_size, complexity)
        flat = rates.data.get("_tooling_flat", {}).get(process) is not None
        if flat:
            tool_src = "your figure for the whole tool; ±55%"
        else:
            from src.costing.rates import family_to_size_tier
            tier = family_to_size_tier(tooling_size)
            if process in CASTING:
                mult = rates.data["tooling_casting_mult"][process]
                what = "pattern/core-box" if process == PT.SAND_CASTING else "wax die + ceramic shell"
            else:
                mult = rates.data["tooling_forging_mult"]
                what = "hardened closed-die set"
            comp = rates.data["complexity_factor"][complexity]
            tool_src = (f"{what}: size tier {tier} (largest side {_tier_size_text(tooling_size, tier)}mm, {basis_words(tooling_basis)}) "
                        f"× {mult:g} family-mult × {complexity} (={comp:.2f}) "
                        f"= ${tooling_cost:,.0f}; ±55%, you can override it "
                        f"{tooling_note}")
        drivers_out.append(Driver(
            name="tooling_cost", value=round(tooling_cost, 2), unit="$",
            provenance=rates.prov_tag(f"tooling.{process.name}"),
            source=tool_src, error_band_pct=55.0,
        ))
    else:
        tooling_cost = 0.0

    tooling_amort_scaled = (tooling_cost / qty) * rt * mgn

    # ---- assemble (base 4 keys + E-now #3/#4 lines when they apply) ------
    # Extra keys (nre/inspection/consumables/finishing) are added ONLY when
    # non-zero — every consumer iterates line_items generically, and the Σ ==
    # unit_cost invariant still holds (asserted below).
    line_items = {
        "amortized_fixed": round(tooling_amort_scaled + setup_scaled, 4),
        "material": round(material_scaled, 4),
        "machine": round(machine_scaled, 4),
        "labor": round(labor_scaled, 4),
    }
    if nre_scaled:
        line_items["nre"] = round(nre_scaled, 4)
    if inspection_scaled:
        line_items["inspection"] = round(inspection_scaled, 4)
    if consumables_scaled:
        line_items["consumables"] = round(consumables_scaled, 4)
    if finishing_scaled:
        line_items["finishing"] = round(finishing_scaled, 4)
    if tolerance_surcharge:
        line_items["tolerance"] = round(tolerance_surcharge, 4)
    # metal-AM additions (only present for the new families)
    for _k, _v in metal_post_items.items():
        if _v:
            line_items[_k] = _v
    if sinter_scaled:
        line_items["sinter"] = round(sinter_scaled, 4)
    if ded_finish_scaled:
        line_items["finish_machining"] = round(ded_finish_scaled, 4)
    unit_cost = round(sum(line_items.values()), 4)

    # ---- region split driver (when any factor ≠ 1.0) --------------------
    if rl != 1.0 or rm != 1.0 or rt != 1.0:
        drivers_out.append(Driver(
            name="region_split", value=0.0, unit=region,
            provenance=rates.region_prov(region),
            source=f"labor ×{rl:g} · material ×{rm:g} · tooling ×{rt:g}",
        ))

    # ---- MIN CHARGE clamp (weakness #3) — adds a line item only if it bites
    # M17: one minimum per order, not per production lot: DED/WAAM lots are 10
    # parts, so a $300 minimum per lot held every quantity at $30 a part or more.
    order_min = rates.min_charge(process)
    floor_per_unit = order_min / qty if qty else 0.0
    if floor_per_unit > unit_cost:
        delta = floor_per_unit - unit_cost
        line_items["min_charge_floor"] = round(delta, 4)
        unit_cost = round(sum(line_items.values()), 4)
        drivers_out.append(Driver(
            name="min_charge_floor", value=round(delta, 4), unit="$",
            provenance=rates.prov_tag(f"min_charge.{process.name}"),
            source=(f"order minimum ${rates.min_charge(process):g} ÷ {qty} = "
                    f"${floor_per_unit:.2f} a part (applied)"),
            error_band_pct=None,
        ))

    # ---- decision split (clean asymptotic fixed/var for crossover §6) ---
    # E-now #3/#4: NRE is a one-time cost (→ fixed, like tooling); consumables,
    # per-part inspection/finishing and the asymptotic per-lot inspection/finishing
    # shares are per-unit (→ variable). extra_fixed/extra_variable were accumulated
    # above. (The make-vs-buy crossover itself uses the exact numerical evaluator.)
    # C11: fixed is what this order pays once (tooling, programming, and its
    # first setup and first-article inspection, which every order needs),
    # variable the rest per part at this quantity, so fixed ÷ qty + variable is
    # exactly the unit price (it read $70 + $26.37 against $139.68 at qty 1:
    # the setup and first article were left out of both).
    first_setup_scaled = setup_hr * labor_rate * rl * mgn * burden
    first_article_scaled = (fai_hr_order * labor_rate * rl * mgn * burden)
    fixed_cost_usd = (tooling_cost * rt * mgn + extra_fixed
                      + min(first_setup_scaled + first_article_scaled,
                            max(0.0, unit_cost * qty - tooling_cost * rt * mgn - extra_fixed)))
    variable_cost_usd = unit_cost - fixed_cost_usd / qty

    # ---- DFM verdict pass-through ---------------------------------------
    dfm_ready = True
    dfm_verdict = "pass"
    dfm_score = 1.0
    dfm_blockers: list = []
    dfm_blocker_details: list = []
    if process_score is not None:
        dfm_verdict = process_score.verdict
        dfm_score = float(process_score.score)
        dfm_ready = process_score.verdict != "fail"
        # The ERROR-severity issues that block this process. Carry BOTH the
        # message strings (dfm_blockers — kept for existing text consumers) and
        # the full serialized Issue (dfm_blocker_details) so the cost view can
        # locate each blocker on the part (faces/region/measured/citation),
        # not merely restate its message. Same order, same source list.
        from src.analysis.serialization import serialize_issue

        error_issues = [
            i for i in process_score.issues
            if getattr(i.severity, "value", i.severity) == "error"
        ]
        dfm_blockers = [i.message for i in error_issues]
        dfm_blocker_details = [serialize_issue(i) for i in error_issues]

    est = CostEstimate(
        process=process.value,
        material=material.name,
        quantity=int(qty),
        unit_cost_usd=unit_cost,
        fixed_cost_usd=round(fixed_cost_usd, 4),
        variable_cost_usd=round(variable_cost_usd, 4),
        drivers=drivers_out,
        line_items=line_items,
        est_error_band_pct=reported_band,
        dfm_ready=dfm_ready,
        dfm_verdict=dfm_verdict,
        dfm_score=dfm_score,
        dfm_blockers=dfm_blockers,
        dfm_blocker_details=dfm_blocker_details,
        owned_in_house=owned_here,
        material_mass=material_mass,
    )
    est.assert_sums()
    return est
