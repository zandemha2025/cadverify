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

from src.analysis.models import ProcessType
from src.costing.drivers import parts_per_build
from src.costing.provenance import CostEstimate, Driver, Provenance
from src.costing.rates import (
    ADDITIVE, SUBTRACTIVE, FORMATIVE, FABRICATION, RateCard, process_family,
)

PT = ProcessType


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
        stock_vol = drivers.hull_volume_cm3 * rates.g("stock_allowance")
        stock_src = (f"hull {drivers.hull_volume_cm3:.1f} cm³ × "
                     f"{rates.g('stock_allowance'):.2f} = {stock_vol:.1f} cm³")
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


# ──────────────────────────────────────────────────────────────────────────
# Master cost breakdown
# ──────────────────────────────────────────────────────────────────────────
def cost_breakdown(process, drivers, material, material_class, qty,
                   rates: RateCard, region: str, n_cavities: int = 1,
                   complexity: str = "moderate", process_score=None) -> CostEstimate:
    family = process_family(process)
    labor_rate = rates.g("labor_rate")
    margin = rates.g("margin")
    overhead = rates.g("overhead")            # indirect burden on conversion cost (DEFAULT 0)
    utilization = rates.g("utilization")      # machine utilization (DEFAULT 1.0)
    scrap = rates.p(process, "scrap")
    band = rates.band_pct(process)

    rl = rates.region_labor(region)
    rm = rates.region_material(region)
    rt = rates.region_tooling(region)
    mgn = 1.0 + margin
    burden = 1.0 + overhead                   # applied to machine/labor/setup conversion cost
    util = utilization if utilization and utilization > 0 else 1.0

    drivers_out: list[Driver] = []

    # ---- MATERIAL --------------------------------------------------------
    if process in SUBTRACTIVE:
        input_mass = drivers.stock_mass_kg(material.density, rates.g("stock_allowance"))
        mass_src = drivers.stock_source(material.density, rates.g("stock_allowance"), material.name)
    elif process in FABRICATION:
        # you buy the rectangular blank (footprint × gauge), not just the net part
        input_mass = drivers.bbox_volume_cm3 * material.density / 1000.0
        mass_src = (f"sheet blank {drivers.bbox_mm[1]:.0f}×{drivers.bbox_mm[2]:.0f}×"
                    f"{drivers.sheet_gauge_mm:g}mm = {drivers.bbox_volume_cm3:.2f} cm³ × "
                    f"{material.name} density {material.density:.2f} g/cm³ (rectangular blank)")
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
    else:
        machine_hr, cycle_src = _formative_cycle(process, drivers, rates)
        n = 1

    # formative: a multi-cavity tool makes n_cavities parts per machine cycle
    cav_div = n_cavities if family == "formative" else 1
    machine_cost = machine_hr * rates.p(process, "machine_rate") / cav_div / util
    machine_scaled = machine_cost * rl * mgn * burden
    cav_note = f" ÷ {n_cavities} cavities" if cav_div != 1 else ""
    util_note = f" ÷ {util:g} utilization" if util != 1.0 else ""
    burden_note = f" × {burden:g} overhead" if burden != 1.0 else ""
    drivers_out.append(Driver(
        name="machine_cost", value=round(machine_scaled, 4), unit="$",
        provenance=rates.prov_tag(f"machine_rate.{process.name}"),
        source=(f"{machine_hr:.4f} hr × ${rates.p(process, 'machine_rate'):g}/hr"
                f"{cav_note}{util_note} × region-labor ×{rl:g}{burden_note}  [{cycle_src}]"),
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
    labor_scaled = post_labor * rl * mgn * burden
    if post_hr_build and n > 1:
        labor_src = (f"finish {post_hr_part:g}hr/part + bulk {post_hr_build:g}hr/build "
                     f"÷ {n} = {post_hr_part + post_hr_build / n:.3f}hr × ${labor_rate:g}/hr "
                     f"× region-labor ×{rl:g}")
    else:
        labor_src = (f"post-process {post_hr_part + post_hr_build / n:g} hr × "
                     f"${labor_rate:g}/hr × region-labor ×{rl:g}")
    drivers_out.append(Driver(
        name="labor_cost", value=round(labor_scaled, 4), unit="$",
        provenance=rates.prov_tag("labor_rate"), source=labor_src, error_band_pct=20.0,
    ))

    # ---- SETUP per lot (weakness #8) ------------------------------------
    setup_hr = rates.p(process, "setup_hr")
    lot_raw = rates.lot_size_raw(process)
    lot_size = n if lot_raw == "build" else int(lot_raw)
    n_setups = math.ceil(qty / lot_size)
    setup_per_unit = setup_hr * labor_rate * n_setups / qty
    setup_scaled = setup_per_unit * rl * mgn * burden
    drivers_out.append(Driver(
        name="setup_cost", value=round(setup_scaled, 4), unit="$",
        provenance=rates.prov_tag("labor_rate"),
        source=(f"setup {setup_hr:g}hr × ${labor_rate:g}/hr × ceil({qty}/{lot_size}) "
                f"= {n_setups} setups ÷ {qty} × region-labor ×{rl:g}"),
        error_band_pct=20.0,
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
    else:
        tooling_cost = 0.0

    tooling_amort_scaled = (tooling_cost / qty) * rt * mgn

    # ---- assemble (4-key line_items; Σ invariant) -----------------------
    line_items = {
        "amortized_fixed": round(tooling_amort_scaled + setup_scaled, 4),
        "material": round(material_scaled, 4),
        "machine": round(machine_scaled, 4),
        "labor": round(labor_scaled, 4),
    }
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
    setup_asymptotic_scaled = (setup_hr * labor_rate / lot_size) * rl * mgn * burden
    fixed_cost_usd = tooling_cost * rt * mgn
    variable_cost_usd = material_scaled + machine_scaled + labor_scaled + setup_asymptotic_scaled

    # ---- DFM verdict pass-through ---------------------------------------
    dfm_ready = True
    dfm_verdict = "pass"
    dfm_score = 1.0
    dfm_blockers: list = []
    if process_score is not None:
        dfm_verdict = process_score.verdict
        dfm_score = float(process_score.score)
        dfm_ready = process_score.verdict != "fail"
        dfm_blockers = [
            i.message for i in process_score.issues
            if getattr(i.severity, "value", i.severity) == "error"
        ]

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
    )
    est.assert_sums()
    return est
