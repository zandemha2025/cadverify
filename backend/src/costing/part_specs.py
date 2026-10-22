"""Declared part specs: surface finish, heat treatment, inspection, certifications.

For aerospace, oil-and-gas, defense-MRO and rail parts these often cost more than
the machining itself, and an outside shop must hold certifications to make them.
This module is the PURE engine side (no DB, no I/O):

* ``validate_part_specs`` / ``normalize_part_specs``: the stored shape, USER-declared
  with the part's other context (``part_contexts.part_specs``).
* ``SpecSession``: one per cost run. For each (process, material) route it
  - adds a cost line and lead time per declared finish, heat treatment and
    inspection, priced from ``SPEC_OPS_V0`` (typical values, each with its source)
    unless the rate card overrides them (``spec_ops`` in a governed card, or a
    ``spec.<op>.<field>`` override);
  - decides whether the route can deliver the specs at all (Ra as made by the
    process, anodize needs aluminum, a metal heat treatment needs metal, …). A
    route that can't is flagged ``spec_excluded`` with the reason, and the
    make-or-buy decision is computed over the routes that can;
  - names what an in-house route needs from the shop (finishing / heat-treat /
    inspection ops and certifications) for the machine-fit check, where an
    undeclared capability is unknown, never "no".
* Certifications (AS9100, ISO 9001, NADCAP for named special processes, ITAR)
  carry no price: they are what whoever makes the part must hold.

Honesty: every number is either the user's, the rate card's, or a typical value
labelled with where it comes from. Nothing here flips a band to validated. No
declared specs → ``session_for`` returns None → the engine is byte-identical.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from src.costing.provenance import TYPICAL, Driver, Provenance

# ─────────────────────────────────────────────────────────────────────────────
# Vocabulary
# ─────────────────────────────────────────────────────────────────────────────

UM_PER_UIN = 0.0254          # exact: 1 µin = 0.0254 µm
SQFT_PER_M2 = 10.763910417   # 1 m² = 10.7639 ft² (1 ft = 0.3048 m exactly)

FINISHES: dict = {
    "as_machined": "As machined",
    "bead_blast": "Bead blast",
    "anodize_ii": "Anodize, Type II",
    "anodize_iii": "Hard anodize, Type III",
    "passivate": "Passivation",
    "electropolish": "Electropolish",
    "powder_coat": "Powder coat",
    "plating": "Plating",
}
HEAT_TREATMENTS: dict = {
    "stress_relief": "Stress relief",
    "solution_age": "Solution treat and age",
    "quench_temper": "Quench and temper",
    "case_harden": "Case hardening",
    "hip": "HIP (hot isostatic pressing)",
}
INSPECTIONS: dict = {
    "standard": "Standard inspection",
    "fai_as9102": "First article inspection, AS9102",
    "cmm_report": "CMM report",
    "full_100": "100% inspection",
}
CERTIFICATIONS: dict = {
    "as9100": "AS9100",
    "iso9001": "ISO 9001",
    "nadcap": "NADCAP",
    "itar": "ITAR registration",
}
NADCAP_PROCESSES: dict = {
    "chemical_processing": "chemical processing",
    "heat_treating": "heat treating",
    "nondestructive_testing": "nondestructive testing",
    "coatings": "coatings",
    "welding": "welding",
    "measurement_inspection": "measurement and inspection",
}
SPEC_FIELDS = frozenset({
    "finishes", "ra_um", "ra_unit", "heat_treatments", "inspection",
    "certifications", "nadcap_processes", "general_tolerance",
})
# The general tolerance for dimensions the drawing doesn't tolerance (buyer-06): an
# ISO 2768-1 class, or a ± value in the part's units. The buyer's statement for the
# supplier; the price doesn't use it (``stored_specs`` leaves it out of the engine).
ISO_2768_CLASSES: dict = {"f": "fine", "m": "medium", "c": "coarse", "v": "very coarse"}
TOLERANCE_UNITS = ("mm", "in")
TOLERANCE_MAX_MM = 10.0
NOT_PRICED_FIELDS = frozenset({"general_tolerance"})
RA_UNITS = ("um", "uin")
RA_MIN_UM, RA_MAX_UM = 0.012, 50.0

_METALS = frozenset({"aluminum", "steel", "stainless", "titanium", "nickel", "cobalt", "copper", "zinc"})
_AM_METAL_FAMILIES = frozenset({"metal_powder_bed", "binder_jet", "ded"})
_CASTING_FAMILIES = frozenset({"casting"})
_MACHINED_FAMILIES = frozenset({"subtractive", "edm", "ded"})  # DED's price includes finish machining

# Which material classes each op can be done on. None = any material.
_OP_MATERIALS: dict = {
    "bead_blast": None,
    "anodize_ii": frozenset({"aluminum"}),
    "anodize_iii": frozenset({"aluminum"}),
    "passivate": frozenset({"stainless"}),
    "electropolish": _METALS,
    "powder_coat": _METALS,
    "plating": _METALS,
    "stress_relief": _METALS,
    "solution_age": frozenset({"aluminum", "stainless", "titanium", "nickel"}),
    "quench_temper": frozenset({"steel", "stainless"}),
    "case_harden": frozenset({"steel"}),
    "hip": _METALS,
}
_OP_NEEDS = {
    "anodize_ii": "aluminum", "anodize_iii": "aluminum", "passivate": "stainless steel",
    "electropolish": "metal", "powder_coat": "metal", "plating": "metal",
    "stress_relief": "metal", "solution_age": "an age-hardening alloy (aluminum, titanium, nickel or PH stainless)",
    "quench_temper": "a hardenable steel", "case_harden": "steel", "hip": "metal",
}
# NADCAP special-process area each op falls under (when NADCAP is required).
_OP_NADCAP = {
    "anodize_ii": "chemical_processing", "anodize_iii": "chemical_processing",
    "passivate": "chemical_processing", "electropolish": "chemical_processing",
    "plating": "chemical_processing",
    "stress_relief": "heat_treating", "solution_age": "heat_treating",
    "quench_temper": "heat_treating", "case_harden": "heat_treating", "hip": "heat_treating",
}
_CLASS_WORDS = {"polymer": "plastic", "aluminum": "aluminum", "steel": "steel",
                "stainless": "stainless steel", "titanium": "titanium", "nickel": "nickel alloy",
                "cobalt": "cobalt-chrome", "copper": "copper", "zinc": "zinc"}

# ─────────────────────────────────────────────────────────────────────────────
# Typical prices and lead times (all overridable on the rate card)
# ─────────────────────────────────────────────────────────────────────────────

SRC_ANODIZE = ("Alibaba.com seller guide to anodizing (2026): Type II $0.50–2.50/ft², "
               "Type III $2–6/ft², small-order minimums $50–200 (Type II) and $100–300 (Type III)")
SRC_HEAT = ("IBISWorld heat treatment services benchmark (2026): $8.08 per lb of steel; "
            "a partial load pays the greater of the per-pound price and the lot minimum "
            "(HEF USA, liquid nitriding price page)")
SRC_ASSUMED = "ScaleCAD's assumption; no published price found"

# pricing kind: "area"  → order = max(lot_usd, per_m2_usd × area × qty)    (outside service)
#               "mass"  → order = max(lot_usd, per_kg_usd × mass × qty)    (outside service)
#               "labor" → hours = hr_per_order + (hr_per_part + hr_per_dm2 × area) × qty
SPEC_OPS_V0: dict = {
    "bead_blast": {"kind": "labor", "hr_per_order": 0.0, "hr_per_part": 0.10, "hr_per_dm2": 0.0,
                   "lead_days": 1.0, "source": SRC_ASSUMED},
    "anodize_ii": {"kind": "area", "lot_usd": 125.0, "per_m2_usd": round(1.50 * SQFT_PER_M2, 2),
                   "lead_days": 5.0, "source": SRC_ANODIZE},
    "anodize_iii": {"kind": "area", "lot_usd": 200.0, "per_m2_usd": round(4.00 * SQFT_PER_M2, 2),
                    "lead_days": 7.0, "source": SRC_ANODIZE},
    "passivate": {"kind": "area", "lot_usd": 100.0, "per_m2_usd": round(1.00 * SQFT_PER_M2, 2),
                  "lead_days": 3.0, "source": SRC_ASSUMED},
    "electropolish": {"kind": "area", "lot_usd": 150.0, "per_m2_usd": round(3.00 * SQFT_PER_M2, 2),
                      "lead_days": 4.0, "source": SRC_ASSUMED},
    "powder_coat": {"kind": "area", "lot_usd": 100.0, "per_m2_usd": round(3.00 * SQFT_PER_M2, 2),
                    "lead_days": 4.0, "source": SRC_ASSUMED},
    "plating": {"kind": "area", "lot_usd": 150.0, "per_m2_usd": round(5.00 * SQFT_PER_M2, 2),
                "lead_days": 5.0, "source": SRC_ASSUMED},
    "stress_relief": {"kind": "mass", "lot_usd": 150.0, "per_kg_usd": round(8.08 / 0.45359237, 2),
                      "lead_days": 3.0, "source": SRC_HEAT},
    "solution_age": {"kind": "mass", "lot_usd": 250.0, "per_kg_usd": round(8.08 / 0.45359237, 2),
                     "lead_days": 5.0, "source": SRC_HEAT},
    "quench_temper": {"kind": "mass", "lot_usd": 200.0, "per_kg_usd": round(8.08 / 0.45359237, 2),
                      "lead_days": 4.0, "source": SRC_HEAT},
    "case_harden": {"kind": "mass", "lot_usd": 300.0, "per_kg_usd": round(8.08 / 0.45359237, 2),
                    "lead_days": 7.0, "source": SRC_HEAT},
    "hip": {"kind": "mass", "lot_usd": 2500.0, "per_kg_usd": 40.0, "lead_days": 10.0,
            "source": SRC_ASSUMED},
    "fai_as9102": {"kind": "labor", "hr_per_order": 6.0, "hr_per_part": 0.0, "hr_per_dm2": 0.0,
                   "lead_days": 2.0, "source": SRC_ASSUMED},
    "cmm_report": {"kind": "labor", "hr_per_order": 2.5, "hr_per_part": 0.0, "hr_per_dm2": 0.0,
                   "lead_days": 1.0, "source": SRC_ASSUMED},
    "full_100": {"kind": "labor", "hr_per_order": 0.0, "hr_per_part": 0.15, "hr_per_dm2": 0.0,
                 "lead_days": 0.0, "source": SRC_ASSUMED},
    "fine_finish": {"kind": "labor", "hr_per_order": 0.0, "hr_per_part": 0.0, "hr_per_dm2": 0.05,
                    "lead_days": 1.0, "source": SRC_ASSUMED},
}
# What each labor op's hours are, in words (for the cost line's source).
_LABOR_WORDS = {
    "bead_blast": "blasting and handling",
    "fai_as9102": "a full AS9102 report (ballooned drawing, forms 1–3), on top of the first-part check already in the price",
    "cmm_report": "programming the CMM and measuring the first part",
    "full_100": "measuring every part",
    "fine_finish": "grinding or polishing every surface to the Ra you set",
}
OVERRIDE_FIELDS = frozenset({"lot_usd", "per_m2_usd", "per_kg_usd", "hr_per_order", "hr_per_part",
                             "hr_per_dm2", "lead_days"})
OP_LABELS = {**FINISHES, **HEAT_TREATMENTS, **INSPECTIONS, "fine_finish": "Fine finish to Ra"}

# ─────────────────────────────────────────────────────────────────────────────
# Roughness each process gives as made (µm Ra)
# ─────────────────────────────────────────────────────────────────────────────

SRC_MH = ("Machinery's Handbook, surface roughness produced by common production methods "
          "(after ASME B46.1)")
SRC_MV = "MakerVerse, Understanding surface roughness in 3D printing"
SRC_XOM = "Xometry Europe, Surface roughness in 3D printing"
SRC_EBM = "Defect analysis of as-built EBM Ti6Al4V (Arizona State University): Ra 6–27 µm by side and build direction"

# Short names for the roughness sources, as a finding cites them.
_SHORT = {
    SRC_MH: "Machinery's Handbook roughness chart",
    SRC_MV: "MakerVerse 3D-printing roughness guide",
    SRC_XOM: "Xometry 3D-printing roughness guide",
    SRC_EBM: "ASU study of as-built EBM Ti6Al4V",
    SRC_ASSUMED: "ScaleCAD's assumption",
}


def short_source(src: str) -> str:
    """"Machinery's Handbook roughness chart" for the long citation (the start of it)."""
    for long, short in _SHORT.items():
        if src.startswith(long):
            return short
    return src.split(" (")[0]


def _cap(words: str) -> str:
    return words[:1].upper() + words[1:]


# process value → (finest typical Ra as made, coarsest typical, source, how it is made)
RA_AS_MADE: dict = {
    "fdm": (10.0, 25.0, SRC_MV, "prints at"),
    "sla": (1.5, None, SRC_XOM, "prints at"),
    "dlp": (1.2, None, SRC_XOM + " (Carbon DLS, a DLP-type process)", "prints at"),
    "sls": (10.0, 20.0, SRC_MV, "prints at"),
    "mjf": (5.0, 10.0, SRC_MV, "prints at"),
    "dmls": (5.0, 15.0, SRC_MV + " (laser powder bed)", "prints at"),
    "slm": (5.0, 15.0, SRC_MV + " (laser powder bed)", "prints at"),
    "ebm": (6.0, 27.0, SRC_EBM, "prints at"),
    "binder_jetting": (6.0, 12.0, SRC_ASSUMED, "sinters at"),
    "ded": (1.6, 6.3, SRC_MH + "; its price already includes finish machining (milling range)", "is finish-machined to"),
    "waam": (1.6, 6.3, SRC_MH + "; its price already includes finish machining (milling range)", "is finish-machined to"),
    "cnc_3axis": (0.8, 6.3, SRC_MH + " (milling)", "mills to"),
    "cnc_5axis": (0.8, 6.3, SRC_MH + " (milling)", "mills to"),
    "cnc_turning": (0.4, 6.3, SRC_MH + " (turning)", "turns to"),
    "wire_edm": (1.6, 3.2, SRC_MH + " (electrical discharge machining)", "cuts to"),
    "injection_molding": (0.05, 1.6, "SPI mold finish grades: the part copies the tool's polish", "molds to"),
    "die_casting": (0.8, 1.6, SRC_MH + " (die casting)", "casts to"),
    "investment_casting": (1.6, 3.2, SRC_MH + " (investment casting)", "casts to"),
    "sand_casting": (12.5, 25.0, SRC_MH + " (sand casting)", "casts to"),
    "forging": (3.2, 12.5, SRC_MH + " (forging)", "forges to"),
    "sheet_metal": (0.8, 3.2, SRC_MH + " (cold-rolled sheet)", "comes as rolled at"),
}
FINE_FINISH_FLOOR_UM = 0.1   # grinding / polishing low end (Machinery's Handbook chart)
MOLD_POLISH_NOTE_BELOW_UM = 0.4


# ─────────────────────────────────────────────────────────────────────────────
# Validation + normalization (the stored shape)
# ─────────────────────────────────────────────────────────────────────────────


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _str_list(specs: dict, key: str, allowed: dict, errors: list) -> list:
    raw = specs.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"{key} must be a list")
        return []
    out: list = []
    for v in raw:
        if not isinstance(v, str) or v not in allowed:
            errors.append(f"unknown {key} value {v!r}; use one of {sorted(allowed)}")
            continue
        if v not in out:
            out.append(v)
    return out


def derived_nadcap(finishes, heat_treatments) -> list:
    """The NADCAP special-process areas the declared finishes and treatments fall under."""
    out: list = []
    for op in list(finishes or []) + list(heat_treatments or []):
        area = _OP_NADCAP.get(op)
        if area and area not in out:
            out.append(area)
    return out


def validate_part_specs(specs) -> None:
    """Raise ``ValueError`` unless ``specs`` is a valid declaration (None allowed).

    Unknown keys and values are rejected (never silently dropped). ``ra_um`` is
    the largest roughness allowed, in µm, from 0.012 to 50; ``ra_unit`` records
    how it was entered (``um`` or ``uin``). ``as_machined`` means no finish, so it
    can't be combined with another finish. NADCAP needs at least one special
    process, named or implied by a declared finish or heat treatment.
    """
    if specs is None:
        return
    if not isinstance(specs, dict):
        raise ValueError("part_specs must be a JSON object")
    errors: list = []
    for key in specs:
        if key not in SPEC_FIELDS:
            errors.append(f"unknown part_specs field '{key}'")
    finishes = _str_list(specs, "finishes", FINISHES, errors)
    heat = _str_list(specs, "heat_treatments", HEAT_TREATMENTS, errors)
    _str_list(specs, "inspection", INSPECTIONS, errors)
    certs = _str_list(specs, "certifications", CERTIFICATIONS, errors)
    nadcap = _str_list(specs, "nadcap_processes", NADCAP_PROCESSES, errors)
    if "as_machined" in finishes and len(finishes) > 1:
        errors.append("as_machined means no finish; remove it or the other finishes")
    ra = specs.get("ra_um")
    if ra is not None:
        if not _is_number(ra):
            errors.append("ra_um must be a number")
        elif not RA_MIN_UM <= ra <= RA_MAX_UM:
            errors.append(f"ra_um must be from {RA_MIN_UM} to {RA_MAX_UM} µm")
    unit = specs.get("ra_unit")
    if unit is not None and unit not in RA_UNITS:
        errors.append("ra_unit must be 'um' or 'uin'")
    _check_tolerance(specs.get("general_tolerance"), errors)
    if "nadcap" in certs and not (nadcap or derived_nadcap(finishes, heat)):
        errors.append("NADCAP needs the special process it covers, for example heat_treating")
    if nadcap and "nadcap" not in certs:
        errors.append("nadcap_processes are only used when NADCAP is a required certification")
    if errors:
        raise ValueError("; ".join(errors))


def _check_tolerance(tol, errors: list) -> None:
    """``{"iso2768": "m"}`` or ``{"plus_minus": 0.1, "unit": "mm"}``; None is no tolerance."""
    if tol is None:
        return
    if not isinstance(tol, dict):
        errors.append("general_tolerance must be an object")
        return
    keys = set(tol)
    if keys == {"iso2768"}:
        if tol["iso2768"] not in ISO_2768_CLASSES:
            errors.append(f"general_tolerance.iso2768 must be one of {sorted(ISO_2768_CLASSES)}")
        return
    if keys in ({"plus_minus"}, {"plus_minus", "unit"}):
        unit = tol.get("unit") or "mm"
        value = tol["plus_minus"]
        if unit not in TOLERANCE_UNITS:
            errors.append("general_tolerance.unit must be 'mm' or 'in'")
        elif not _is_number(value) or value <= 0:
            errors.append("general_tolerance.plus_minus must be a number above 0")
        elif value * (25.4 if unit == "in" else 1.0) > TOLERANCE_MAX_MM:
            errors.append(f"general_tolerance.plus_minus must be at most {TOLERANCE_MAX_MM:g} mm")
        return
    errors.append("general_tolerance is either {iso2768: f|m|c|v} or {plus_minus, unit}")


def tolerance_text(specs: dict) -> Optional[str]:
    """``ISO 2768-m (medium)`` or ``±0.1 mm`` (``±0.005 in (0.127 mm)``), or None."""
    tol = (specs or {}).get("general_tolerance")
    if not isinstance(tol, dict):
        return None
    if tol.get("iso2768") in ISO_2768_CLASSES:
        return f"ISO 2768-{tol['iso2768']} ({ISO_2768_CLASSES[tol['iso2768']]})"
    value = tol.get("plus_minus")
    if not _is_number(value):
        return None
    if tol.get("unit") == "in":
        return f"±{value:g} in ({value * 25.4:.3g} mm)"
    return f"±{value:g} mm"


def normalize_part_specs(specs) -> Optional[dict]:
    """The canonical stored shape, or None when nothing is declared.

    Lists keep their order without duplicates; ``standard`` inspection is the
    default and is dropped; ``ra_unit`` is kept only with an ``ra_um``.
    Validates first (``ValueError``).
    """
    validate_part_specs(specs)
    if not specs:
        return None
    out: dict = {}
    for key in ("finishes", "heat_treatments", "inspection", "certifications", "nadcap_processes"):
        vals = [v for v in dict.fromkeys(specs.get(key) or []) if v != "standard"]
        if vals:
            out[key] = vals
    if specs.get("ra_um") is not None:
        out["ra_um"] = float(specs["ra_um"])
        out["ra_unit"] = specs.get("ra_unit") or "um"
    tol = specs.get("general_tolerance")
    if tol:
        out["general_tolerance"] = (
            {"iso2768": tol["iso2768"]} if "iso2768" in tol
            else {"plus_minus": float(tol["plus_minus"]), "unit": tol.get("unit") or "mm"})
    return out or None


def ra_text(specs: dict) -> Optional[str]:
    """``Ra 0.8 µm`` or ``Ra 32 µin`` as the user entered it (µm shown too)."""
    ra = (specs or {}).get("ra_um")
    if ra is None:
        return None
    if (specs or {}).get("ra_unit") == "uin":
        uin = ra / UM_PER_UIN
        return f"Ra {_g(uin)} µin ({_g(ra)} µm)"
    return f"Ra {_g(ra)} µm"


def _g(v: float) -> str:
    return f"{v:.3g}" if v < 10 else f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


def nadcap_processes(specs: dict) -> list:
    """Named NADCAP areas plus those the declared finishes and treatments imply."""
    if "nadcap" not in ((specs or {}).get("certifications") or []):
        return []
    out = list((specs or {}).get("nadcap_processes") or [])
    for area in derived_nadcap(specs.get("finishes"), specs.get("heat_treatments")):
        if area not in out:
            out.append(area)
    return out


def required_certifications(specs: dict) -> list:
    """What whoever makes the part must hold: ``[{key, label, shop_op}]``.

    ``shop_op`` is the shop-capability key the in-house check reads (``as9100``,
    ``iso9001``, ``itar``, ``nadcap_<area>``).
    """
    out: list = []
    for c in (specs or {}).get("certifications") or []:
        if c == "nadcap":
            for area in nadcap_processes(specs):
                out.append({"key": f"nadcap_{area}",
                            "label": f"NADCAP, {NADCAP_PROCESSES[area]}",
                            "shop_op": f"nadcap_{area}"})
        else:
            out.append({"key": c, "label": CERTIFICATIONS[c], "shop_op": c})
    return out


def spec_summary(specs: dict) -> list:
    """Each declared spec as a short line, in a stable order (for RFQs and exports)."""
    s = specs or {}
    lines: list = []
    fins = [FINISHES[f] for f in s.get("finishes") or []]
    ra = ra_text(s)
    if fins or ra:
        lines.append("Finish: " + ", ".join(fins + ([ra] if ra else [])))
    if s.get("heat_treatments"):
        lines.append("Heat treatment: " + ", ".join(HEAT_TREATMENTS[h] for h in s["heat_treatments"]))
    insp = s.get("inspection") or []
    lines.append("Inspection: " + (", ".join(INSPECTIONS[i] for i in insp) if insp else INSPECTIONS["standard"]))
    certs = required_certifications(s)
    if certs:
        lines.append("Supplier must hold: " + ", ".join(c["label"] for c in certs))
    tol = tolerance_text(s)
    if tol:
        lines.append(f"General tolerance: {tol}")
    return lines


def ops_declared(specs: dict) -> list:
    """Finish, heat-treatment and inspection ops in declared order (as-machined is not an op)."""
    s = specs or {}
    return ([f for f in s.get("finishes") or [] if f != "as_machined"]
            + list(s.get("heat_treatments") or []) + list(s.get("inspection") or []))


# ─────────────────────────────────────────────────────────────────────────────
# Rate-card resolution
# ─────────────────────────────────────────────────────────────────────────────


def op_params(rates, op: str) -> tuple:
    """``(params, provenance_by_field, from_card)`` for one op.

    The typical table is the base; a governed card's ``spec_ops`` overlays it
    (``from_card``: the org's published card stated it); an ad-hoc or shop
    override (``spec.<op>.<field>``) wins and is tagged USER / SHOP.
    """
    base = dict(SPEC_OPS_V0[op])
    data = getattr(rates, "data", {}) or {}
    card = (data.get("spec_ops") or {}).get(op) or {}
    prov: dict = {}
    from_card = False
    for k, v in card.items():
        if k in OVERRIDE_FIELDS and _is_number(v):
            base[k] = float(v)
            from_card = True
    user_keys = getattr(rates, "user_keys", set()) or set()
    shop_keys = getattr(rates, "shop_keys", set()) or set()
    for k in OVERRIDE_FIELDS:
        key = f"spec.{op}.{k}"
        if key in user_keys:
            prov[k] = Provenance.USER
        elif key in shop_keys:
            prov[k] = Provenance.SHOP
    return base, prov, from_card


def apply_override(data: dict, suffix: str, value) -> None:
    """Rate-card override hook for ``spec.<op>.<field>`` (called by rates)."""
    op, _, fld = suffix.partition(".")
    if op not in SPEC_OPS_V0 or fld not in OVERRIDE_FIELDS:
        raise ValueError(f"Unknown spec override 'spec.{suffix}'")
    if fld not in SPEC_OPS_V0[op] and not (fld == "lead_days"):
        raise ValueError(f"'{fld}' doesn't apply to {op}")
    data.setdefault("spec_ops", {}).setdefault(op, {})[fld] = float(value)


# ─────────────────────────────────────────────────────────────────────────────
# Per-route evaluation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SpecLine:
    key: str               # line-item / driver key: "spec_<op>"
    op: str
    label: str
    unit_usd: float        # per part at this quantity
    fixed_usd: float       # the order's one-time share (lot minimum, per-order hours)
    variable_usd: float    # per part, asymptotic
    lead_days: float
    driver: Driver


@dataclass
class RouteSpecs:
    """What the declared specs mean for one (process, material) route."""

    process: str
    material: str
    material_class: str
    family: str
    ops: list = field(default_factory=list)          # ops priced on this route, in order
    shop_ops: list = field(default_factory=list)     # in-house ops the fit check asks for
    findings: list = field(default_factory=list)     # unmet requirements (issue dicts)
    notes: list = field(default_factory=list)        # said plainly, not blocking
    excluded: bool = False

    @property
    def reason(self) -> Optional[str]:
        return self.findings[0]["message"] if self.findings else None


def _finding(code: str, process: str, message: str, fix: str, *,
             measured: float | None = None, required: float | None = None,
             unit: str | None = None) -> dict:
    d = {"code": code, "severity": "error", "message": message, "fix_suggestion": fix,
         "process": process, "scope": "whole_part", "source": "part_specs"}
    if measured is not None:
        d["measured_value"] = float(measured)
    if required is not None:
        d["required_value"] = float(required)
    if unit and (measured is not None or required is not None):
        d["measurement_unit"] = unit
    return d


def _process_words(pv: str) -> str:
    try:
        from src.analysis.process_names import process_phrase
        from src.analysis.models import ProcessType

        return process_phrase(ProcessType(pv))
    except Exception:  # noqa: BLE001 — wording only
        return pv.replace("_", " ")


def evaluate_route(specs: dict, process: str, material_name: str, material_class: str) -> RouteSpecs:
    """Which declared specs this route can deliver, and what it needs to."""
    from src.costing.rates import MATERIAL_FAMILY, process_family
    from src.analysis.models import ProcessType

    try:
        fam = process_family(ProcessType(process))
    except ValueError:
        fam = "unknown"
    cls = MATERIAL_FAMILY.get(material_name) or material_class or "unknown"
    r = RouteSpecs(process=process, material=material_name, material_class=cls, family=fam)
    words = _process_words(process)
    mat_words = material_name or _CLASS_WORDS.get(cls, cls)

    for op in ops_declared(specs):
        allowed = _OP_MATERIALS.get(op, None) if op in _OP_MATERIALS else None
        if op == "hip" and fam not in _AM_METAL_FAMILIES | _CASTING_FAMILIES:
            if cls in _METALS:
                r.notes.append(f"HIP is for printed and cast metal; {words} starts from wrought stock, "
                               f"so HIP isn't added to this route's price.")
                continue
        if op == "stress_relief" and fam == "metal_powder_bed":
            r.notes.append("Stress relief is already in this route's price (every metal powder-bed build gets it).")
            r.shop_ops.append("stress_relief")
            continue
        if allowed is not None and cls not in allowed:
            label = OP_LABELS[op]
            r.findings.append(_finding(
                f"SPEC_{op.upper()}_MATERIAL", process,
                f"{label} needs {_OP_NEEDS[op]}; {words} is priced in {mat_words}.",
                f"Change the material, or take {label.lower()} off the specs."))
            continue
        if op == "solution_age" and cls == "stainless" and "PH" not in (material_name or "").upper():
            r.notes.append(f"Solution treat and age hardens PH grades such as 17-4 PH; {mat_words} "
                           f"isn't one, so check the grade.")
        if op == "quench_temper" and (material_name or "").lower() == "mild steel":
            r.notes.append("Mild steel has too little carbon to harden much by quench and temper; "
                           "the real part would be a grade such as 4140, which ScaleCAD doesn't price yet.")
        r.ops.append(op)
        r.shop_ops.append(op)

    ra = (specs or {}).get("ra_um")
    if ra is not None and process in RA_AS_MADE:
        best, worst, src, verb = RA_AS_MADE[process]
        rng = f"Ra {_g(best)}–{_g(worst)} µm" if worst else f"about Ra {_g(best)} µm"
        if ra >= best:
            if process == "injection_molding" and ra < MOLD_POLISH_NOTE_BELOW_UM:
                r.notes.append(f"Ra {_g(ra)} µm needs a polished tool (SPI A); the tool price doesn't include that polish.")
        elif fam in _MACHINED_FAMILIES and ra >= FINE_FINISH_FLOOR_UM:
            r.ops.append("fine_finish")
            r.shop_ops.append("grinding")
            r.notes.append(f"{_cap(words)} {verb} {rng}; Ra {_g(ra)} µm takes grinding or polishing "
                           f"after, priced as a fine-finish line. Source: {short_source(src)}.")
        else:
            after = ("lapping or superfinishing, which isn't priced"
                     if fam in _MACHINED_FAMILIES else
                     "machining and polishing after, which isn't priced here")
            r.findings.append(_finding(
                "SPEC_RA_UNREACHABLE", process,
                f"{_cap(words)} {verb} {rng}; Ra {_g(ra)} µm needs {after}. "
                f"Source: {short_source(src)}.",
                "Choose a machined route, or allow a rougher finish.",
                measured=best, required=ra, unit="µm Ra"))
            r.findings[-1]["citation"] = {"standard": src}
    r.excluded = bool(r.findings)
    return r


def price_route(rs: RouteSpecs, *, rates, region: str, qty: int, area_cm2: float,
                mass_kg: Optional[float]) -> list:
    """The cost lines for the ops this route delivers, at ``qty`` parts."""
    lines: list = []
    q = max(1, int(qty))
    rl = rates.region_labor(region)
    mgn = 1.0 + float(rates.g("margin"))
    burden = 1.0 + float(rates.g("overhead"))
    labor_rate = float(rates.g("labor_rate"))
    area_m2 = max(0.0, float(area_cm2 or 0.0)) / 1e4
    area_dm2 = area_m2 * 100.0
    markup = (f" × {mgn:g} markup" if mgn != 1.0 else "")
    for op in rs.ops:
        p, prov_by, from_card = op_params(rates, op)
        kind = p["kind"]
        user = any(v == Provenance.USER for v in prov_by.values())
        shop = any(v == Provenance.SHOP for v in prov_by.values())
        prov = Provenance.USER if user else Provenance.SHOP if shop else Provenance.DEFAULT
        origin = ("your figures" if user or shop else
                  "your rate card" if from_card else f"typical: {p['source']}; {TYPICAL}")
        label = OP_LABELS[op] if op != "fine_finish" else "Grind or polish to the Ra you set"
        lead = float(p.get("lead_days", 0.0))
        if kind == "area":
            per_order = p["per_m2_usd"] * area_m2 * q
            order = max(p["lot_usd"], per_order)
            fixed = max(0.0, p["lot_usd"] - per_order) * rl * mgn
            variable = p["per_m2_usd"] * area_m2 * rl * mgn
            unit = order / q * rl * mgn
            how = (f"{label}: the greater of the ${p['lot_usd']:g} lot minimum and "
                   f"${p['per_m2_usd']:g}/m² × {area_m2:.4f} m² × {q} parts = ${order:,.2f} ÷ {q} "
                   f"= ${order / q:.2f}/part × region ×{rl:g}{markup} ({origin})")
        elif kind == "mass":
            if mass_kg is None:
                rs.notes.append(f"{label} isn't priced: the part's weight isn't known (no material density).")
                continue
            per_order = p["per_kg_usd"] * mass_kg * q
            order = max(p["lot_usd"], per_order)
            fixed = max(0.0, p["lot_usd"] - per_order) * rl * mgn
            variable = p["per_kg_usd"] * mass_kg * rl * mgn
            unit = order / q * rl * mgn
            how = (f"{label}: the greater of the ${p['lot_usd']:g} furnace-load minimum and "
                   f"${p['per_kg_usd']:g}/kg × {mass_kg:.3f} kg × {q} parts = ${order:,.2f} ÷ {q} "
                   f"= ${order / q:.2f}/part × region ×{rl:g}{markup} ({origin})")
        else:
            per_part_hr = p.get("hr_per_part", 0.0) + p.get("hr_per_dm2", 0.0) * area_dm2
            hours = p.get("hr_per_order", 0.0) + per_part_hr * q
            rate = labor_rate * rl * mgn * burden
            fixed = p.get("hr_per_order", 0.0) * rate
            variable = per_part_hr * rate
            unit = hours * rate / q
            bits = []
            if p.get("hr_per_order"):
                bits.append(f"{p['hr_per_order']:g} h per order")
            if p.get("hr_per_part"):
                bits.append(f"{p['hr_per_part']:g} h per part")
            if p.get("hr_per_dm2"):
                bits.append(f"{p['hr_per_dm2']:g} h/dm² × {area_dm2:.2f} dm²")
            how = (f"{label}: {' + '.join(bits) or '0 h'} ({_LABOR_WORDS.get(op, 'labor')}) = {hours:.2f} h "
                   f"for {q} parts × ${labor_rate:g}/hr labor (rate card) × region ×{rl:g}{markup}"
                   + (f" × {burden:g} overhead" if burden != 1.0 else "")
                   + f" = ${unit:.2f}/part ({origin})")
            if op == "full_100":
                lead = math.ceil(per_part_hr * q / 8.0) if per_part_hr > 0 else 0.0
        drv = Driver(name=f"spec_{op}_cost", value=round(unit, 4), unit="$",
                     provenance=prov, source=how, error_band_pct=50.0)
        lines.append(SpecLine(key=f"spec_{op}", op=op, label=label, unit_usd=round(unit, 4),
                              fixed_usd=round(fixed, 4), variable_usd=round(variable, 4),
                              lead_days=float(lead), driver=drv))
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# The session the cost engine calls (a handful of lines in estimate.py)
# ─────────────────────────────────────────────────────────────────────────────


class SpecSession:
    """Declared specs bound to one cost run. Build with ``session_for``."""

    def __init__(self, specs: dict, rates, region: str, drivers):
        self.specs = specs
        self.rates = rates
        self.region = region
        self.drivers = drivers
        self._routes: dict = {}

    # -- route view ----------------------------------------------------------
    def route(self, process, material, material_class: str) -> RouteSpecs:
        pv = getattr(process, "value", process)
        name = getattr(material, "name", material) or ""
        key = (pv, name)
        if key not in self._routes:
            self._routes[key] = evaluate_route(self.specs, pv, name, material_class)
        return self._routes[key]

    def _mass(self, material) -> Optional[float]:
        density = getattr(material, "density", None)
        if not _is_number(density) or not hasattr(self.drivers, "mass_kg"):
            return None
        return float(self.drivers.mass_kg(density))

    # -- pricing ---------------------------------------------------------------
    def price(self, est, lt, process, material, material_class: str):
        """``(est, lt)`` with the spec lines added; Σ line items still equals the unit cost."""
        rs = self.route(process, material, material_class)
        lines = price_route(rs, rates=self.rates, region=self.region, qty=est.quantity,
                            area_cm2=getattr(self.drivers, "surface_area_cm2", 0.0),
                            mass_kg=self._mass(material))
        if not lines:
            return est, lt
        items = dict(est.line_items)
        for ln in lines:
            items[ln.key] = ln.unit_usd
        unit = round(sum(items.values()), 4)
        fixed = est.fixed_cost_usd + sum(ln.fixed_usd for ln in lines)
        est2 = replace(est, line_items=items, unit_cost_usd=unit,
                       fixed_cost_usd=round(fixed, 4),
                       variable_cost_usd=round(unit - fixed / max(1, est.quantity), 4),
                       drivers=list(est.drivers) + [ln.driver for ln in lines])
        est2.assert_sums()
        if lt is None:
            return est2, None
        days = sum(ln.lead_days for ln in lines)
        if days <= 0:
            return est2, lt
        comps = dict(lt.components)
        comps["specs"] = float(days)
        mid = sum(comps.values())
        lt2 = replace(lt, components=comps, mid_days=round(mid, 1),
                      low_days=round(mid * 0.7, 1), high_days=round(mid * 1.3, 1))
        return est2, lt2

    # -- machine fit -------------------------------------------------------------
    def part_req(self, preq, process, material, material_class: str):
        """The route's PartReq with the in-house ops, certifications and unmet specs."""
        from src.costing.makeability import FitFailure

        rs = self.route(process, material, material_class)
        fails = tuple(FitFailure("spec", f["code"], f.get("required_value", "meets the spec"),
                                 f.get("measured_value", "doesn't"), f["message"])
                      for f in rs.findings)
        return replace(preq, spec_ops=tuple(dict.fromkeys(rs.shop_ops)),
                       certifications=tuple(c["shop_op"] for c in required_certifications(self.specs)),
                       spec_failures=fails)

    # -- serialized estimates ----------------------------------------------------------
    def annotate(self, estimates: list, material_class: str) -> set:
        """Flag each serialized estimate; returns the process values the specs rule out."""
        out: set = set()
        for e in estimates:
            rs = self.route(e.get("process"), e.get("material"), material_class)
            if rs.findings:
                e["spec_excluded"] = True
                e["spec_exclusion_reason"] = rs.reason
                e["spec_findings"] = [dict(f) for f in rs.findings]
                out.add(e.get("process"))
            if rs.notes:
                e["spec_notes"] = list(dict.fromkeys(rs.notes))
            lines = [k for k in (e.get("line_items") or {}) if k.startswith("spec_")]
            if lines:
                e["spec_lines"] = lines
        return out

    def note(self, excluded: set) -> Optional[str]:
        if not excluded:
            return None
        return ("the declared specs rule out " + ", ".join(_process_words(p) for p in sorted(excluded))
                + "; decision computed over the routes that can meet them")

    def block(self, estimates: list) -> dict:
        """The report's ``specs`` block: what was declared and what it requires."""
        return {
            "declared": copy.deepcopy(self.specs),
            "summary": spec_summary(self.specs),
            "ra_text": ra_text(self.specs),
            "certifications": required_certifications(self.specs),
            "nadcap_processes": nadcap_processes(self.specs),
            "ops": [{"op": op, "label": OP_LABELS[op]} for op in ops_declared(self.specs)],
            "excluded_processes": sorted({e["process"] for e in estimates if e.get("spec_excluded")}),
            "provenance": "user",
            "note": ("Each finish, heat treatment and inspection adds a cost line and lead time "
                     "from your rate card, or a typical value with its source. Certifications "
                     "carry no price: they are what whoever makes the part must hold."),
        }


def session_for(options, rates, region: str, drivers) -> Optional[SpecSession]:
    """A SpecSession when the options carry declared specs, else None (no-op)."""
    specs = getattr(options, "part_specs", None)
    if not specs:
        return None
    try:
        specs = normalize_part_specs(specs)
    except ValueError:
        return None
    if not specs:
        return None
    return SpecSession(specs, rates, region, drivers)


def stored_specs(context_row: Any) -> Optional[dict]:
    """A part context row's declared specs the engine prices with, normalized, or None.
    The general tolerance is the buyer's statement for the supplier, not priced, so it
    stays out (a record isn't out of date when only the tolerance changes)."""
    raw = getattr(context_row, "part_specs", None) if context_row is not None else None
    if not raw:
        return None
    try:
        specs = normalize_part_specs(raw)
    except ValueError:
        return None
    priced = {k: v for k, v in (specs or {}).items() if k not in NOT_PRICED_FIELDS}
    return priced or None
