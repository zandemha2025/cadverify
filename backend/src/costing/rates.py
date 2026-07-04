"""RATE_CARD_V0 — the concrete, reproducible default cost table (spec §6.3).

Every value here is a DEFAULT (a stated assumption, not claimed truth) and is
overridable via EstimateOptions.rate_overrides. Overridden values become USER
provenance and the report shows both the default and the override.

Nothing in this file is the toy `cost_per_cm3` model. These are itemized shop
drivers (machine $/hr, setup hr, MRR, tooling tiers) that feed the explicit
master formula in cost_model.py.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from src.analysis.models import ProcessType

PT = ProcessType

# Process families (drive cycle-time sub-model + error band)
ADDITIVE = {PT.FDM, PT.SLA, PT.DLP, PT.SLS, PT.MJF}
SUBTRACTIVE = {PT.CNC_3AXIS, PT.CNC_5AXIS, PT.CNC_TURNING}
FORMATIVE = {PT.INJECTION_MOLDING, PT.DIE_CASTING}
# FABRICATION: 2.5D blank-and-bend (laser/punch + press brake). No hard tooling
# at low/mid volume, so this is a MAKE-NOW family like additive / CNC.
FABRICATION = {PT.SHEET_METAL}
# CASTING: pour-and-solidify (sand mould / investment shell). Hard tooling is a
# PATTERN (sand) or a wax die + ceramic shell (investment), cheaper than an
# injection/die-cast tool. Aramco makes many cast parts (pump housings, valve
# bodies), so these must leave feasibility-only with a defensible dollar.
CASTING = {PT.INVESTMENT_CASTING, PT.SAND_CASTING}
# FORGING: heat + press/hammer a billet in a closed die. Tooling is a hardened
# forging DIE set — the most expensive of the tooled families here. Common for
# high-strength Aramco parts (flanges, valve bodies, drilling components).
FORGING_FAMILY = {PT.FORGING}
# EDM: wire-EDM is a SLOW, precise, tool-less removal route (spark-erode a
# conductive blank along a cut path). No hard tooling; cost is dominated by the
# very slow cut. Common on Aramco hard/precise features. Kept in its own family
# so its wide band + cut-path model never touch the CNC removal path.
EDM = {PT.WIRE_EDM}
# ── METAL ADDITIVE (dollar-costed 2026-07-04) ────────────────────────────────
# These six were feasibility-only AND — the latent bug this fixes — fell through
# process_family()'s "formative" fallback because they were in NO family set.
# They are metal AM, not molding. Three physically-distinct routes, each its own
# family so its cost model + wide band never touch a polymer-AM/casting path:
#   metal_powder_bed {DMLS,SLM,EBM} — laser/e-beam powder-bed fusion. REUSES the
#     build-job additive time model (full-build Z-sweep ÷ parts_per_build) with
#     metal params + a metal-only post helper (plate cut-off, support removal,
#     stress-relief furnace) that polymer AM never pays.
#   binder_jet {BINDER_JET} — print a green part (fast/cheap) then debind + SINTER
#     (furnace batch; ~18% linear shrink → the green is printed oversize).
#   ded {DED,WAAM} — directed-energy / wire-arc: deposition-RATE driven near-net,
#     then a coarse finish-machining allowance. HIGH, geometry/shop-specific band.
METAL_POWDER_BED = {PT.DMLS, PT.SLM, PT.EBM}
BINDER_JET_FAMILY = {PT.BINDER_JET}
DED_FAMILY = {PT.DED, PT.WAAM}

# The bounded set V0 will produce a dollar should-cost for. Everything else is
# feasibility-only (honest: no number we cannot defend).
COSTED_PROCESSES = {
    PT.FDM, PT.SLA, PT.DLP, PT.SLS, PT.MJF,
    PT.CNC_3AXIS, PT.CNC_5AXIS, PT.CNC_TURNING,
    PT.INJECTION_MOLDING, PT.DIE_CASTING,
    PT.SHEET_METAL,
    # newly costed (off feasibility-only): forged, cast, wire-EDM
    PT.FORGING, PT.INVESTMENT_CASTING, PT.SAND_CASTING, PT.WIRE_EDM,
    # metal additive (off feasibility-only): powder-bed, binder-jet, DED/WAAM
    PT.DMLS, PT.SLM, PT.EBM, PT.BINDER_JET, PT.DED, PT.WAAM,
}

# Absolute-cost error band by family (the dominant-line band, spec §6.5). The new
# families are WIDE and honest — un-validated, pre-calibration physics models.
BAND_PCT = {"additive": 40.0, "subtractive": 50.0, "formative": 60.0,
            "fabrication": 35.0,
            "casting": 55.0,     # pour-yield + tooling tier are un-validated assumptions
            "forging": 55.0,     # billet loss + die-tier are un-validated assumptions
            "edm": 45.0,         # cut-path proxy (perimeter × thickness) is un-validated
            # metal AM (un-validated, pre-calibration physics — wider than polymer AM)
            "metal_powder_bed": 50.0,  # build-job time + metal post are assumptions
            "binder_jet": 55.0,        # sinter shrink + furnace batch are assumptions
            "ded": 60.0}               # deposition-rate model is coarse + shop-specific

# ── Declared tolerance classes (Aramco readiness gap #4, cost side) ─────────
# Ordered loosest → tightest. The caller DECLARES how tight the part is; there
# is no real GD&T/PMI extraction here (that needs OCP), so this is an honest
# STATED input, not a measured one. "standard" is the neutral no-op class.
TOLERANCE_CLASSES = ("standard", "precision", "tight")


def normalize_tolerance_class(value) -> str:
    """Coerce any caller input to a known tolerance class; unknown → 'standard'.

    Honest fallback: never crash on a bad string, and an unrecognised value is
    treated as the neutral 'standard' (byte-identical to omitting it).
    """
    if not isinstance(value, str):
        return "standard"
    v = value.strip().lower()
    return v if v in TOLERANCE_CLASSES else "standard"


# ──────────────────────────────────────────────────────────────────────────
# The default rate card (all DEFAULT)
# ──────────────────────────────────────────────────────────────────────────
RATE_CARD_V0: dict = {
    "global": {
        "labor_rate": 35.00,          # $/hr loaded shop-floor labor
        "margin": 0.00,               # should-cost, not price
        "overhead": 0.00,             # indirect-cost markup on conversion (machine+labor+setup); 0 = no-op
        "utilization": 1.00,          # machine utilization 0<u<=1; effective machine cost ÷ u; 1 = no-op
        "stock_allowance": 1.10,      # CNC billet oversize on hull volume
        "daily_machine_hours": 8.0,   # hr/day for lead-time production days
        "cooling_coef": 2.0,          # s/mm^2 — molding cooling ∝ wall^2
        "shot_overhead_s": 5.0,       # s — molding non-cooling cycle overhead
        "ship_days": 3.0,             # outbound logistics
        # ── volume/learning economics (S1 fix) ──────────────────────────
        # Wright cumulative-average learning curve on the ATTENDED CONVERSION
        # cost (machine cycle + post-process labor) of make-now, labor-bearing
        # families (subtractive/CNC + fabrication/sheet-metal). Per-unit
        # conversion time drops as (cumulative_qty / first_lot)^b, b=log2(rate),
        # capturing optimized tool-paths, dedicated fixturing, dialed-in
        # feeds/speeds, and reduced attention at volume. Material never learns;
        # per-lot setup already amortizes separately. This is a MODEL, tagged
        # DEFAULT/assumption — NOT validated against real shop quotes.
        "learning_rate": 0.90,        # 0<rate<=1 fraction per doubling of cumulative qty; 1.0 = no learning (old flat behavior)
        "learning_floor": 0.25,       # min fraction of first-lot standard time the curve can reach (practical cycle-time floor)
        # ── region machine-rate capital/labor split (E-now #2) ───────────
        # BUG FIX (cost audit M8): the region_labor multiplier (e.g. CN 0.55)
        # was applied to the WHOLE machine $/hr, discounting the machine's
        # capital depreciation / facility / energy as if it were local labor.
        # A CNC or printer costs ~the same globally; only the OPERATOR share of
        # the loaded rate follows regional labor. machine_labor_frac splits the
        # rate: (1-frac) is globally-priced capital+facility+energy (region ×1),
        # frac is operator labor (region ×region_labor). 1.0 = the old, buggy
        # whole-rate discount (the off-switch). This is a MODEL structure tagged
        # DEFAULT/assumption — the fraction is NOT validated against real shop
        # cost accounting; Zoox will calibrate it (likely per-process).
        "machine_labor_frac": 0.35,   # operator-labor share of the loaded machine rate; 1.0 recovers old behavior
        # ── perishable tooling / consumables (E-now #4) ──────────────────
        # Cutting tools, inserts, coolant, abrasives wear out and are consumed in
        # proportion to spindle/machine time. Modeled as a % of the machine line
        # for subtractive (CNC) work — standard shop cost-accounting. DEFAULT
        # assumption, NOT shop-validated; 0.0 = off (byte-identical old cost).
        "perishable_frac": 0.05,      # perishable tooling+consumables as a fraction of CNC machine cost
        # ── owned-equipment / in-house marginal costing (make-it-ourselves) ──
        # The target customer MAKES PARTS IN THEIR OWN FACILITY on machines they
        # ALREADY OWN. When the org owns the machine, its capital purchase /
        # amortization is a SUNK cost — the true MARGINAL cost of making one more
        # part in-house is material + energy + operator + consumables, NOT the
        # fully-loaded bureau $/hr (which recovers the capital as if renting time
        # from an outside shop). machine_capital_frac is the share of the loaded
        # machine rate that is capital purchase/depreciation (DISTINCT from the
        # facility/energy/operator that stay marginal even on owned gear). When a
        # process is declared OWNED (EstimateOptions.owned_processes, USER), the
        # machine line is costed at machine_rate × (1 - machine_capital_frac).
        # This is a MODEL structure tagged DEFAULT/assumption — the fraction is
        # NOT validated against a real org's cost accounting; a customer's real
        # numbers (governed rate library + W5 flywheel) calibrate it, likely
        # per-process. machine_capital_frac=0.0 is the OFF-SWITCH: owned ==
        # fully-loaded, byte-identical to renting the time.
        "machine_capital_frac": 0.35, # capital/amortization share of the loaded machine rate; SUNK when the org owns the machine; 0.0 = off (owned == fully-loaded)
    },
    # Per-process rates. Keys map 1:1 to the spec §6.3 + V1 §1 tables.
    #
    # New V1 keys (all DEFAULT, all overridable):
    #   ADDITIVE-only: build_env_mm (X,Y,Z), packing_density, part_spacing_mm,
    #                  nesting_mode ("serial" | "build_job")
    #   ALL: post_hr_part (per-part finishing), post_hr_build (per-build bulk,
    #        amortized over parts/build), lot_size (units/setup; "build" sentinel
    #        for AM = parts_per_build), min_charge ($/lot order floor)
    #
    # `vert` recalibrated for build_job processes so the full-build duration is
    # realistic: SLS 600/20=30hr, MJF 380/25=15.2hr, DLP 245/30=8.2hr.
    "process": {
        PT.FDM: dict(
            machine_rate=8, setup_hr=0.25, post_hr=0.25, scrap=0.10,
            deposition=16, vert=25, finish=None, queue_days=2, post_days=1,
            build_env_mm=(250, 250, 250), packing_density=0.10, part_spacing_mm=4.0,
            nesting_mode="serial", post_hr_part=0.20, post_hr_build=0.10,
            lot_size="build", min_charge=30,
            xy_packing_density=0.50, n_machines=12, machine_hours_per_day=22),
        PT.SLA: dict(
            machine_rate=12, setup_hr=0.30, post_hr=0.50, scrap=0.10,
            deposition=8, vert=20, finish=None, queue_days=2, post_days=1,
            build_env_mm=(145, 145, 185), packing_density=0.10, part_spacing_mm=3.0,
            nesting_mode="serial", post_hr_part=0.15, post_hr_build=0.20,
            lot_size="build", min_charge=40,
            xy_packing_density=0.50, n_machines=8, machine_hours_per_day=22),
        PT.DLP: dict(
            machine_rate=12, setup_hr=0.30, post_hr=0.50, scrap=0.10,
            deposition=12, vert=30, finish=None, queue_days=2, post_days=1,
            build_env_mm=(192, 120, 245), packing_density=0.12, part_spacing_mm=3.0,
            nesting_mode="build_job", post_hr_part=0.15, post_hr_build=0.20,
            lot_size="build", min_charge=40,
            n_machines=8, machine_hours_per_day=22),
        PT.SLS: dict(
            machine_rate=20, setup_hr=0.50, post_hr=0.50, scrap=0.10,
            deposition=18, vert=20, finish=None, queue_days=3, post_days=1,
            build_env_mm=(340, 340, 600), packing_density=0.10, part_spacing_mm=5.0,
            nesting_mode="build_job", post_hr_part=0.08, post_hr_build=0.50,
            lot_size="build", min_charge=75,
            n_machines=6, machine_hours_per_day=22),
        PT.MJF: dict(
            machine_rate=22, setup_hr=0.50, post_hr=0.50, scrap=0.10,
            deposition=20, vert=25, finish=None, queue_days=3, post_days=1,
            build_env_mm=(380, 284, 380), packing_density=0.10, part_spacing_mm=5.0,
            nesting_mode="build_job", post_hr_part=0.08, post_hr_build=0.50,
            lot_size="build", min_charge=75,
            n_machines=6, machine_hours_per_day=22),
        # CNC keys nre_hr / fai_hr / inspect_hr_part / finish_* are E-now #3+#4:
        # CAM-programming NRE (amortized over the whole order), first-article +
        # in-process inspection, and OUTSOURCED secondary finishing (anodize /
        # plate / heat-treat) as a lot + per-part charge (default 0 = as-machined,
        # no finish assumed). All DEFAULT, all overridable, all Zoox-caveated.
        PT.CNC_3AXIS: dict(
            machine_rate=75, setup_hr=0.75, post_hr=0.50, scrap=0.05,
            deposition=None, vert=None, finish=600, queue_days=5, post_days=1,
            post_hr_part=0.50, post_hr_build=0.0, lot_size=100, min_charge=90,
            n_machines=8, machine_hours_per_day=16,
            nre_hr=2.0, fai_hr=0.50, inspect_hr_part=0.030,
            finish_lot_charge=0.0, finish_per_part=0.0),
        PT.CNC_5AXIS: dict(
            machine_rate=110, setup_hr=1.00, post_hr=0.50, scrap=0.05,
            deposition=None, vert=None, finish=500, queue_days=7, post_days=1,
            post_hr_part=0.50, post_hr_build=0.0, lot_size=100, min_charge=110,
            n_machines=4, machine_hours_per_day=16,
            nre_hr=3.0, fai_hr=0.75, inspect_hr_part=0.050,
            finish_lot_charge=0.0, finish_per_part=0.0),
        PT.CNC_TURNING: dict(
            machine_rate=65, setup_hr=0.50, post_hr=0.30, scrap=0.05,
            deposition=None, vert=None, finish=800, queue_days=5, post_days=1,
            post_hr_part=0.30, post_hr_build=0.0, lot_size=100, min_charge=90,
            n_machines=6, machine_hours_per_day=16,
            nre_hr=1.0, fai_hr=0.40, inspect_hr_part=0.025,
            finish_lot_charge=0.0, finish_per_part=0.0),
        PT.INJECTION_MOLDING: dict(
            machine_rate=45, setup_hr=0.00, post_hr=0.05, scrap=0.03,
            deposition=None, vert=None, finish=None, queue_days=2, post_days=1,
            post_hr_part=0.05, post_hr_build=0.0, lot_size=100000, min_charge=0,
            n_machines=2, machine_hours_per_day=22),
        PT.DIE_CASTING: dict(
            machine_rate=90, setup_hr=0.00, post_hr=0.10, scrap=0.03,
            deposition=None, vert=None, finish=None, queue_days=3, post_days=2,
            post_hr_part=0.10, post_hr_build=0.0, lot_size=100000, min_charge=0,
            n_machines=2, machine_hours_per_day=22),
        # FABRICATION — laser/punch blank + press-brake bend. Cycle time is a
        # physics model (cut length / cut speed + bends + handling), NOT a magic
        # $/cm³. Material is the rectangular blank (footprint × gauge × scrap).
        # No per-unit hard tooling at this volume (stamping dies are a separate,
        # future high-volume route), so fixed cost is setup only -> make-now.
        PT.SHEET_METAL: dict(
            machine_rate=45,            # $/hr loaded laser/punch + brake cell
            setup_hr=0.40,              # CAM nest + program + first-article, per lot
            post_hr=0.10, scrap=0.05,
            deposition=None, vert=None, finish=None, queue_days=4, post_days=1,
            post_hr_part=0.10,          # deburr / edge-break / inspect, per part
            post_hr_build=0.0, lot_size=200, min_charge=75,
            n_machines=4, machine_hours_per_day=16,
            # cut/bend/handling physics constants (all DEFAULT, all overridable)
            cut_speed_mm_min=4000.0,    # laser feed at the reference gauge
            ref_gauge_mm=2.0,           # gauge at which cut_speed holds; thicker = slower
            sec_per_bend=20.0,          # press-brake hit: locate + bend + remove
            handling_hr=0.020),         # load/unload/locate per part
        # ── CASTING (pour + solidify) — foundry cell. Material = poured metal =
        # net part mass × (1 + yield_loss) for gating/risers. Machine cycle =
        # pour + solidification cool (∝ poured mass). Knockout/fettle/clean is
        # LABOR (post_hr_part). Tooling is a pattern (sand) / wax die + shell
        # (investment), sized by the shared size-tier table × a casting multiplier
        # (see tooling_casting_mult). EVERY constant below is a DEFAULT assumption,
        # NOT foundry-validated. ──────────────────────────────────────────────
        PT.SAND_CASTING: dict(
            machine_rate=40.0,          # $/hr loaded sand-foundry pour cell (DEFAULT, un-validated)
            setup_hr=1.00,              # mould box / gating setup per lot (DEFAULT)
            post_hr=0.0, scrap=0.06,    # casting-defect scrap fraction (DEFAULT)
            deposition=None, vert=None, finish=None, queue_days=6, post_days=3,
            post_hr_part=0.60,          # shakeout + knockout + fettle/grind/clean, per part (DEFAULT)
            post_hr_build=0.0, lot_size=200, min_charge=120,
            n_machines=3, machine_hours_per_day=16,
            yield_loss=0.50,            # gating+risers: poured = net × 1.50 (sand runs heavy) (DEFAULT)
            pour_hr=0.08,               # ladle pour + handling per part (DEFAULT)
            cool_min_per_kg=1.20),      # solidification/cool minutes per kg poured (DEFAULT)
        PT.INVESTMENT_CASTING: dict(
            machine_rate=55.0,          # $/hr loaded investment (lost-wax) shell+pour cell (DEFAULT)
            setup_hr=1.50,              # tree assembly / shell prep per lot (DEFAULT)
            post_hr=0.0, scrap=0.05,    # casting-defect scrap fraction (DEFAULT)
            deposition=None, vert=None, finish=None, queue_days=10, post_days=4,
            post_hr_part=0.35,          # near-net precision route: less fettling than sand (DEFAULT)
            post_hr_build=0.0, lot_size=200, min_charge=180,
            n_machines=2, machine_hours_per_day=16,
            yield_loss=0.40,            # gating tree metal: poured = net × 1.40 (DEFAULT)
            pour_hr=0.12,               # shell fill + handling per part (DEFAULT)
            cool_min_per_kg=1.50),      # ceramic shell holds heat: slower cool per kg (DEFAULT)
        # ── FORGING (heat + press/hammer a billet in a closed die) — material =
        # billet mass = net × (1 + flash/scale loss), bought as bar stock. Machine
        # cycle = furnace heat (∝ billet mass) + press/hammer strokes + trim. High
        # per-lot setup; hardened DIE set (most expensive tooled family here). NOTE:
        # a forging is a NEAR-NET blank — it USUALLY needs downstream finish
        # machining that this model does NOT bundle (caveat, not a hidden CNC pass).
        # All constants DEFAULT, un-validated. ────────────────────────────────
        PT.FORGING: dict(
            machine_rate=120.0,         # $/hr loaded forging press/hammer + furnace cell (DEFAULT)
            setup_hr=3.00,              # die install + heat-up + trial strokes per lot (DEFAULT)
            post_hr=0.0, scrap=0.05,    # lap/underfill scrap fraction (DEFAULT)
            deposition=None, vert=None, finish=None, queue_days=12, post_days=3,
            post_hr_part=0.20,          # de-scale / trim-flash cleanup, per part (DEFAULT)
            post_hr_build=0.0, lot_size=250, min_charge=200,
            n_machines=2, machine_hours_per_day=16,
            flash_loss=0.25,            # flash + scale: billet = net × 1.25 (DEFAULT)
            heat_min_per_kg=2.50,       # furnace heat-to-forging-temp minutes per kg billet (DEFAULT)
            press_hr=0.05,              # press/hammer strokes + manipulation per part (DEFAULT)
            trim_hr=0.03),              # flash-trim press hit per part (DEFAULT)
        # ── WIRE-EDM (spark-erode a conductive blank along a cut path) — tool-less
        # and SLOW. Material = the billet plate you buy (bbox billet, like milling).
        # Machine cycle = swept cut AREA (cut-path length × stock thickness) ÷ a very
        # slow EDM cut rate (mm²/hr, material-dependent) + wire-threading per contour.
        # Wire is a CONSUMABLE (∝ cut time). No hard tooling. cut_rate is by material
        # class (see edm_cut_rate). CAVEAT: with no true cut-perimeter driver we use
        # outline_perimeter_mm (the measured 2D outline proxy) × the min bbox extent
        # (stock thickness) as the swept area — an APPROXIMATION, flagged in-source.
        # All constants DEFAULT, un-validated. ────────────────────────────────
        PT.WIRE_EDM: dict(
            machine_rate=42.0,          # $/hr loaded wire-EDM machine (runs mostly unattended) (DEFAULT)
            setup_hr=0.75,              # fixture + edge-find + program per lot (DEFAULT)
            post_hr=0.0, scrap=0.04,    # blank offcut/handling scrap fraction (DEFAULT)
            deposition=None, vert=None, finish=None, queue_days=6, post_days=1,
            post_hr_part=0.10,          # break wire-entry tab / light deburr, per part (DEFAULT)
            post_hr_build=0.0, lot_size=50, min_charge=110,
            n_machines=3, machine_hours_per_day=20,
            n_threads=1,                # wire threads (contours) per part (DEFAULT proxy)
            thread_min=6.0,             # auto-wire-thread + re-reference minutes per contour (DEFAULT)
            wire_cost_per_hr=7.0),      # brass wire + dielectric/filter consumable $/cut-hr (DEFAULT)
        # ── METAL POWDER-BED FUSION (DMLS/SLM/EBM) — laser/e-beam melt of metal
        # powder, layer by layer. REUSES the build-job additive time model: the beam
        # sweeps every layer of the whole build, so per-part machine time = full-build
        # Z-height ÷ vert (SLOW metal build rate) ÷ parts_per_build. Machines are
        # expensive ($150-180/hr loaded). Metal-only POST that polymer AM never pays:
        # build-plate cut-off + support removal (per part) + stress-relief furnace
        # (per-build batch, amortized). Powder is recycled so scrap is the ~15%
        # effective loss, NOT 100% of unfused powder. Support structure adds ~20%
        # extra printed (then removed) volume, folded into material mass. NOTE: powder
        # $/kg is taken at the material-DB value (metal_am_powder_mult=1.0 — powder
        # vs wrought pricing is a KNOWN refinement, NOT silently inflated). HIP /
        # solution heat-treat / CNC finish of critical surfaces are part-specific and
        # deliberately NOT bundled. Every constant DEFAULT, un-validated. ───────────
        PT.DMLS: dict(
            machine_rate=180.0,         # $/hr loaded laser powder-bed metal machine (DEFAULT)
            setup_hr=0.50, post_hr=0.0, scrap=0.15,   # 15% effective powder loss (recycled) (DEFAULT)
            deposition=None, vert=6.0,  # SLOW metal Z build rate mm/hr (DEFAULT)
            finish=None, queue_days=7, post_days=3,
            build_env_mm=(250, 250, 325), packing_density=0.08, part_spacing_mm=6.0,
            nesting_mode="build_job", post_hr_part=0.0, post_hr_build=0.0,
            lot_size="build", min_charge=250,
            n_machines=2, machine_hours_per_day=20,
            # metal-AM post-processing (all DEFAULT, all overridable)
            plate_removal_hr=0.30,      # wire-EDM/bandsaw off the build plate, per part (DEFAULT)
            support_removal_hr=0.60,    # metal support removal, per part (DEFAULT)
            stress_relief_hr_build=2.0, # stress-relief furnace per build, amortized over n (DEFAULT)
            support_vol_frac=0.20,      # extra printed support volume (removed) as fraction of net (DEFAULT)
            metal_am_powder_mult=1.0),  # powder-price multiplier on material-DB $/kg (1.0 = no inflation) (DEFAULT)
        PT.SLM: dict(
            machine_rate=180.0, setup_hr=0.50, post_hr=0.0, scrap=0.15,
            deposition=None, vert=6.0, finish=None, queue_days=7, post_days=3,
            build_env_mm=(250, 250, 325), packing_density=0.08, part_spacing_mm=6.0,
            nesting_mode="build_job", post_hr_part=0.0, post_hr_build=0.0,
            lot_size="build", min_charge=250,
            n_machines=2, machine_hours_per_day=20,
            plate_removal_hr=0.30, support_removal_hr=0.60, stress_relief_hr_build=2.0,
            support_vol_frac=0.20, metal_am_powder_mult=1.0),
        PT.EBM: dict(
            machine_rate=150.0,         # electron-beam machine (DEFAULT)
            setup_hr=0.50, post_hr=0.0, scrap=0.15,
            deposition=None, vert=9.0,  # faster Z build than laser (DEFAULT)
            finish=None, queue_days=7, post_days=3,
            build_env_mm=(350, 380, 380), packing_density=0.08, part_spacing_mm=6.0,
            nesting_mode="build_job", post_hr_part=0.0, post_hr_build=0.0,
            lot_size="build", min_charge=250,
            n_machines=2, machine_hours_per_day=20,
            plate_removal_hr=0.30, support_removal_hr=0.60, stress_relief_hr_build=2.0,
            support_vol_frac=0.20, metal_am_powder_mult=1.0),
        # ── BINDER JETTING — inkjet a binder into metal powder → GREEN part (fast,
        # cheap print machine), then debind + SINTER in a furnace batch. The green is
        # printed OVERSIZE because sintering shrinks it ~18% linearly → material mass
        # = net × (1+shrinkage_linear)³ of powder. Sinter is a long furnace batch cycle
        # amortized over the parts sintered together. Every constant DEFAULT,
        # un-validated. ────────────────────────────────────────────────────────────
        PT.BINDER_JET: dict(
            machine_rate=40.0,          # $/hr loaded binder-jet PRINT machine (fast, cheap) (DEFAULT)
            setup_hr=0.50, post_hr=0.0, scrap=0.10,
            deposition=None, vert=25.0, # fast green print Z rate mm/hr (DEFAULT)
            finish=None, queue_days=7, post_days=4,
            build_env_mm=(400, 250, 250), packing_density=0.12, part_spacing_mm=6.0,
            nesting_mode="build_job", post_hr_part=0.0, post_hr_build=0.0,
            lot_size="build", min_charge=150,
            n_machines=2, machine_hours_per_day=20,
            # debind + sinter (all DEFAULT, all overridable)
            sinter_hr_build=24.0,       # furnace debind+sinter batch cycle hr (DEFAULT)
            sinter_rate=15.0,           # $/hr loaded sinter furnace (DEFAULT)
            shrinkage_linear=0.18,      # linear sinter shrink → green oversize (1+s)^3 volume (DEFAULT)
            parts_per_sinter_batch=0.0),# furnace batch count; 0 => amortize over parts_per_build (DEFAULT)
        # ── DED / WAAM (directed-energy / wire-arc) — deposition-RATE driven near-net
        # deposition of feedstock (wire/powder), then finish machining (ALWAYS needed).
        # Machine cost = deposited mass ÷ deposition_rate × machine_rate. Feedstock =
        # net × feedstock_mult (near-net overbuild) at the material price. A coarse
        # finish-machining allowance is added as a fraction of deposition cost. This
        # is HIGHLY geometry/shop-specific — the WIDEST band. Every constant DEFAULT,
        # un-validated. ────────────────────────────────────────────────────────────
        PT.DED: dict(
            machine_rate=120.0,         # $/hr loaded DED cell (DEFAULT)
            setup_hr=1.00, post_hr=0.0, scrap=0.10,
            deposition=None, vert=None, finish=None, queue_days=10, post_days=4,
            post_hr_part=0.0, post_hr_build=0.0, lot_size=10, min_charge=300,
            n_machines=2, machine_hours_per_day=20,
            deposition_rate_kg_hr=1.0,  # feedstock deposited per hour (DEFAULT)
            feedstock_mult=1.15,        # near-net overbuild: deposited = net × 1.15 (DEFAULT)
            finish_machining_frac=0.30),# finish-machining allowance as fraction of deposition cost (DEFAULT)
        PT.WAAM: dict(
            machine_rate=90.0,          # $/hr loaded wire-arc cell (DEFAULT)
            setup_hr=1.00, post_hr=0.0, scrap=0.10,
            deposition=None, vert=None, finish=None, queue_days=10, post_days=4,
            post_hr_part=0.0, post_hr_build=0.0, lot_size=10, min_charge=300,
            n_machines=2, machine_hours_per_day=20,
            deposition_rate_kg_hr=3.0,  # wire-arc deposits FAST (DEFAULT)
            feedstock_mult=1.15,
            finish_machining_frac=0.30),
    },
    # Shop-specific material lot prices ($/kg). Empty by default → fall back to
    # the material-DB cost_per_kg (a generic DEFAULT). A calibrated shop binds its
    # real negotiated lot prices here, keyed by exact material name (e.g.
    # "PA12 (Nylon 12)") or by a class sentinel ("@polymer", "@aluminum", ...).
    "material_prices": {},
    # CNC material-removal rate (cm^3/min) by material class.
    # Material-removal rate (cm³/min) by class. Nickel superalloys (Inconel,
    # Incoloy, Hastelloy) work-harden and machine SLOWER than titanium, so they
    # get their own low rate — without it the fallback (8) would cost a nickel
    # CNC part like steel and materially under-cost the machine line.
    "mrr": {"polymer": 50, "aluminum": 30, "steel": 8, "stainless": 5,
            "titanium": 2, "nickel": 1.5},
    # Wire-EDM cut rate (mm^2 of swept cross-section per HOUR) by material class —
    # the whole point of wire-EDM is that it is SLOW and precise (orders of
    # magnitude below milling). Conductive metals only; the "polymer" entry is a
    # nominal fallback (EDM needs a conductive workpiece). All DEFAULT, un-validated.
    "edm_cut_rate": {"aluminum": 12000, "steel": 8000, "stainless": 6000,
                     "titanium": 4000, "nickel": 3500, "polymer": 6000},
    # Single-cavity tooling by part size tier (max bbox dim, mm). Die-casting = ×1.5.
    "tooling": {"S": 6000, "M": 15000, "L": 30000, "XL": 60000},
    "tooling_die_mult": 1.5,
    # Hard-tooling multipliers on the size-tier base for the new tooled families
    # (all DEFAULT, un-validated). Ordering is the physically-honest one:
    #   sand pattern (cheap wood/resin) < investment wax die + shell < injection/
    #   die-cast tool (base/×1.5) < hardened forging DIE set (most expensive).
    "tooling_casting_mult": {
        PT.SAND_CASTING: 0.35,          # pattern + core boxes — cheapest hard tooling (DEFAULT)
        PT.INVESTMENT_CASTING: 0.90,    # wax-injection die + ceramic shell — > sand, < injection (DEFAULT)
    },
    "tooling_forging_mult": 2.00,       # hardened closed-die set — most expensive tooled family (DEFAULT)
    # Tooling cavity + complexity scaling (weakness #5). DEFAULT 1 cav, moderate.
    "cavity_exponent": 0.70,   # tool cost ~ n_cavities^0.70 (shared bolster/base)
    "complexity_factor": {"simple": 0.80, "moderate": 1.00, "complex": 1.50, "very_complex": 2.20},
    # ── Declared tolerance class (Aramco cost gap #4) ────────────────────────
    # The caller DECLARES how tight the part is → we apply a machining COST
    # multiplier (≥1.0) to the tolerance-SENSITIVE conversion terms (CNC finish
    # pass + inspection) and WIDEN the confidence band by band_add_pct absolute
    # points (tighter = more uncertain — the band only ever widens). "standard"
    # MUST be (1.0, 0.0): an omitted/standard declaration is BYTE-IDENTICAL to
    # pre-change output. The DECLARATION is USER; these factor magnitudes are
    # DEFAULT assumptions, NOT shop-validated, and overridable via a governed
    # base rate table. There is NO real GD&T extraction here (that needs OCP).
    "tolerance_class": {
        "standard":  {"cost_mult": 1.00, "band_add_pct": 0.0},
        "precision": {"cost_mult": 1.20, "band_add_pct": 8.0},
        "tight":     {"cost_mult": 1.50, "band_add_pct": 18.0},
    },
    # Tooling lead time (days), applied once regardless of qty.
    "tooling_lead_days": {PT.INJECTION_MOLDING: 25, PT.DIE_CASTING: 35,
                          # new tooled families (DEFAULT, un-validated lead assumptions)
                          PT.SAND_CASTING: 15, PT.INVESTMENT_CASTING: 30,
                          PT.FORGING: 45},
    # Region split (weakness #4): three independent vectors. Commodity material &
    # global-steel tooling do NOT track regional shop labor.
    "region_labor":    {"US": 1.00, "EU": 1.10, "MX": 0.70, "CN": 0.55, "IN": 0.50, "SA": 1.05},
    "region_material": {"US": 1.00, "EU": 1.02, "MX": 1.00, "CN": 0.98, "IN": 0.98, "SA": 1.02},
    "region_tooling":  {"US": 1.00, "EU": 1.05, "MX": 0.75, "CN": 0.45, "IN": 0.50, "SA": 1.10},
}


# ──────────────────────────────────────────────────────────────────────────
# Material family map (spec §5.2) — kills the Inconel-for-plastic bug by
# construction: a polymer part never matches a titanium/superalloy material.
# Mechanical mapping by alloy / polymer name over profiles.database.MATERIALS.
# ──────────────────────────────────────────────────────────────────────────
MATERIAL_FAMILY: dict = {
    # polymers (FDM / resin / SLS-MJF / machinable / molded)
    "PLA": "polymer", "PETG": "polymer", "ABS": "polymer", "Nylon (PA6)": "polymer",
    "ULTEM 9085": "polymer", "CF-Nylon": "polymer", "TPU 95A": "polymer",
    "Standard Resin": "polymer", "Tough Resin": "polymer", "Flexible Resin": "polymer",
    "Castable Resin": "polymer", "Dental Model Resin": "polymer",
    "PA12 (Nylon 12)": "polymer", "PA11": "polymer", "Glass-filled PA12": "polymer",
    "TPU (SLS)": "polymer", "PP (MJF)": "polymer",
    "Delrin (POM)": "polymer", "PEEK": "polymer",
    "ABS (Molded)": "polymer", "PC (Polycarbonate)": "polymer", "PP (Molded)": "polymer",
    "PA66-GF30": "polymer", "PP (Polypropylene)": "polymer",
    # aluminum
    "AlSi10Mg": "aluminum", "6061-T6 Aluminum": "aluminum", "7075-T6 Aluminum": "aluminum",
    "A356 Aluminum": "aluminum", "5052 Aluminum (Sheet)": "aluminum",
    # stainless
    "SS316L": "stainless", "304 Stainless": "stainless", "304 SS (Sheet)": "stainless",
    "17-4 PH SS": "stainless", "17-4 PH (Cast)": "stainless", "Duplex 2205": "stainless",
    # carbon / ferrous steel
    "Mild Steel": "steel", "Ductile Iron": "steel",
    # titanium
    "Ti6Al4V": "titanium", "Ti6Al4V (Wrought)": "titanium", "Ti-6Al-4V Grade 5": "titanium",
    # nickel superalloy (deliberately its own family — never a default for a
    # polymer/aluminum/steel part; this is the structural fix for the teardown bug)
    "Inconel 718": "nickel", "Inconel 625": "nickel",
    # cobalt-chrome, zinc, copper (other families — excluded from V0 default classes)
    "CoCr": "cobalt", "CoCr ASTM F75": "cobalt",
    "Zinc Alloy (Zamak 3)": "zinc",
    "Copper C110 (Sheet)": "copper",
    # ── Oil & gas / API-spec alloy pack (2026-07-04) ─────────────────────────
    # Low-alloy & carbon forging steels (Aramco flanges, fittings, stems, bodies)
    "AISI 4130": "steel", "AISI 4140": "steel",
    "ASTM A105": "steel", "ASTM A182 F22": "steel",
    # Martensitic / duplex CRAs (OCTG/tubing, valve bodies, seawater/topside)
    "API 13Cr": "stainless", "Super 13Cr": "stainless",
    "Super Duplex 2507": "stainless", "F6NM": "stainless",
    # Nickel CRAs (sour/acid service, cladding, downhole)
    "Incoloy 825": "nickel", "Hastelloy C276": "nickel",
}


def family_to_size_tier(max_bbox_mm: float) -> str:
    if max_bbox_mm < 50:
        return "S"
    if max_bbox_mm < 150:
        return "M"
    if max_bbox_mm <= 300:
        return "L"
    return "XL"


def process_family(process: ProcessType) -> str:
    if process in ADDITIVE:
        return "additive"
    if process in SUBTRACTIVE:
        return "subtractive"
    if process in FABRICATION:
        return "fabrication"
    if process in CASTING:
        return "casting"
    if process in FORGING_FAMILY:
        return "forging"
    if process in EDM:
        return "edm"
    # metal additive — MUST precede the "formative" fallback (that fallback was
    # the latent bug: these six matched no family set and mis-returned formative).
    if process in METAL_POWDER_BED:
        return "metal_powder_bed"
    if process in BINDER_JET_FAMILY:
        return "binder_jet"
    if process in DED_FAMILY:
        return "ded"
    return "formative"


@dataclass
class RateCard:
    """Merged rate card + record of which dotted keys were sourced where.

    Provenance of any dotted key resolves in precedence order:
        USER  — overridden ad-hoc for THIS quote (rate_overrides) — wins.
        SHOP  — bound from the ACTIVE calibrated shop profile (shop_keys).
        DEFAULT — the generic rate card (neither overridden nor shop-bound).

    Dotted-key override forms (EstimateOptions.rate_overrides + shop profiles):
        "labor_rate" / "margin" / "overhead" / "utilization" / "region" /
        "stock_allowance"                                       -> global
        "machine_rate.SLS" / "setup_hr.CNC_3AXIS" / ...          -> per-process
        "tooling.INJECTION_MOLDING"                              -> flat tooling override
        "material_price.PA12 (Nylon 12)" / "material_price.@polymer" -> material lot price
    """

    data: dict
    user_keys: set = field(default_factory=set)
    shop_keys: set = field(default_factory=set)
    shop_name: "str | None" = None
    shop_region: "str | None" = None   # region declared by the active shop profile

    # ---- global getters --------------------------------------------------
    def g(self, key: str) -> float:
        return self.data["global"][key]

    def is_user(self, dotted: str) -> bool:
        return dotted in self.user_keys

    def prov_tag(self, dotted: str):
        from src.costing.provenance import Provenance
        if dotted in self.user_keys:
            return Provenance.USER
        if dotted in self.shop_keys:
            return Provenance.SHOP
        return Provenance.DEFAULT

    # ---- shop-bound material lot price (else generic material-DB default) -
    def material_price(self, material_name: str, material_class: str,
                       default_price: float):
        """Resolve the $/kg to use for this material.

        Returns (price, provenance, note). When the active shop profile carries a
        real lot price for this exact material (or its class via "@<class>"), that
        price is used and tagged USER/SHOP. Otherwise we fall back to the generic
        material-DB $/kg, which is a stated DEFAULT assumption (a book price, NOT
        extracted from the part) — so it is tagged DEFAULT, not MEASURED. (The
        part MASS it multiplies is MEASURED and carries its own tag on the
        geometry drivers; the PRICE, the assumable part, is what this tags.)
        """
        from src.costing.provenance import Provenance
        mp = self.data.get("material_prices", {}) or {}
        for key_suffix, note in ((material_name, "shop lot price"),
                                 (f"@{material_class}", f"shop {material_class} lot price")):
            if key_suffix in mp:
                dotted = f"material_price.{key_suffix}"
                return float(mp[key_suffix]), self.prov_tag(dotted), note
        return float(default_price), Provenance.DEFAULT, "material-DB unit price (DEFAULT book value)"

    # ---- per-process getter ---------------------------------------------
    def p(self, process: ProcessType, key: str):
        return self.data["process"][process][key]

    # ---- region split (weakness #4) -------------------------------------
    def region_prov(self, region: str):
        """Provenance of the region selection / its three multiplier vectors.

        USER when the buyer picked a non-default region or overrode a region
        vector ad-hoc; SHOP when the active profile declares this region (or pins
        its multipliers); DEFAULT otherwise.
        """
        from src.costing.provenance import Provenance
        vecs = ("region_labor", "region_material", "region_tooling")
        has_user = any(k.split(".", 1)[0] in vecs for k in self.user_keys if "." in k)
        has_shop = any(k.split(".", 1)[0] in vecs for k in self.shop_keys if "." in k)
        if self.shop_region is not None and self.shop_region == region:
            return Provenance.USER if has_user else Provenance.SHOP
        if region != "US" or has_user:
            return Provenance.USER
        if has_shop:
            return Provenance.SHOP
        return Provenance.DEFAULT

    def region_labor(self, region: str) -> float:
        return self.data["region_labor"].get(region, 1.0)

    def region_material(self, region: str) -> float:
        return self.data["region_material"].get(region, 1.0)

    def region_tooling(self, region: str) -> float:
        return self.data["region_tooling"].get(region, 1.0)

    def machine_region_mult(self, region: str) -> float:
        """Effective region multiplier for the MACHINE line (E-now #2).

        Only the operator-labor share (machine_labor_frac) of the loaded machine
        rate follows regional labor; the capital+facility+energy share is a
        global commodity (region ×1). CADVERIFY_MACHINE_CAPITAL_SPLIT=0 (or
        machine_labor_frac=1.0) recovers the legacy whole-rate discount exactly.
        """
        import os
        rl = self.region_labor(region)
        if os.getenv("CADVERIFY_MACHINE_CAPITAL_SPLIT", "1") == "0":
            return rl
        frac = self.g("machine_labor_frac")
        return (1.0 - frac) + frac * rl

    # ---- per-process getter with a default (new/optional keys) -----------
    def pget(self, process: ProcessType, key: str, default: float = 0.0) -> float:
        """Read a per-process numeric key that may be absent on some processes
        (nre_hr, fai_hr, inspect_hr_part, finish_lot_charge, finish_per_part).
        Absent => the default (0.0), i.e. the line simply does not apply."""
        v = self.data["process"][process].get(key)
        return float(v) if v is not None else float(default)

    # ---- additive build-plate nesting (weaknesses #1, #2) ---------------
    def build_env(self, proc: ProcessType) -> tuple:
        return tuple(self.p(proc, "build_env_mm"))

    def packing_density(self, proc: ProcessType) -> float:
        return self.p(proc, "packing_density")

    def part_spacing(self, proc: ProcessType) -> float:
        return self.p(proc, "part_spacing_mm")

    def nesting_mode(self, proc: ProcessType) -> str:
        return self.p(proc, "nesting_mode")

    def xy_packing_density(self, proc: ProcessType) -> float:
        """Areal packing fraction of the build plate for serial (FDM/SLA) XY
        nesting — parts laid flat in one layer (R2)."""
        return self.p(proc, "xy_packing_density")

    # ---- finite-capacity lead-time pool (R1) ----------------------------
    def machine_pool(self, proc: ProcessType) -> int:
        """Bureau parallel-machine pool size for this process (>= 1)."""
        return max(1, int(self.p(proc, "n_machines")))

    def machine_hours_per_day(self, proc: ProcessType) -> float:
        """Realistic daily uptime; falls back to the global single-shift default
        for processes without the per-process key."""
        v = self.data["process"][proc].get("machine_hours_per_day")
        return float(v) if v is not None else float(self.g("daily_machine_hours"))

    # ---- lot model + order floor (weaknesses #3, #8) --------------------
    def min_charge(self, proc: ProcessType) -> float:
        return float(self.p(proc, "min_charge"))

    def lot_size_raw(self, proc: ProcessType):
        return self.p(proc, "lot_size")            # int or the "build" sentinel

    # ---- domain helpers --------------------------------------------------
    def mrr(self, material_class: str) -> float:
        return self.data["mrr"].get(material_class, 8)

    def edm_cut_rate(self, material_class: str) -> float:
        """Wire-EDM swept-area cut rate (mm²/hr) by material class (DEFAULT)."""
        return float(self.data["edm_cut_rate"].get(material_class, 6000))

    def tooling_cost(self, process: ProcessType, max_bbox_mm: float,
                     n_cavities: int = 1, complexity: str = "moderate") -> float:
        """Single-cavity size-tier base × n_cavities^cavity_exponent × complexity
        (weakness #5). A flat USER override is the whole tool (pre cavity/complexity)."""
        flat = self.data.get("_tooling_flat", {}).get(process)
        if flat is not None:
            return float(flat)
        tier = family_to_size_tier(max_bbox_mm)
        base = float(self.data["tooling"][tier])
        if process == ProcessType.DIE_CASTING:
            base = base * self.data["tooling_die_mult"]
        cav = float(n_cavities) ** self.data["cavity_exponent"]
        comp = self.data["complexity_factor"][complexity]
        return base * cav * comp

    def casting_forging_tooling(self, process: ProcessType, max_bbox_mm: float,
                                complexity: str = "moderate") -> float:
        """Hard-tooling cost for the CASTING / FORGING families: size-tier base ×
        family multiplier × complexity. Honors a flat USER override
        (`tooling.<PROCESS>`) exactly like `tooling_cost`. Multipliers order sand
        pattern < investment (wax die + shell) < forging die (see
        tooling_casting_mult / tooling_forging_mult). All DEFAULT, un-validated."""
        flat = self.data.get("_tooling_flat", {}).get(process)
        if flat is not None:
            return float(flat)
        tier = family_to_size_tier(max_bbox_mm)
        base = float(self.data["tooling"][tier])
        if process in CASTING:
            mult = float(self.data["tooling_casting_mult"][process])
        else:  # FORGING
            mult = float(self.data["tooling_forging_mult"])
        comp = self.data["complexity_factor"][complexity]
        return base * mult * comp

    def tooling_lead_days(self, process: ProcessType) -> float:
        return float(self.data["tooling_lead_days"].get(process, 0))

    def band_pct(self, process: ProcessType) -> float:
        return BAND_PCT[process_family(process)]

    def tolerance_factors(self, tolerance_class: str) -> tuple:
        """(cost_mult, band_add_pct) for a DECLARED tolerance class.

        Unknown / missing → 'standard' → (1.0, 0.0), i.e. a byte-identical
        no-op. The multiplier scales the tolerance-sensitive conversion terms;
        band_add_pct is added (absolute points) to the reported error band. Both
        are DEFAULT assumptions (governed via the rate card), never validated."""
        table = self.data.get("tolerance_class", {}) or {}
        tc = table.get(normalize_tolerance_class(tolerance_class)) or \
            table.get("standard", {"cost_mult": 1.0, "band_add_pct": 0.0})
        return float(tc.get("cost_mult", 1.0)), float(tc.get("band_add_pct", 0.0))


# Map a flag-style process token (e.g. "SLS", "INJECTION_MOLDING") to ProcessType.
_NAME_TO_PT = {pt.name: pt for pt in ProcessType}
_NAME_TO_PT.update({pt.value: pt for pt in ProcessType})


def _resolve_process_token(token: str):
    return _NAME_TO_PT.get(token) or _NAME_TO_PT.get(token.upper())


# per-process numeric fields accepted as dotted overrides (coerced to float)
_NUMERIC_FIELDS = {
    "machine_rate", "setup_hr", "post_hr", "post_hr_part", "post_hr_build",
    "scrap", "deposition", "vert", "finish", "queue_days", "post_days",
    "packing_density", "part_spacing_mm", "min_charge", "lot_size",
    # R1 finite-capacity pool + R2 serial XY nesting (all DEFAULT, overridable)
    "n_machines", "machine_hours_per_day", "xy_packing_density",
    # FABRICATION (sheet metal) cut/bend/handling physics (all overridable)
    "cut_speed_mm_min", "ref_gauge_mm", "sec_per_bend", "handling_hr",
    # E-now #3+#4: CNC NRE / inspection / outsourced secondary finishing
    "nre_hr", "fai_hr", "inspect_hr_part", "finish_lot_charge", "finish_per_part",
    # CASTING / FORGING / WIRE-EDM physics constants (all DEFAULT, overridable)
    "yield_loss", "pour_hr", "cool_min_per_kg",
    "flash_loss", "heat_min_per_kg", "press_hr", "trim_hr",
    "n_threads", "thread_min", "wire_cost_per_hr",
    # METAL-AM physics constants (powder-bed / binder-jet / DED — all DEFAULT, overridable)
    "plate_removal_hr", "support_removal_hr", "stress_relief_hr_build",
    "support_vol_frac", "metal_am_powder_mult",
    "sinter_hr_build", "sinter_rate", "shrinkage_linear", "parts_per_sinter_batch",
    "deposition_rate_kg_hr", "feedstock_mult", "finish_machining_frac",
}


def _apply_override(data: dict, raw_key: str, value) -> None:
    """Apply one dotted (or flat) override onto the rate-card `data` in place.

    Shared by ad-hoc USER overrides and SHOP-profile bindings so both flow through
    exactly the same validated path (the only difference is which key-set the
    caller records the key in, which drives provenance).
    """
    if "." in raw_key:
        field_name, suffix = raw_key.split(".", 1)
        # region-split + complexity tables key off a NON-process suffix
        if field_name in ("region_labor", "region_material", "region_tooling"):
            data[field_name][suffix] = float(value)
            return
        if field_name == "complexity_factor":
            data["complexity_factor"][suffix] = float(value)
            return
        # material lot price: suffix is a material NAME or "@<class>" sentinel
        if field_name == "material_price":
            data.setdefault("material_prices", {})[suffix] = float(value)
            return
        # everything else keys off a process token
        pt = _resolve_process_token(suffix)
        if pt is None:
            raise ValueError(f"Unknown process in override {raw_key!r}")
        if field_name == "tooling":
            data["_tooling_flat"][pt] = float(value)
        elif field_name == "build_env_mm":
            # 3-tuple envelope override — NOT coerced to float
            data["process"][pt]["build_env_mm"] = tuple(value)
        elif field_name == "lot_size":
            # "build" sentinel stays a string; numeric override -> int
            data["process"][pt]["lot_size"] = (
                value if isinstance(value, str) else int(float(value)))
        elif field_name in _NUMERIC_FIELDS and field_name in data["process"][pt]:
            data["process"][pt][field_name] = float(value)
        else:
            raise ValueError(f"Unknown per-process field {field_name!r} in {raw_key!r}")
    else:
        if raw_key == "cavity_exponent":
            data["cavity_exponent"] = float(value)
        elif raw_key in data["global"]:
            data["global"][raw_key] = float(value)
        else:
            raise ValueError(f"Unknown global rate key {raw_key!r}")


def build_rate_card(overrides: dict | None = None, *,
                    shop_overrides: dict | None = None,
                    shop_name: "str | None" = None,
                    shop_region: "str | None" = None,
                    base_rate_table: dict | None = None) -> RateCard:
    """Deep-copy the base card, bind the active SHOP profile (if any), then
    apply ad-hoc USER overrides on top.

    Precedence: DEFAULT (card) < SHOP (shop_overrides) < USER (overrides). A key
    set by both the shop and an ad-hoc override resolves to USER (the buyer
    explicitly overrode their own shop default for this quote).

    ``base_rate_table`` (W4 governed libraries): when supplied, it is the base
    DEFAULT table instead of the hardcoded ``RATE_CARD_V0`` — a governed,
    versioned, effective-dated rate card an org has published. ``None`` (the
    default) uses ``RATE_CARD_V0`` verbatim, so the pre-W4 behaviour is
    byte-identical. A governed card is still a table of DEFAULT assumptions: it
    changes *which* default numbers are used, never the provenance semantics —
    nothing here is presented as measured/validated.
    """
    data = copy.deepcopy(
        base_rate_table if base_rate_table is not None else RATE_CARD_V0
    )
    data.setdefault("_tooling_flat", {})
    data.setdefault("material_prices", {})
    shop_keys: set = set()
    user_keys: set = set()

    # 1) SHOP profile bindings first (the shop's measured reality).
    for raw_key, value in (shop_overrides or {}).items():
        _apply_override(data, raw_key, value)
        shop_keys.add(raw_key)

    # 2) Ad-hoc USER overrides win; a USER key supersedes the shop binding.
    for raw_key, value in (overrides or {}).items():
        _apply_override(data, raw_key, value)
        user_keys.add(raw_key)
        shop_keys.discard(raw_key)

    return RateCard(data=data, user_keys=user_keys, shop_keys=shop_keys,
                    shop_name=shop_name, shop_region=shop_region)
