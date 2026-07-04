"""Pure capability-matching + gap engine + service-environment gate (spec §5, §6).

This module is the verification-thesis crux: given a part's MEASURED geometry
drivers + DECLARED material/tolerance/environment, and an org's DECLARED machine
inventory, decide *can it be made, on WHICH of THEIR machines, or if not, exactly
what capability delta closes the gap* — or honestly abstain.

Design invariants (spec §2 — asserted in tests):
  * PURE — no DB, no I/O, no network. Everything is dataclasses + numeric
    comparisons, deterministic and exhaustively unit-testable.
  * NEVER fabricate a `makeable`. A missing capability field makes that gate
    ``unknown`` (a FitFailure whose ``have is None``), never a silent PASS. A
    clean PASS requires every gate satisfied by real DECLARED data.
  * Capabilities are USER-declared. An envelope "fits" is a MEASURED-geometry ×
    USER-capability comparison; tolerance / secondary-op capability is DECLARED,
    never a measurement of the machine.
  * Environment exclusions CITE the property/standard (NACE MR0175, max service
    temp); gaps are concrete + quantified (measured-vs-declared delta).
  * No inventory / no env → ``unknown`` / no-op (byte-identical-when-unused).

Nothing here reaches into the rate card for a price: "cost" here is only a
``resource_hint`` (which machine + which rate basis to use) handed back to the
caller — the fit engine never invents a dollar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis.models import ProcessType
from src.costing.rates import (
    MATERIAL_FAMILY,
    normalize_tolerance_class,
    process_family,
)

# ─────────────────────────────────────────────────────────────────────────────
# LOCKED shared type contract (Phase A imports these — field names/shapes fixed)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MachineCap:
    """One owned machine (or identical group) hydrated to a DB-free dataclass.

    Every field is the org's DECLARATION (provenance USER). ``capabilities`` is
    the per-process-family scalar bag (spec §3): envelope, force/energy,
    reach/access, resolution, material-special gates.
    """

    process: str
    name: str
    count: int = 1
    max_workpiece_kg: "float | None" = None
    hourly_rate_usd: "float | None" = None
    capital_frac: "float | None" = None
    materials: tuple = ()
    material_thickness_map: dict = field(default_factory=dict)
    capabilities: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ShopCaps:
    """Shop-level (NOT per-machine) secondary-op capabilities (spec §3.1).

    ``ops`` maps an op name to ``True`` (available, unbounded) or a size-limit
    dict, e.g. ``{"hip": {"dia_mm": 300, "height_mm": 600}, "grinding": True}``.
    """

    ops: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PartReq:
    """The part's requirements — MEASURED geometry + DECLARED material/tol/env."""

    process: str
    bbox_mm: tuple                       # sorted ascending (d0 <= d1 <= d2)
    rotational: bool = False
    rot_cross_dia_mm: float = 0.0
    rot_axis_len_mm: float = 0.0
    mass_kg: "float | None" = None       # None => density unknown => unknown gate
    material_name: str = ""
    material_class: str = "unknown"
    material_props: dict = field(default_factory=dict)
    tolerance_it: "int | None" = None    # required IT grade (lower = tighter)
    min_feature_mm: float = 0.0
    required_secondary_ops: tuple = ()
    thickness_mm: "float | None" = None
    sheet_like: bool = False


@dataclass(frozen=True)
class FitFailure:
    """A single failed (or unknown) gate.

    ``have is None`` is the sentinel for UNKNOWN (capability not declared) — it
    is NOT a hard geometric/material failure, and verify_part maps a machine
    whose only failures are unknown to the ``unknown`` verdict, never a gap.
    """

    gate: str            # envelope|mass|material|tolerance|axes|force|thickness|min_feature|secondary_op|environment
    axis: str
    need: object = None
    have: object = None
    human: str = ""


@dataclass(frozen=True)
class FitResult:
    machine: str
    passes: bool
    failures: tuple = ()
    resource_hint: "dict | None" = None


@dataclass(frozen=True)
class MakeabilityVerdict:
    verdict: str                         # §0 lattice
    best_machine: "str | None" = None
    resource: "dict | None" = None
    gap: tuple = ()                      # FitFailure[], BINDING-CONSTRAINT FIRST
    env_exclusions: tuple = ()
    per_route: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Constants / declared mappings (all tagged assumptions)
# ─────────────────────────────────────────────────────────────────────────────

# TOLERANCE CLASS → IT ORDINAL (spec open-decision #3).
#
# CAVEAT / ASSUMPTION: an ISO-286 IT grade is SIZE-DEPENDENT (the ± band for IT7
# differs at 10mm vs 500mm). The declared tolerance_class carries no size, so
# this is a deliberately COARSE class→grade map, tagged an assumption, NOT a
# per-dimension ISO-286 computation. "standard" == the neutral no-op (IT11, the
# loosest) so an omitted/standard declaration never engages the tolerance gate
# (byte-identical to pre-feature). Lower IT number = tighter.
TOLERANCE_IT_MAP: dict = {"standard": 11, "precision": 8, "tight": 6}
STANDARD_IT = 11  # >= this => no tolerance constraint (neutral no-op class)

# Typical IT grade a base process family holds WITHOUT a precision finishing op.
# Coarse, DEFAULT/assumption (used only to derive whether a part *typically*
# needs grinding; the per-machine tolerance gate is the authoritative check).
BASE_PROCESS_IT: dict = {
    "subtractive": 9, "edm": 7, "additive": 12, "metal_powder_bed": 11,
    "binder_jet": 12, "ded": 13, "casting": 13, "forging": 12,
    "fabrication": 11, "formative": 11,
}

# Gate ordering for gap_analysis: the constraints that most DEFINE the required
# machine class come first (envelope/axes), then qualification/precision, then
# the rest. "Binding-constraint first" — see gap_analysis docstring.
GATE_PRIORITY: list = [
    "envelope", "axes", "material", "tolerance", "mass",
    "force", "thickness", "min_feature", "secondary_op", "environment",
]

# Corrosion-resistant-alloy classes (for corrosive/sour environment gating).
CRA_CLASSES = {"stainless", "nickel", "titanium", "cobalt"}

_MILLING = {ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS}

_NAME_TO_PT: dict = {pt.name: pt for pt in ProcessType}
_NAME_TO_PT.update({pt.value: pt for pt in ProcessType})


def _resolve_pt(process) -> "ProcessType | None":
    """Resolve a ProcessType | value-string | name-string to a ProcessType."""
    if isinstance(process, ProcessType):
        return process
    if isinstance(process, str):
        return _NAME_TO_PT.get(process) or _NAME_TO_PT.get(process.upper())
    return None


def _pt_value(process) -> str:
    pt = _resolve_pt(process)
    return pt.value if pt is not None else str(process)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Part-requirement extraction
# ─────────────────────────────────────────────────────────────────────────────


def _env_pressure_critical(env) -> bool:
    """Env implies a fatigue/pressure-critical duty (→ HIP for cast/AM)."""
    if not env:
        return False
    return bool(
        env.get("fatigue_critical")
        or env.get("pressure_containing")
        or (_is_number(env.get("pressure_bar")) and env.get("pressure_bar") > 0)
    )


def _required_secondary_ops(pt, material_class, tolerance_it, env) -> tuple:
    """Derive the secondary ops a part REQUIRES from material+process+env.

    - metal powder-bed / DED (metal AM) → ``stress_relief`` (before plate removal)
    - binder-jet green part            → ``sinter``
    - fatigue/pressure-critical cast or AM (per env) → ``hip``
    - tolerance tighter than the base process typically holds → ``grinding``

    ``grinding`` is a HINT here; the authoritative precision check is the
    per-machine tolerance gate in ``fit_machine`` (a precision machine may hold
    the grade natively, needing no grind).
    """
    ops: list = []
    fam = process_family(pt) if pt is not None else None
    if fam in ("metal_powder_bed", "ded"):
        ops.append("stress_relief")
    if fam == "binder_jet":
        ops.append("sinter")
    if _env_pressure_critical(env) and fam in (
        "casting", "metal_powder_bed", "binder_jet", "ded"
    ):
        ops.append("hip")
    base_it = BASE_PROCESS_IT.get(fam)
    if tolerance_it is not None and base_it is not None and tolerance_it < base_it:
        ops.append("grinding")
    # de-dup, order-preserving
    seen: set = set()
    out: list = []
    for op in ops:
        if op not in seen:
            seen.add(op)
            out.append(op)
    return tuple(out)


def part_req_from_drivers(process, drivers, material, tolerance_class,
                          material_props=None, env=None) -> PartReq:
    """Extract the MEASURED + DECLARED requirements into a PartReq.

    ``drivers`` is a GeoDrivers (duck-typed). ``material`` may be a
    MaterialProfile-like object (``.name``/``.density``) or a bare name string.
    ``material_props`` carries the property flags the env + special gates read
    (nace_mr0175, sour_service, max_temperature_c, conductive, ...).
    """
    pt = _resolve_pt(process)
    material_props = dict(material_props or {})

    # material identity + density
    if isinstance(material, str):
        name = material
        density = material_props.get("density")
    else:
        name = getattr(material, "name", "") or material_props.get("name", "")
        density = getattr(material, "density", None)
        if density is None:
            density = material_props.get("density")
    material_class = (
        MATERIAL_FAMILY.get(name)
        or material_props.get("class")
        or "unknown"
    )

    # mass — None when density is unknown (→ unknown mass gate, never a fake pass)
    mass_kg = None
    if _is_number(density) and hasattr(drivers, "mass_kg"):
        mass_kg = drivers.mass_kg(density)

    tc = normalize_tolerance_class(tolerance_class)
    tolerance_it = TOLERANCE_IT_MAP.get(tc, STANDARD_IT)

    # thickness (stock/gauge) for laser/EDM/sheet gates: sheet gauge when the
    # part reads as a flat blank, else the thinnest bbox extent (blank thickness)
    bbox = tuple(drivers.bbox_mm)
    sheet_like = bool(getattr(drivers, "sheet_like", False))
    if sheet_like and getattr(drivers, "sheet_gauge_mm", 0.0):
        thickness_mm = float(drivers.sheet_gauge_mm)
    elif bbox:
        thickness_mm = float(bbox[0])
    else:
        thickness_mm = None

    req_ops = _required_secondary_ops(pt, material_class, tolerance_it, env)

    return PartReq(
        process=_pt_value(pt if pt is not None else process),
        bbox_mm=bbox,
        rotational=bool(getattr(drivers, "rotational", False)),
        rot_cross_dia_mm=float(getattr(drivers, "rot_cross_dia_mm", 0.0) or 0.0),
        rot_axis_len_mm=float(getattr(drivers, "rot_axis_len_mm", 0.0) or 0.0),
        mass_kg=mass_kg,
        material_name=name,
        material_class=material_class,
        material_props=material_props,
        tolerance_it=tolerance_it,
        min_feature_mm=float(getattr(drivers, "nominal_wall_mm", 0.0) or 0.0),
        required_secondary_ops=req_ops,
        thickness_mm=thickness_mm,
        sheet_like=sheet_like,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. fit_machine — the six gate types (spec §5)
# ─────────────────────────────────────────────────────────────────────────────


def _sorted_env(cap: dict, keys) -> "list | None":
    vals = [cap.get(k) for k in keys]
    if any(not _is_number(v) for v in vals):
        return None
    return sorted(float(v) for v in vals)


def _machine_envelope(cap: dict):
    """Return (kind, sorted_extents | special) for the machine's envelope.

    kind ∈ {"turning", "sheet", "rect"}; None extents => not declared (unknown).
    """
    if any(k in cap for k in ("swing_dia", "swing_dia_mm", "between_centers")):
        return "turning", cap
    if "bed_x" in cap or "bed_y" in cap:
        return "sheet", _sorted_env(cap, ("bed_x", "bed_y"))
    for keyset in (("x", "y", "z"), ("flask_x", "flask_y", "flask_z"),
                   ("platen_x", "platen_y", "daylight")):
        if all(k in cap for k in keyset):
            return "rect", _sorted_env(cap, keyset)
    return "rect", None


def _envelope_failures(part: PartReq, cap: dict) -> list:
    kind, env = _machine_envelope(cap)
    fails: list = []
    if kind == "turning":
        swing = cap.get("swing_dia", cap.get("swing_dia_mm"))
        length = cap.get("between_centers")
        if part.rotational:
            need_dia, need_len = part.rot_cross_dia_mm, part.rot_axis_len_mm
        else:  # non-rotational on a lathe: bbox proxy (mid dia, long length)
            b = part.bbox_mm
            need_dia = b[1] if len(b) > 1 else (b[0] if b else 0.0)
            need_len = b[-1] if b else 0.0
        if not _is_number(swing):
            fails.append(FitFailure("envelope", "swing_dia", round(need_dia, 2),
                                    None, "swing diameter not declared"))
        elif need_dia > swing:
            fails.append(FitFailure(
                "envelope", "swing_dia", round(need_dia, 2), round(float(swing), 2),
                f"swing {need_dia:.0f}mm > machine {float(swing):.0f}mm "
                f"(need >={need_dia:.0f}mm)"))
        if not _is_number(length):
            fails.append(FitFailure("envelope", "between_centers",
                                    round(need_len, 2), None,
                                    "between-centers length not declared"))
        elif need_len > length:
            fails.append(FitFailure(
                "envelope", "between_centers", round(need_len, 2),
                round(float(length), 2),
                f"length {need_len:.0f}mm > machine {float(length):.0f}mm "
                f"(need >={need_len:.0f}mm)"))
        return fails

    # rectangular / sheet — orientation permutation (sorted vs sorted)
    if env is None:
        return [FitFailure("envelope", "envelope", tuple(part.bbox_mm), None,
                           "work envelope not declared")]
    if kind == "sheet":
        b = part.bbox_mm
        need = sorted([b[1], b[2]]) if len(b) >= 3 else sorted(b)
        labels = ("footprint", "footprint")
    else:
        need = list(part.bbox_mm)
        labels = ("shortest", "mid", "longest")
    # compare best-orientation sorted-vs-sorted; report the single worst axis
    n = min(len(need), len(env))
    worst = None
    for i in range(n):
        if need[i] > env[i]:
            delta = need[i] - env[i]
            if worst is None or delta > worst[0]:
                worst = (delta, need[i], env[i], labels[min(i, len(labels) - 1)])
    if worst is not None:
        _, nd, hv, lbl = worst
        fails.append(FitFailure(
            "envelope", "envelope", round(nd, 2), round(hv, 2),
            f"{lbl} {nd:.0f}mm > machine {hv:.0f}mm (need >={nd:.0f}mm)"))
    return fails


def _material_qualified(part: PartReq, materials: tuple) -> bool:
    tokens = {str(m).strip().lower().lstrip("@") for m in materials}
    return (part.material_name.strip().lower() in tokens
            or part.material_class.strip().lower() in tokens)


def fit_machine(part_req: PartReq, machine_cap: MachineCap,
                shop_caps: "ShopCaps | None" = None) -> FitResult:
    """Fit ONE part against ONE machine → PASS or a list of concrete failures.

    A FitFailure with ``have is None`` is an UNKNOWN (undeclared capability),
    not a hard fail; ``passes`` is True only when there are ZERO failures of
    either kind (honesty invariant #3 — never a fabricated pass).

    On PASS, ``resource_hint`` names the machine + its rate basis, and lists any
    shop secondary ops that were needed (present in-house) → the caller reads a
    non-empty ``secondary_ops`` as ``makeable_with_secondary_op``.
    """
    cap = machine_cap.capabilities or {}
    ops = (shop_caps.ops if shop_caps else {}) or {}
    failures: list = []
    needed_secondary: list = []

    # (a) ENVELOPE ----------------------------------------------------------
    failures.extend(_envelope_failures(part_req, cap))

    # (b) MASS --------------------------------------------------------------
    if machine_cap.max_workpiece_kg is None:
        failures.append(FitFailure("mass", "mass_kg",
                                   None if part_req.mass_kg is None
                                   else round(part_req.mass_kg, 3),
                                   None, "max workpiece weight not declared"))
    elif part_req.mass_kg is None:
        failures.append(FitFailure(
            "mass", "mass_kg", None, None,
            "part mass unknown (material density undeclared)"))
    elif part_req.mass_kg > machine_cap.max_workpiece_kg:
        failures.append(FitFailure(
            "mass", "mass_kg", round(part_req.mass_kg, 3),
            round(machine_cap.max_workpiece_kg, 3),
            f"part {part_req.mass_kg:.1f}kg > machine max "
            f"{machine_cap.max_workpiece_kg:.1f}kg"))

    # (c) MATERIAL QUALIFICATION -------------------------------------------
    if not machine_cap.materials:
        failures.append(FitFailure("material", "material", part_req.material_name,
                                   None, "no qualified materials declared"))
    elif not _material_qualified(part_req, machine_cap.materials):
        failures.append(FitFailure(
            "material", "material", part_req.material_name,
            tuple(machine_cap.materials),
            f"not qualified for {part_req.material_name or part_req.material_class}"))

    # (d) TOLERANCE / PRECISION --------------------------------------------
    #   standard (>=IT11) is the neutral no-op — gate does not engage.
    if part_req.tolerance_it is not None and part_req.tolerance_it < STANDARD_IT:
        ach = cap.get("achievable_it_grade")
        if ach is None:
            failures.append(FitFailure("tolerance", "it_grade",
                                       part_req.tolerance_it, None,
                                       "machine achievable IT grade not declared"))
        elif ach <= part_req.tolerance_it:
            pass  # machine holds the grade natively
        elif "grinding" in ops:
            needed_secondary.append("grinding")  # soft: shop grind reaches it
        else:
            failures.append(FitFailure(
                "tolerance", "it_grade", part_req.tolerance_it, int(ach),
                f"needs IT{part_req.tolerance_it}; machine holds IT{int(ach)} "
                f"(no in-house grinding)"))

    # (e) AXES / REACH (milling only) --------------------------------------
    #   "Needs 5-axis" is inherited from the ROUTE decision (spec open-decision
    #   #4): a part routed to CNC_5AXIS needs 5-axis simultaneous; we do NOT
    #   invent undercuts from geometry (conservative + honest — see report).
    pt = _resolve_pt(part_req.process)
    if pt in _MILLING:
        need_axes = 5 if pt == ProcessType.CNC_5AXIS else 3
        have_axes = cap.get("axes")
        if need_axes == 5:
            if not _is_number(have_axes):
                failures.append(FitFailure("axes", "axes", 5, None,
                                           "axis count not declared"))
            elif have_axes < 5:
                failures.append(FitFailure(
                    "axes", "axes", 5, int(have_axes),
                    f"needs 5-axis; machine is {int(have_axes)}-axis"))
            else:
                mode = cap.get("motion_mode")
                if mode is not None and mode != "simultaneous_5":
                    failures.append(FitFailure(
                        "axes", "motion_mode", "simultaneous_5", str(mode),
                        f"needs simultaneous 5-axis; machine is {mode}"))
        # need_axes == 3: 3 is the definitional floor of a milling process; an
        # undeclared axis count is treated as >=3 (the process's own floor, not
        # a fabricated capability). A declared <3 is impossible → ignored.

    # (f) FORCE / THICKNESS / POWER ----------------------------------------
    #   laser/EDM cut thickness by material (material_thickness_map); EDM
    #   conductivity + taper; brake/forge/mold tonnage (part must DECLARE the
    #   required tonnage — we never invent a forming force from geometry).
    tmap = machine_cap.material_thickness_map or {}
    if tmap and part_req.thickness_mm is not None:
        max_t = tmap.get(part_req.material_name)
        if max_t is None:
            max_t = tmap.get(part_req.material_class)
        if max_t is None:
            max_t = tmap.get("@" + part_req.material_class)
        if _is_number(max_t) and part_req.thickness_mm > max_t:
            failures.append(FitFailure(
                "thickness", "cut_thickness_mm", round(part_req.thickness_mm, 2),
                round(float(max_t), 2),
                f"thickness {part_req.thickness_mm:.1f}mm > machine max "
                f"{float(max_t):.1f}mm for "
                f"{part_req.material_name or part_req.material_class}"))

    if pt == ProcessType.WIRE_EDM and cap.get("conductive_required"):
        if not part_req.material_props.get("conductive"):
            failures.append(FitFailure(
                "force", "conductive", True,
                part_req.material_props.get("conductive"),
                f"wire-EDM requires a conductive workpiece; "
                f"{part_req.material_name} not declared conductive"))
        max_taper = cap.get("max_taper_deg")
        need_taper = part_req.material_props.get("taper_deg")
        if _is_number(max_taper) and _is_number(need_taper) and need_taper > max_taper:
            failures.append(FitFailure(
                "force", "taper_deg", need_taper, max_taper,
                f"taper {need_taper:.1f}deg > machine max {max_taper:.1f}deg"))

    need_tonnage = part_req.material_props.get("required_tonnage_t")
    if _is_number(need_tonnage):
        have_ton = None
        for k in ("tonnage_t", "press_tonnage_t", "clamp_tonnage_t"):
            if _is_number(cap.get(k)):
                have_ton = cap.get(k)
                break
        if have_ton is None:
            failures.append(FitFailure("force", "tonnage_t", need_tonnage, None,
                                       "machine tonnage not declared"))
        elif need_tonnage > have_ton:
            failures.append(FitFailure(
                "force", "tonnage_t", need_tonnage, float(have_ton),
                f"needs {need_tonnage:.0f}t; machine {float(have_ton):.0f}t"))

    # (g) MIN FEATURE -------------------------------------------------------
    #   engaged only when the machine DECLARES a min feature (a refinement gate).
    m_minfeat = cap.get("min_feature_mm", cap.get("min_wall_mm"))
    if (_is_number(m_minfeat) and part_req.min_feature_mm
            and part_req.min_feature_mm < m_minfeat):
        failures.append(FitFailure(
            "min_feature", "min_feature_mm", round(part_req.min_feature_mm, 3),
            round(float(m_minfeat), 3),
            f"feature {part_req.min_feature_mm:.2f}mm < machine min "
            f"{float(m_minfeat):.2f}mm"))

    # (h) SECONDARY OPS (physics-mandated; grinding is owned by the tol gate) --
    for op in part_req.required_secondary_ops:
        if op == "grinding":
            continue
        avail = ops.get(op)
        if avail is None:
            # a MISSING required op is a concrete gap (you lack this capability),
            # NOT an "undeclared datum" unknown → have=False (a hard failure).
            failures.append(FitFailure(
                "secondary_op", op, op, False,
                f"requires {op}; not available in-house"))
        elif isinstance(avail, dict):
            # size-limited op (e.g. HIP vessel) — part must fit its envelope
            b = part_req.bbox_mm
            dia = max(b[:-1]) if len(b) >= 2 else (b[0] if b else 0.0)
            height = b[-1] if b else 0.0
            lim_d, lim_h = avail.get("dia_mm"), avail.get("height_mm")
            over = ((_is_number(lim_d) and dia > lim_d)
                    or (_is_number(lim_h) and height > lim_h))
            if over:
                failures.append(FitFailure(
                    "secondary_op", op, (round(dia, 1), round(height, 1)),
                    (lim_d, lim_h),
                    f"part exceeds {op} envelope {lim_d}x{lim_h}mm"))
            else:
                needed_secondary.append(op)
        else:  # True / available, unbounded
            needed_secondary.append(op)

    passes = len(failures) == 0
    resource_hint = None
    if passes:
        resource_hint = {
            "machine": machine_cap.name,
            "process": part_req.process,
            "rate_basis": "machine_hr",
            "hourly_rate_usd": machine_cap.hourly_rate_usd,
            "capital_frac": machine_cap.capital_frac,
            "secondary_ops": tuple(dict.fromkeys(needed_secondary)),
        }
    return FitResult(machine=machine_cap.name, passes=passes,
                     failures=tuple(failures), resource_hint=resource_hint)


# ─────────────────────────────────────────────────────────────────────────────
# 3. environment_gate (spec §6)
# ─────────────────────────────────────────────────────────────────────────────


def _env_requires_sour(env: dict) -> bool:
    return bool(env.get("sour_service") or env.get("sour"))


def _mat_flag(p: dict, key: str):
    """Read a material compliance/property flag from a props dict, accepting BOTH
    shapes: a FLAT top-level value (hand-built dicts / overrides) OR one nested
    under a ``compliance`` sub-dict — the shape ``MaterialProfile`` stores
    compliance flags in (``MaterialProfile.compliance``, e.g. ``nace_mr0175`` /
    ``sour_service``). Top-level WINS on conflict, so a flat override still beats a
    nested value. Returns None when neither carries the key.

    Without this the gate read the flags flat only and silently saw NO
    qualification on real ``MaterialProfile``-derived props (all flags live under
    ``compliance``), which would wrongly exclude every NACE/sour-qualified alloy.
    """
    if key in p:
        return p[key]
    compliance = p.get("compliance")
    if isinstance(compliance, dict):
        return compliance.get(key)
    return None


def environment_gate(routes, materials, env, material_props_by_name=None):
    """Drop routes/materials INVALID for the declared service environment.

    Returns ``(valid, exclusions)`` where ``valid`` is a dict
    ``{"routes":[...], "materials":[...], "excluded_materials":set,
    "excluded_routes":set}`` and ``exclusions`` is a tuple of FitFailure, each
    CITING the property/standard (honesty invariant #4). No env → no-op: the
    inputs are returned unchanged with no exclusions (byte-identical).
    """
    routes = [_pt_value(r) for r in (routes or [])]
    materials = list(materials or [])
    props = material_props_by_name or {}

    if not env:
        return ({"routes": routes, "materials": materials,
                 "excluded_materials": set(), "excluded_routes": set()}, ())

    exclusions: list = []
    excluded_materials: set = set()

    sour = _env_requires_sour(env)
    corrosive = bool(env.get("corrosive"))
    max_temp = env.get("max_temp_c")

    for mat in materials:
        p = props.get(mat, {}) or {}
        mclass = p.get("class") or MATERIAL_FAMILY.get(mat, "unknown")

        # sour service → require NACE MR0175 / sour_service qualification
        if sour and not (_mat_flag(p, "nace_mr0175") or _mat_flag(p, "sour_service")):
            excluded_materials.add(mat)
            exclusions.append(FitFailure(
                "environment", mat, "NACE MR0175 sour-service qualified",
                {"nace_mr0175": _mat_flag(p, "nace_mr0175"),
                 "sour_service": _mat_flag(p, "sour_service")},
                f"{mat} excluded: sour service requires NACE MR0175 "
                f"qualification (material not NACE MR0175 / sour_service)"))
            continue

        # over-temperature → material max service temp must clear the env
        if _is_number(max_temp):
            mt = _mat_flag(p, "max_temperature_c")
            if mt is None:
                mt = _mat_flag(p, "max_temperature")
            if _is_number(mt) and mt < max_temp:
                excluded_materials.add(mat)
                exclusions.append(FitFailure(
                    "environment", mat, f">={max_temp}C service", f"{mt}C max",
                    f"{mat} excluded: service {max_temp:.0f}C exceeds material "
                    f"max service temperature {mt:.0f}C"))
                continue

        # corrosive (non-sour) → require a corrosion-resistant alloy class
        if corrosive and not sour and mclass not in CRA_CLASSES \
                and not (_mat_flag(p, "nace_mr0175") or _mat_flag(p, "cra")):
            excluded_materials.add(mat)
            exclusions.append(FitFailure(
                "environment", mat, "corrosion-resistant alloy", mclass,
                f"{mat} excluded: corrosive service requires a CRA "
                f"(class '{mclass}' is not corrosion-resistant)"))

    excluded_routes: set = {
        _pt_value(r) for r in (env.get("excluded_processes") or [])
    }
    for r in routes:
        if r in excluded_routes:
            exclusions.append(FitFailure(
                "environment", r, "process permitted by environment", r,
                f"route {r} excluded by declared environment"))

    valid_routes = [r for r in routes if r not in excluded_routes]
    valid_materials = [m for m in materials if m not in excluded_materials]
    return ({"routes": valid_routes, "materials": valid_materials,
             "excluded_materials": excluded_materials,
             "excluded_routes": excluded_routes}, tuple(exclusions))


# ─────────────────────────────────────────────────────────────────────────────
# 4. gap_analysis (spec §5)
# ─────────────────────────────────────────────────────────────────────────────


def _rel_delta(f: FitFailure) -> float:
    if _is_number(f.need) and _is_number(f.have) and f.have:
        return max(0.0, (f.need - f.have) / abs(f.have))
    return 1.0  # categorical / can't quantify → treat as a full-class delta


def _abs_delta(f: FitFailure):
    if _is_number(f.need) and _is_number(f.have):
        return f.need - f.have
    return None


def _gate_rank(gate: str) -> int:
    return GATE_PRIORITY.index(gate) if gate in GATE_PRIORITY else len(GATE_PRIORITY)


def gap_analysis(closest_fit_results) -> tuple:
    """Collapse the closest machines' HARD failures to the minimal spec delta,
    BINDING-CONSTRAINT FIRST.

    "Binding constraint" = the constraint that most defines the machine class
    you would have to acquire. The ordering is deterministic:
      1. group hard failures by (gate, axis) and, per group, keep the SMALLEST
         delta across machines (the closest existing capability — "you're only
         X short", not the worst machine),
      2. order groups by GATE_PRIORITY (envelope/axes lead — they set the
         machine class), then by LARGEST relative delta, then axis name.
    Fixing the lead constraint may reveal the next; every listed gap must be
    satisfied for the part to become makeable. Unknown (undeclared) failures are
    excluded — a gap is a CONCRETE measured-vs-declared delta, never "unknown".

    Accepts an iterable of FitResult, or a bare iterable of FitFailure.
    """
    groups: dict = {}
    for item in closest_fit_results or []:
        if isinstance(item, FitFailure):
            failures = (item,)
        else:
            failures = getattr(item, "failures", ())
        for f in failures:
            if f.have is None:  # skip unknowns — not a concrete gap
                continue
            key = (f.gate, f.axis)
            d = _abs_delta(f)
            prev = groups.get(key)
            if prev is None:
                groups[key] = f
            else:
                pd = _abs_delta(prev)
                if d is not None and pd is not None and d < pd:
                    groups[key] = f  # closer machine → smaller delta

    ordered = sorted(
        groups.values(),
        key=lambda f: (_gate_rank(f.gate), -_rel_delta(f), str(f.axis)),
    )
    return tuple(ordered)


# ─────────────────────────────────────────────────────────────────────────────
# 5. verify_part — the §0 verdict lattice
# ─────────────────────────────────────────────────────────────────────────────


def _hard(failures) -> list:
    return [f for f in failures if f.have is not None]


def _unknown(failures) -> list:
    return [f for f in failures if f.have is None]


def _machine_score(fr: FitResult):
    """Lower = closer to passing (fewest hard fails, then smallest rel delta)."""
    hard = _hard(fr.failures)
    return (len(hard), sum(_rel_delta(f) for f in hard))


def verify_part(part_req_by_route, inventory, shop_caps=None, env=None,
                material_props=None) -> MakeabilityVerdict:
    """Top verdict over all routes (§0 lattice).

    part_req_by_route: {route(process) : PartReq}. inventory: [MachineCap].
    Honesty: empty/absent inventory → ``unknown`` (byte-identical-when-unused);
    a makeable verdict is returned ONLY when a machine passes every gate on real
    declared data.
    """
    material_props = material_props or {}

    # honesty invariant #1: no inventory declared → unknown, no-op.
    if not inventory:
        return MakeabilityVerdict(verdict="unknown")

    if not part_req_by_route:
        return MakeabilityVerdict(verdict="not_makeable")

    # normalise route keys, keep the PartReq association
    route_req: dict = {}
    route_material: dict = {}
    for r, preq in part_req_by_route.items():
        rv = _pt_value(r)
        route_req[rv] = preq
        route_material[rv] = getattr(preq, "material_name", "")

    routes = list(route_req.keys())
    materials = list({route_material[r] for r in routes if route_material[r]})

    gate, exclusions = environment_gate(routes, materials, env, material_props)
    excluded_materials = gate["excluded_materials"]
    excluded_routes = gate["excluded_routes"]
    valid_routes = [
        r for r in routes
        if route_material.get(r) not in excluded_materials
        and r not in excluded_routes
    ]

    if not valid_routes:
        # there WERE routes, all environment-excluded
        return MakeabilityVerdict(verdict="environment_excluded",
                                  env_exclusions=tuple(exclusions))

    passes: list = []                 # (secondary_count, cost, FitResult, route)
    not_on_owned: list = []           # (score, route, fits)
    unknown_routes: list = []         # route
    outsource_routes: list = []       # route
    per_route: dict = {}

    for r in valid_routes:
        preq = route_req[r]
        owned = [m for m in inventory if _pt_value(m.process) == r]
        if not owned:
            outsource_routes.append(r)
            per_route[r] = {"verdict": "makeable_outsource_only",
                            "machines_evaluated": 0, "best_machine": None,
                            "failures": ()}
            continue

        fits = [fit_machine(preq, m, shop_caps) for m in owned]
        route_passes = [f for f in fits if f.passes]
        if route_passes:
            best = min(
                route_passes,
                key=lambda f: (
                    len(f.resource_hint.get("secondary_ops", ())),
                    f.resource_hint.get("hourly_rate_usd")
                    if _is_number(f.resource_hint.get("hourly_rate_usd"))
                    else float("inf")))
            sec = len(best.resource_hint.get("secondary_ops", ()))
            cost = (best.resource_hint.get("hourly_rate_usd")
                    if _is_number(best.resource_hint.get("hourly_rate_usd"))
                    else float("inf"))
            passes.append((sec, cost, best, r))
            per_route[r] = {
                "verdict": ("makeable_in_house" if sec == 0
                            else "makeable_with_secondary_op"),
                "machines_evaluated": len(fits),
                "best_machine": best.machine,
                "failures": (),
                # the winning machine's rate basis (machine + declared rate +
                # capital_frac + secondary ops) so a caller can cost this route on
                # the fitted machine's OWN marginal rate (spec §7 cost_breakdown).
                # Present ONLY on a passing route; absent elsewhere.
                "resource": best.resource_hint,
            }
        else:
            closest = min(fits, key=_machine_score)
            if _hard(closest.failures):
                not_on_owned.append((_machine_score(closest), r, fits))
                per_route[r] = {"verdict": "makeable_not_on_owned",
                                "machines_evaluated": len(fits),
                                "best_machine": closest.machine,
                                "failures": tuple(_hard(closest.failures))}
            else:  # only unknown (undeclared) failures → can't confirm
                unknown_routes.append(r)
                per_route[r] = {"verdict": "unknown",
                                "machines_evaluated": len(fits),
                                "best_machine": closest.machine,
                                "failures": tuple(_unknown(closest.failures))}

    exclusions_t = tuple(exclusions)

    # verdict precedence (see module docstring / spec §0):
    #   in_house > with_secondary > not_on_owned > outsource_only > unknown
    if passes:
        best = min(passes, key=lambda t: (t[0], t[1]))
        sec, _cost, fr, _route = best
        verdict = ("makeable_in_house" if sec == 0
                   else "makeable_with_secondary_op")
        return MakeabilityVerdict(
            verdict=verdict, best_machine=fr.machine,
            resource=fr.resource_hint, env_exclusions=exclusions_t,
            per_route=per_route)

    if not_on_owned:
        not_on_owned.sort(key=lambda t: t[0])
        _score, _route, fits = not_on_owned[0]
        return MakeabilityVerdict(
            verdict="makeable_not_on_owned",
            gap=gap_analysis(fits), env_exclusions=exclusions_t,
            per_route=per_route)

    if outsource_routes:
        return MakeabilityVerdict(
            verdict="makeable_outsource_only", env_exclusions=exclusions_t,
            per_route=per_route)

    if unknown_routes:
        return MakeabilityVerdict(verdict="unknown", env_exclusions=exclusions_t,
                                  per_route=per_route)

    return MakeabilityVerdict(verdict="not_makeable", env_exclusions=exclusions_t,
                              per_route=per_route)
