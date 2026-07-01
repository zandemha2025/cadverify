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

# The bounded set V0 will produce a dollar should-cost for. Everything else is
# feasibility-only (honest: no number we cannot defend).
COSTED_PROCESSES = {
    PT.FDM, PT.SLA, PT.DLP, PT.SLS, PT.MJF,
    PT.CNC_3AXIS, PT.CNC_5AXIS, PT.CNC_TURNING,
    PT.INJECTION_MOLDING, PT.DIE_CASTING,
    PT.SHEET_METAL,
}

# Absolute-cost error band by family (the dominant-line band, spec §6.5).
BAND_PCT = {"additive": 40.0, "subtractive": 50.0, "formative": 60.0,
            "fabrication": 35.0}


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
        PT.CNC_3AXIS: dict(
            machine_rate=75, setup_hr=0.75, post_hr=0.50, scrap=0.05,
            deposition=None, vert=None, finish=600, queue_days=5, post_days=1,
            post_hr_part=0.50, post_hr_build=0.0, lot_size=100, min_charge=90,
            n_machines=8, machine_hours_per_day=16),
        PT.CNC_5AXIS: dict(
            machine_rate=110, setup_hr=1.00, post_hr=0.50, scrap=0.05,
            deposition=None, vert=None, finish=500, queue_days=7, post_days=1,
            post_hr_part=0.50, post_hr_build=0.0, lot_size=100, min_charge=110,
            n_machines=4, machine_hours_per_day=16),
        PT.CNC_TURNING: dict(
            machine_rate=65, setup_hr=0.50, post_hr=0.30, scrap=0.05,
            deposition=None, vert=None, finish=800, queue_days=5, post_days=1,
            post_hr_part=0.30, post_hr_build=0.0, lot_size=100, min_charge=90,
            n_machines=6, machine_hours_per_day=16),
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
    },
    # Shop-specific material lot prices ($/kg). Empty by default → fall back to
    # the material-DB cost_per_kg (a generic DEFAULT). A calibrated shop binds its
    # real negotiated lot prices here, keyed by exact material name (e.g.
    # "PA12 (Nylon 12)") or by a class sentinel ("@polymer", "@aluminum", ...).
    "material_prices": {},
    # CNC material-removal rate (cm^3/min) by material class.
    "mrr": {"polymer": 50, "aluminum": 30, "steel": 8, "stainless": 5, "titanium": 2},
    # Single-cavity tooling by part size tier (max bbox dim, mm). Die-casting = ×1.5.
    "tooling": {"S": 6000, "M": 15000, "L": 30000, "XL": 60000},
    "tooling_die_mult": 1.5,
    # Tooling cavity + complexity scaling (weakness #5). DEFAULT 1 cav, moderate.
    "cavity_exponent": 0.70,   # tool cost ~ n_cavities^0.70 (shared bolster/base)
    "complexity_factor": {"simple": 0.80, "moderate": 1.00, "complex": 1.50, "very_complex": 2.20},
    # Tooling lead time (days), applied once regardless of qty.
    "tooling_lead_days": {PT.INJECTION_MOLDING: 25, PT.DIE_CASTING: 35},
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
    "Mild Steel (Sheet)": "steel", "Ductile Iron": "steel",
    # titanium
    "Ti6Al4V": "titanium", "Ti6Al4V (Wrought)": "titanium", "Ti-6Al-4V Grade 5": "titanium",
    # nickel superalloy (deliberately its own family — never a default for a
    # polymer/aluminum/steel part; this is the structural fix for the teardown bug)
    "Inconel 718": "nickel", "Inconel 625": "nickel",
    # cobalt-chrome, zinc, copper (other families — excluded from V0 default classes)
    "CoCr": "cobalt", "CoCr ASTM F75": "cobalt",
    "Zinc Alloy (Zamak 3)": "zinc",
    "Copper C110 (Sheet)": "copper",
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
        material-DB price (MEASURED part mass × a DEFAULT unit price).
        """
        from src.costing.provenance import Provenance
        mp = self.data.get("material_prices", {}) or {}
        for key_suffix, note in ((material_name, "shop lot price"),
                                 (f"@{material_class}", f"shop {material_class} lot price")):
            if key_suffix in mp:
                dotted = f"material_price.{key_suffix}"
                return float(mp[key_suffix]), self.prov_tag(dotted), note
        return float(default_price), Provenance.MEASURED, "material-DB unit price (DEFAULT)"

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

    def tooling_lead_days(self, process: ProcessType) -> float:
        return float(self.data["tooling_lead_days"].get(process, 0))

    def band_pct(self, process: ProcessType) -> float:
        return BAND_PCT[process_family(process)]


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
                    shop_region: "str | None" = None) -> RateCard:
    """Deep-copy the default card, bind the active SHOP profile (if any), then
    apply ad-hoc USER overrides on top.

    Precedence: DEFAULT (card) < SHOP (shop_overrides) < USER (overrides). A key
    set by both the shop and an ad-hoc override resolves to USER (the buyer
    explicitly overrode their own shop default for this quote).
    """
    data = copy.deepcopy(RATE_CARD_V0)
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
