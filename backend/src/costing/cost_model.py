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
  #8     setup recurs per lot: ceil(qty / lot_size) setups, not one over the lot.

    line_items = {amortized_fixed, material, machine, labor}   (4-key shape kept)
    unit_cost  = Σ line_items   (+ min_charge_floor when the order floor bites)
"""

from __future__ import annotations

import math
import os

from src.analysis.models import ProcessType
from src.costing.drivers import parts_per_build
from src.costing.provenance import CostEstimate, Driver, Provenance
from src.costing.rates import (
    ADDITIVE, SUBTRACTIVE, FORMATIVE, FABRICATION, CASTING, FORGING_FAMILY, EDM,
    RateCard, process_family,
)

PT = ProcessType

# Master on/off for the volume/learning economics (S1 fix). Defaults ON (the
# corrected behavior that fixes the demo path). Set CADVERIFY_CNC_LEARNING=0 to
# recover the old flat, volume-invariant conversion cost. (A learning_rate=1.0
# rate override is the equivalent per-quote off-switch.)
_LEARNING_FAMILIES = {"subtractive", "fabrication"}


def _learning_multiplier(family, qty, ref_qty, rates: RateCard):
    """Wright cumulative-average learning multiplier on ATTENDED CONVERSION cost.

    Real machining/fabrication economics: per-unit attended time (machine cycle +
    hand labor) falls as cumulative volume grows — optimized tool-paths, dedicated
    fixtures/pallets, dialed-in feeds & speeds, less operator attention. Modeled as
    the classic Wright curve, cumulative-average form:

        mult(Q) = (Q / Q_ref) ** b ,  b = log2(learning_rate) < 0 ,  clamped ≤ 1

    Q_ref = the first production lot (lot_size): the rate-card cycle time is the
    first-lot standard time, so no learning is credited at/below one lot (mult=1),
    and it accrues only above it. Floored at ``learning_floor`` (a practical
    minimum cycle time). learning_rate=1.0 (or CADVERIFY_CNC_LEARNING=0) => 1.0.

    Returns (multiplier, source_string). The source is honestly tagged as a
    DEFAULT assumption, NOT validated against real shop quotes.
    """
    if os.getenv("CADVERIFY_CNC_LEARNING", "1") == "0":
        return 1.0, None
    if family not in _LEARNING_FAMILIES:
        return 1.0, None
    rate = rates.g("learning_rate")
    if not rate or rate >= 1.0 or ref_qty <= 0 or qty <= ref_qty:
        return 1.0, None
    floor = rates.g("learning_floor")
    b = math.log(rate) / math.log(2.0)
    mult = (qty / ref_qty) ** b
    mult = max(mult, floor)
    doublings = math.log(qty / ref_qty) / math.log(2.0)
    src = (f"learning curve {rate:g}×/doubling of cumulative qty on machine+labor: "
           f"({qty}/{ref_qty} first-lot)^{b:.3f} = ×{mult:.3f} "
           f"(~{doublings:.1f} doublings, floor {floor:g}) "
           f"[assumption, not shop-validated]")
    return mult, src


# ──────────────────────────────────────────────────────────────────────────
# MACHINE sub-models. Additive returns (machine_hr, parts_per_build, src);
# subtractive/formative return (cycle_hr, src) with parts_per_build = 1.
# ──────────────────────────────────────────────────────────────────────────
def _additive_machine(process, drivers, rates: RateCard):
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
    n = parts_per_build(process, drivers.bbox_mm, rates)
    mode = rates.nesting_mode(process)
    if mode == "build_job":
        Z = rates.build_env(process)[2]
        vert = rates.p(process, "vert")
        build_job_hr = Z / vert                       # full-build duration (height-driven)
        machine_hr = build_job_hr / n                 # this part's amortized share
        src = (f"build-job {Z:g}mm ÷ {vert:g}mm/hr = {build_job_hr:.1f}hr full build "
               f"÷ {n} parts/build (packing {rates.packing_density(process):g}, "
               f"env {rates.build_env(process)}) = {machine_hr:.3f}hr/part")
    else:  # serial (FDM single nozzle / SLA laser): XY-nested plate
        dep = rates.p(process, "deposition")
        vert = rates.p(process, "vert")
        build_h = drivers.bbox_mm[0]                  # smallest extent = build height
        deposition_hr = drivers.volume_cm3 / dep      # per-part — single nozzle/laser, irreducible
        sweep_hr = (build_h / vert) / n               # per-PLATE Z-climb, amortized over the XY nest
        machine_hr = deposition_hr + sweep_hr
        src = (f"serial XY-nested: deposition V/{dep:g} = {drivers.volume_cm3:.2f}/{dep:g} "
               f"= {deposition_hr:.3f}hr/part (per-part nozzle) + Z-sweep "
               f"({build_h:.1f}/{vert:g})÷{n} parts/plate = {sweep_hr:.3f}hr/part "
               f"(plate Z-climb amortized; XY packing {rates.xy_packing_density(process):g}, "
               f"plate {rates.build_env(process)[0]:g}×{rates.build_env(process)[1]:g}mm) "
               f"= {machine_hr:.3f}hr/part")
    return machine_hr, n, src


def _cnc_cycle(process, drivers, material_class, rates: RateCard):
    """Material-removal model: rough (remove billet→part) + finish (surface area)."""
    if process == PT.CNC_TURNING:
        r = drivers.rot_cross_dia_mm / 2.0
        stock_vol = math.pi * r * r * drivers.rot_axis_len_mm / 1000.0
        stock_src = (f"bounding cylinder π·({drivers.rot_cross_dia_mm:.1f}/2)²·"
                     f"{drivers.rot_axis_len_mm:.1f} mm = {stock_vol:.1f} cm³")
    else:
        # E-now #1: mill from a rectangular BILLET (bounding box), not a hull —
        # a pocketed part is cut from a solid block, so more is roughed away.
        from src.costing.drivers import bbox_billet_enabled
        allow = rates.g("stock_allowance")
        stock_vol = drivers.billet_volume_cm3(allow)
        if bbox_billet_enabled():
            stock_src = (f"bbox billet {drivers.bbox_volume_cm3:.1f} cm³ × {allow:.2f} "
                         f"= {stock_vol:.1f} cm³ [assumption, not shop-validated]")
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
           f"= {finish_hr:.3f} hr  [stock {stock_src}; MRR {material_class}]")
    return cycle, src


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
           f"[foundry assumption, not shop-validated]")
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
           f"+ trim {trim_hr:g}hr = {cycle:.4f} hr  (near-net blank — finish machining "
           f"NOT bundled) [forge assumption, not shop-validated]")
    return cycle, src


def _edm_cycle(process, drivers, material_class, rates: RateCard):
    """Wire-EDM cut-path model: swept cross-section AREA ÷ a very slow EDM cut rate,
    plus wire-threading per contour.

      swept area = cut-path length × stock thickness.
                   PROXY: cut-path length = drivers.outline_perimeter_mm (the
                   MEASURED 2D outline/cutout length); stock thickness = the
                   smallest bbox extent (the plate the wire cuts through). This is
                   an APPROXIMATION — there is no true 3D cut-perimeter driver — and
                   is flagged as such in the source string.
      cut time   = swept area ÷ edm_cut_rate(material) (mm²/hr — slow, material-set).
      thread     = n_threads contours × thread_min (auto-wire-thread + re-reference).

    Returns (machine_hr, swept_area_mm2, cut_hr, src). Wire consumable is costed
    separately (∝ cut time). All constants DEFAULT, un-validated.
    """
    dd = sorted(drivers.bbox_mm)                 # ascending: dd[0] = stock thickness
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
           f"= {cycle:.4f} hr  [cut-path = outline_perimeter × min-bbox-extent PROXY, "
           f"not a true 3D cut perimeter; assumption, not shop-validated]")
    return cycle, swept_area, cut_hr, src


# ──────────────────────────────────────────────────────────────────────────
# Master cost breakdown
# ──────────────────────────────────────────────────────────────────────────
def cost_breakdown(process, drivers, material, material_class, qty,
                   rates: RateCard, region: str, n_cavities: int = 1,
                   complexity: str = "moderate", process_score=None,
                   owned: bool = False) -> CostEstimate:
    family = process_family(process)
    labor_rate = rates.g("labor_rate")
    margin = rates.g("margin")
    overhead = rates.g("overhead")            # indirect burden on conversion cost (DEFAULT 0)
    utilization = rates.g("utilization")      # machine utilization (DEFAULT 1.0)
    scrap = rates.p(process, "scrap")
    band = rates.band_pct(process)

    rl = rates.region_labor(region)
    rl_machine = rates.machine_region_mult(region)   # E-now #2: labor-only region scaling of the blended machine rate
    rm = rates.region_material(region)
    rt = rates.region_tooling(region)
    mgn = 1.0 + margin
    burden = 1.0 + overhead                   # applied to machine/labor/setup conversion cost
    util = utilization if utilization and utilization > 0 else 1.0

    drivers_out: list[Driver] = []

    # ---- MATERIAL --------------------------------------------------------
    if process == PT.CNC_TURNING:
        # turning starts from round bar (hull ≈ swept solid) — billet unchanged
        input_mass = drivers.stock_mass_kg(material.density, rates.g("stock_allowance"))
        mass_src = drivers.stock_source(material.density, rates.g("stock_allowance"), material.name)
    elif process in SUBTRACTIVE:
        # E-now #1: milling billet = bounding-box block × allowance (was hull)
        input_mass = drivers.billet_mass_kg(material.density, rates.g("stock_allowance"))
        mass_src = drivers.billet_source(material.density, rates.g("stock_allowance"), material.name)
    elif process in FABRICATION:
        # you buy the rectangular blank (footprint × gauge), not just the net part
        input_mass = drivers.bbox_volume_cm3 * material.density / 1000.0
        mass_src = (f"sheet blank {drivers.bbox_mm[1]:.0f}×{drivers.bbox_mm[2]:.0f}×"
                    f"{drivers.sheet_gauge_mm:g}mm = {drivers.bbox_volume_cm3:.2f} cm³ × "
                    f"{material.name} density {material.density:.2f} g/cm³ (rectangular blank)")
    elif process in CASTING:
        # poured metal = net part mass × (1 + yield_loss) for gating + risers
        net_mass = drivers.mass_kg(material.density)
        yl = rates.p(process, "yield_loss")
        input_mass = net_mass * (1.0 + yl)
        mass_src = (f"poured metal = net {net_mass:.4f} kg (CAD volume "
                    f"{drivers.volume_cm3:.2f} cm³ × {material.name} density "
                    f"{material.density:.2f} g/cm³) × (1+{yl:g} gating/riser yield) "
                    f"[foundry assumption, not shop-validated]")
    elif process in FORGING_FAMILY:
        # billet from bar stock = net part mass × (1 + flash/scale loss)
        net_mass = drivers.mass_kg(material.density)
        fl = rates.p(process, "flash_loss")
        input_mass = net_mass * (1.0 + fl)
        mass_src = (f"billet from bar = net {net_mass:.4f} kg (CAD volume "
                    f"{drivers.volume_cm3:.2f} cm³ × {material.name} density "
                    f"{material.density:.2f} g/cm³) × (1+{fl:g} flash/scale loss) "
                    f"[forge assumption, not shop-validated]")
    elif process in EDM:
        # wire-EDM cuts the part from a solid billet plate (bbox block × allowance)
        input_mass = drivers.billet_mass_kg(material.density, rates.g("stock_allowance"))
        mass_src = drivers.billet_source(material.density, rates.g("stock_allowance"), material.name)
    else:
        input_mass = drivers.mass_kg(material.density)
        mass_src = drivers.mass_source(material.density, material.name)
    # shop lot price when the active profile binds one; else generic material-DB price
    price_per_kg, price_prov, price_note = rates.material_price(
        material.name, material_class, material.cost_per_kg)
    material_cost = input_mass * price_per_kg * (1.0 + scrap)
    material_scaled = material_cost * rm * mgn
    drivers_out.append(Driver(
        name="material_cost", value=round(material_scaled, 4), unit="$",
        provenance=price_prov,
        source=(f"{mass_src} = {input_mass:.4f} kg × ${price_per_kg:g}/kg ({price_note}) "
                f"× (1+{scrap:g} scrap) × region-material ×{rm:g}"),
        error_band_pct=5.0,
    ))

    # ---- MACHINE ---------------------------------------------------------
    if family == "additive":
        machine_hr, n, cycle_src = _additive_machine(process, drivers, rates)
        if rates.nesting_mode(process) == "serial":
            pp_src = (f"XY nest: plate {rates.build_env(process)[0]:g}×"
                      f"{rates.build_env(process)[1]:g}mm × xy_packing "
                      f"{rates.xy_packing_density(process):g} ÷ footprint "
                      f"({drivers.bbox_mm[1]:.1f}×{drivers.bbox_mm[2]:.1f}+"
                      f"{rates.part_spacing(process):g}mm) = {n} parts/plate")
            pp_prov = rates.prov_tag(f"xy_packing_density.{process.name}")
        else:
            pp_src = (f"nesting: packing {rates.packing_density(process):g} × env "
                      f"{rates.build_env(process)} ÷ part bbox {tuple(drivers.bbox_mm)}+"
                      f"{rates.part_spacing(process):g}mm spacing = {n} parts/build")
            pp_prov = rates.prov_tag(f"packing_density.{process.name}")
        drivers_out.append(Driver(
            name="parts_per_build", value=float(n), unit="parts",
            provenance=pp_prov,
            source=pp_src,
        ))
    elif family == "subtractive":
        machine_hr, cycle_src = _cnc_cycle(process, drivers, material_class, rates)
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
    else:
        machine_hr, cycle_src = _formative_cycle(process, drivers, rates)
        n = 1

    # ---- lot model (weakness #8) + volume/learning economics (S1) -------
    # lot_size is the first production lot; it is the learning-curve anchor and
    # the per-lot setup basis, so compute it before machine/labor cost.
    setup_hr = rates.p(process, "setup_hr")
    lot_raw = rates.lot_size_raw(process)
    lot_size = n if lot_raw == "build" else int(lot_raw)
    n_setups = math.ceil(qty / lot_size)
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
    base_machine_rate = rates.p(process, "machine_rate")
    cap_frac = rates.g("machine_capital_frac")
    owned_here = bool(owned) and cap_frac > 0.0
    eff_machine_rate = base_machine_rate * (1.0 - cap_frac) if owned_here else base_machine_rate
    machine_cost = machine_hr * eff_machine_rate / cav_div / util
    machine_learned = machine_cost * learn_mult          # attended-time learning (S1)
    machine_scaled = machine_learned * rl_machine * mgn * burden   # E-now #2: labor-only region scaling
    owned_note = (f" × (1-{cap_frac:g} capital sunk) OWNED-IN-HOUSE marginal "
                  f"[assumption, not shop-validated]") if owned_here else ""
    cav_note = f" ÷ {n_cavities} cavities" if cav_div != 1 else ""
    util_note = f" ÷ {util:g} utilization" if util != 1.0 else ""
    burden_note = f" × {burden:g} overhead" if burden != 1.0 else ""
    learn_note = f" × {learn_mult:.3f} learning@qty{qty}" if learn_mult != 1.0 else ""
    if rl_machine != rl:
        _frac = rates.g("machine_labor_frac")
        region_mach_note = (f" × region-machine ×{rl_machine:g} (labor {_frac:g} of "
                            f"rate ×{rl:g}, capital global ×1) [assumption, not shop-validated]")
    else:
        region_mach_note = f" × region-labor ×{rl_machine:g}"
    drivers_out.append(Driver(
        name="machine_cost", value=round(machine_scaled, 4), unit="$",
        provenance=rates.prov_tag(f"machine_rate.{process.name}"),
        source=(f"{machine_hr:.4f} hr × ${rates.p(process, 'machine_rate'):g}/hr"
                f"{owned_note}{cav_note}{util_note}{learn_note}{region_mach_note}{burden_note}"
                f"  [{cycle_src}]"),
        error_band_pct=band,
    ))
    if owned_here:
        # First-class make-it-ourselves saving. The OWNED declaration is USER
        # (the org told us it owns this gear); the machine_capital_frac magnitude
        # removed is a DEFAULT assumption, not shop-validated. validated never
        # flips here — this is a structural sunk-cost adjustment, not a measured
        # number. Driver only (does not enter the line_items sum).
        drivers_out.append(Driver(
            name="owned_in_house", value=round(1.0 - cap_frac, 4), unit="×",
            provenance=Provenance.USER,
            source=(f"process OWNED in-house: machine costed at MARGINAL rate "
                    f"${eff_machine_rate:g}/hr = ${base_machine_rate:g}/hr × "
                    f"(1-{cap_frac:g} capital) — capital purchase/amortization removed "
                    f"(sunk on gear the org already owns; make-it-ourselves, not "
                    f"rent-the-time). USER-declared ownership; the {cap_frac:g} capital "
                    f"fraction is DEFAULT [assumption, not shop-validated]"),
            error_band_pct=band,
        ))
    if rl_machine != rl:
        drivers_out.append(Driver(
            name="machine_region_split", value=round(rl_machine, 4), unit="×",
            provenance=Provenance.DEFAULT,
            source=(f"machine region multiplier ×{rl_machine:g}: only the labor share "
                    f"{rates.g('machine_labor_frac'):g} of the ${rates.p(process,'machine_rate'):g}/hr "
                    f"rate scales ×{rl:g}; capital/facility/energy stays global ×1 "
                    f"(fixes the whole-rate offshore over-discount) "
                    f"[assumption, not shop-validated]"),
            error_band_pct=band,
        ))
    drivers_out.append(Driver(
        name="cycle_time", value=round(machine_hr, 4), unit="hr",
        provenance=Provenance.DEFAULT, source=cycle_src, error_band_pct=band,
    ))

    # ---- LABOR (post-process) — AM split, CNC/molding single ------------
    post_hr_part = rates.p(process, "post_hr_part")
    post_hr_build = rates.p(process, "post_hr_build")
    post_labor = (post_hr_part + post_hr_build / n) * labor_rate
    post_labor_learned = post_labor * learn_mult         # attended-time learning (S1)
    labor_scaled = post_labor_learned * rl * mgn * burden
    if post_hr_build and n > 1:
        labor_src = (f"finish {post_hr_part:g}hr/part + bulk {post_hr_build:g}hr/build "
                     f"÷ {n} = {post_hr_part + post_hr_build / n:.3f}hr × ${labor_rate:g}/hr"
                     f"{learn_note} × region-labor ×{rl:g}")
    else:
        labor_src = (f"post-process {post_hr_part + post_hr_build / n:g} hr × "
                     f"${labor_rate:g}/hr{learn_note} × region-labor ×{rl:g}")
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
        source=(f"setup {setup_hr:g}hr × ${labor_rate:g}/hr × ceil({qty}/{lot_size}) "
                f"= {n_setups} setups ÷ {qty} × region-labor ×{rl:g}"),
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
                        f"region-labor ×{rl:g} ÷ {qty} order (one-time) "
                        f"[assumption, not shop-validated]"),
                error_band_pct=40.0,
            ))
        inspect_part = inspect_hr_part * learn_mult                   # per-part (learns/samples down at volume)
        fai_per_unit = fai_hr * n_setups / qty                       # first article per lot
        insp_hr_per_unit = fai_per_unit + inspect_part
        if insp_hr_per_unit > 0:
            inspection_scaled = insp_hr_per_unit * labor_rate * rl * mgn * burden
            extra_variable += (fai_hr / lot_size + inspect_part) * labor_rate * rl * mgn * burden
            drivers_out.append(Driver(
                name="inspection_cost", value=round(inspection_scaled, 4), unit="$",
                provenance=rates.prov_tag(f"fai_hr.{process.name}"),
                source=(f"first-article {fai_hr:g}hr × {n_setups} lot(s) ÷ {qty} + in-process "
                        f"{inspect_hr_part:g}hr/part{learn_note} = {insp_hr_per_unit:.4f}hr × "
                        f"${labor_rate:g}/hr × region-labor ×{rl:g} "
                        f"[assumption, not shop-validated]"),
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
                        f"[assumption, not shop-validated]"),
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
                        f"(brass wire + dielectric/filter) × region-material ×{rm:g} "
                        f"[assumption, not shop-validated]"),
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
        extra_variable += (fin_lot / lot_size + fin_part) * rl * mgn
        drivers_out.append(Driver(
            name="finishing_cost", value=round(finishing_scaled, 4), unit="$",
            provenance=rates.prov_tag(f"finish_per_part.{process.name}"),
            source=(f"outsourced finishing: lot ${fin_lot:g} × {n_setups} ÷ {qty} + "
                    f"${fin_part:g}/part = ${finishing_per_unit:.2f}/unit × region-labor ×{rl:g} "
                    f"[assumption, not shop-validated]"),
            error_band_pct=40.0,
        ))

    # ---- TOOLING (formative only; cavity + complexity, weakness #5) -----
    if process in FORMATIVE:
        tooling_cost = rates.tooling_cost(process, drivers.max_bbox_mm, n_cavities, complexity)
        flat = rates.data.get("_tooling_flat", {}).get(process) is not None
        if flat:
            tool_src = "flat USER override (whole tool); ±60%, OVERRIDABLE"
        else:
            from src.costing.rates import family_to_size_tier
            tier = family_to_size_tier(drivers.max_bbox_mm)
            cav = float(n_cavities) ** rates.data["cavity_exponent"]
            comp = rates.data["complexity_factor"][complexity]
            tool_src = (f"size tier {tier} (max bbox {drivers.max_bbox_mm:.0f}mm) "
                        f"× {n_cavities} cav^{rates.data['cavity_exponent']:g} (={cav:.2f}) "
                        f"× {complexity} (={comp:.2f}) = ${tooling_cost:,.0f}; "
                        f"±60%, OVERRIDABLE")
        drivers_out.append(Driver(
            name="tooling_cost", value=round(tooling_cost, 2), unit="$",
            provenance=rates.prov_tag(f"tooling.{process.name}"),
            source=tool_src, error_band_pct=60.0,
        ))
    elif family in ("casting", "forging"):
        # ---- TOOLING (casting pattern / wax die+shell / forging die) --------
        # Size-tier base × family multiplier × complexity. Ordering: sand pattern
        # < investment (wax die + shell) < forging die. Amortized over qty below.
        tooling_cost = rates.casting_forging_tooling(process, drivers.max_bbox_mm, complexity)
        flat = rates.data.get("_tooling_flat", {}).get(process) is not None
        if flat:
            tool_src = "flat USER override (whole tool); ±55%, OVERRIDABLE"
        else:
            from src.costing.rates import family_to_size_tier
            tier = family_to_size_tier(drivers.max_bbox_mm)
            if process in CASTING:
                mult = rates.data["tooling_casting_mult"][process]
                what = "pattern/core-box" if process == PT.SAND_CASTING else "wax die + ceramic shell"
            else:
                mult = rates.data["tooling_forging_mult"]
                what = "hardened closed-die set"
            comp = rates.data["complexity_factor"][complexity]
            tool_src = (f"{what}: size tier {tier} (max bbox {drivers.max_bbox_mm:.0f}mm) "
                        f"× {mult:g} family-mult × {complexity} (={comp:.2f}) "
                        f"= ${tooling_cost:,.0f}; ±55%, OVERRIDABLE "
                        f"[assumption, not shop-validated]")
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
    unit_cost = round(sum(line_items.values()), 4)

    # ---- region split driver (when any factor ≠ 1.0) --------------------
    if rl != 1.0 or rm != 1.0 or rt != 1.0:
        drivers_out.append(Driver(
            name="region_split", value=0.0, unit=region,
            provenance=rates.region_prov(region),
            source=f"labor ×{rl:g} · material ×{rm:g} · tooling ×{rt:g}",
        ))

    # ---- MIN CHARGE clamp (weakness #3) — adds a line item only if it bites
    order_min = rates.min_charge(process) * n_setups
    floor_per_unit = order_min / qty if qty else 0.0
    if floor_per_unit > unit_cost:
        delta = floor_per_unit - unit_cost
        line_items["min_charge_floor"] = round(delta, 4)
        unit_cost = round(sum(line_items.values()), 4)
        drivers_out.append(Driver(
            name="min_charge_floor", value=round(delta, 4), unit="$",
            provenance=rates.prov_tag(f"min_charge.{process.name}"),
            source=(f"shop/order minimum ${rates.min_charge(process):g}/lot × {n_setups} "
                    f"lots ÷ {qty} = ${floor_per_unit:.2f}/unit floor (applied)"),
            error_band_pct=None,
        ))

    # ---- decision split (clean asymptotic fixed/var for crossover §6) ---
    # E-now #3/#4: NRE is a one-time cost (→ fixed, like tooling); consumables,
    # per-part inspection/finishing and the asymptotic per-lot inspection/finishing
    # shares are per-unit (→ variable). extra_fixed/extra_variable were accumulated
    # above. (The make-vs-buy crossover itself uses the exact numerical evaluator.)
    setup_asymptotic_scaled = (setup_hr * labor_rate / lot_size) * rl * mgn * burden
    fixed_cost_usd = tooling_cost * rt * mgn + extra_fixed
    variable_cost_usd = (material_scaled + machine_scaled + labor_scaled
                         + setup_asymptotic_scaled + extra_variable)

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
        est_error_band_pct=band,
        dfm_ready=dfm_ready,
        dfm_verdict=dfm_verdict,
        dfm_score=dfm_score,
        dfm_blockers=dfm_blockers,
        dfm_blocker_details=dfm_blocker_details,
        owned_in_house=owned_here,
    )
    est.assert_sums()
    return est
