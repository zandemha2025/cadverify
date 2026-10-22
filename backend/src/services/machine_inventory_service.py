"""Machine-inventory service — org-owned machine capability registry (spec §3–§4).

The data/CRUD half of the verification-thesis crux: an org declares the machines
it OWNS with real capability fields, so a later pure matcher (Phase B,
``src.costing.makeability``) can answer "can this part be made, on WHICH of THEIR
machines, or exactly what machine spec would close the gap." This module is the
deliberate sibling of the shipped governed-library services
(``manifest_service`` for the CSV/keyset/error discipline, ``rate_library_service``
for the pure-validation-then-thin-adapter shape).

HONESTY RAILS (non-negotiable, spec §2):
  * Capabilities are USER-declared → provenance ``"user"``, NEVER measured. A
    machine's envelope/rate/material qualification is the org's declaration.
  * Malformed inputs are REPORTED (per-field / per-line), never coerced. A bad
    process, a negative scalar, a non-integer IT grade, an unknown material, or a
    ``capital_frac`` outside [0,1] is a reported error, not a silently-fixed value.
  * No inventory declared → the platform is byte-identical (this is purely
    additive). ``load_org_inventory`` returns ``[]`` for an empty/absent org.
  * Org-scoped throughout: every query filters by ``org_id`` — one org's machines
    never leak into another's list, hydration, or shop-capabilities.

The pure ``MachineCap`` / ``ShopCaps`` capability types are the LOCKED Phase-B
contract; the real definitions live in ``src.costing.makeability`` (written in
parallel). Until that module lands here we fall back to local dataclasses of the
EXACT same shape so this phase is self-contained and testable; the orchestrator
reconciles the two at integration.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError
from ulid import ULID

from src.analysis.models import ProcessType
from src.costing.rates import ADDITIVE, BINDER_JET_FAMILY, METAL_POWDER_BED
from src.db.models import MachineInstance, ShopCapabilities
from src.profiles.database import MACHINES, MATERIALS, get_material_by_name, get_materials_for_process
from src.profiles.models import MAKER_DESCRIBED, MAKER_SPEC
# Reuse the EXACT material-class vocabulary the ground-truth / manifest importers
# validate against — a machine can never smuggle in a material the cost engine
# would later reject.
from src.services.groundtruth_service import KNOWN_MATERIAL_CLASSES

logger = logging.getLogger("cadverify.machine_inventory")


# ── LOCKED Phase-B capability types (real import is src.costing.makeability) ──
try:  # pragma: no cover - exercised at integration when makeability.py lands
    from src.costing.makeability import MachineCap, ShopCaps  # type: ignore
except Exception:  # noqa: BLE001 - module not written yet in this worktree

    @dataclass(frozen=True)
    class MachineCap:  # type: ignore[no-redef]
        """DB-free capability view of one owned machine (Phase-B contract).

        Field set + order is the LOCKED contract shared with
        ``src.costing.makeability``. Keep in exact sync.
        """

        process: str
        name: Optional[str]
        count: int
        max_workpiece_kg: Optional[float]
        hourly_rate_usd: Optional[float]
        capital_frac: Optional[float]
        materials: tuple = ()
        material_thickness_map: dict = field(default_factory=dict)
        capabilities: dict = field(default_factory=dict)

    @dataclass(frozen=True)
    class ShopCaps:  # type: ignore[no-redef]
        """DB-free view of an org's shop-level secondary-op set (Phase-B contract)."""

        ops: dict = field(default_factory=dict)


# ── valid process set (ProcessType.value) ────────────────────────────────────
_VALID_PROCESSES = frozenset(p.value for p in ProcessType)

# ── capability-field schema (per gate type; all USER-declared) ────────────────
# scalar kinds
_POS = "pos"        # a number strictly > 0
_NONNEG = "nonneg"  # a number >= 0
_BOOL = "bool"
_STR = "str"        # a non-empty string

# key -> scalar kind. Special-cased keys (IT grade / axes / enums) are handled
# separately in ``_validate_capabilities`` so their precise messages are clean.
_CAP_SPEC: dict[str, str] = {
    # Envelope (mm, > 0) — mill/AM/EDM travels, sheet bed, turning swing/length,
    # casting flask, molding platen.
    "x": _POS, "y": _POS, "z": _POS,
    "bed_x": _POS, "bed_y": _POS,
    "swing_dia": _POS, "between_centers": _POS, "spindle_bore": _POS,
    "flask_x": _POS, "flask_y": _POS, "flask_z": _POS,
    "platen_x": _POS, "platen_y": _POS, "tie_bar_gap": _POS, "daylight": _POS,
    # Force / energy.
    "spindle_power_kw": _POS, "spindle_taper": _STR, "max_rpm": _POS,
    "laser_power_kw": _POS, "tonnage_t": _POS, "max_bend_length_mm": _POS,
    "clamp_tonnage_t": _POS, "shot_capacity_g": _POS, "max_injection_bar": _POS,
    "press_tonnage_t": _POS, "furnace_capacity_kg": _POS, "max_pour_kg": _POS,
    "max_cut_thickness_mm": _POS,
    # Reach / access.
    "min_tool_dia_mm": _POS, "max_tool_reach_ratio": _POS,
    "live_tooling": _BOOL, "y_axis": _BOOL, "sub_spindle": _BOOL, "bar_feed": _BOOL,
    # Resolution / precision.
    "positioning_accuracy_um": _POS, "repeatability_um": _POS,
    "surface_finish_ra_um": _POS, "min_layer_um": _POS, "min_wall_mm": _POS,
    "min_feature_mm": _POS, "max_taper_deg": _POS,
    # Material special gates.
    "conductive_required": _BOOL,
    # Printer details (additive only; see _PRINTER_KEY_PROCESSES). Layer heights
    # are µm like min_layer_um; the chamber limit is °C.
    "nozzle_dia_mm": _POS, "max_layer_um": _POS, "max_chamber_c": _POS,
}
_MOTION_MODES = frozenset({"positional_3plus2", "simultaneous_5"})
_CHAMBER_TYPES = frozenset({"hot", "cold"})
_ENCLOSURES = frozenset({"none", "enclosed", "heated"})

# ── printer details: which additive methods each key describes ───────────────
# From the costing families (``src.costing.rates``): an extrusion nozzle and a
# build enclosure belong to filament printers; a layer-height range to every
# layer-by-layer printer (polymer additive, metal powder bed, binder jetting —
# not bead-deposition DED/WAAM); stocked feedstock to filament and resin
# printers (powder printers declare what they run in ``materials``). A key on
# any other method is reported, never stored. ``min_layer_um`` predates these
# and stays accepted on every machine.
_FILAMENT = frozenset({ProcessType.FDM.value})
_LAYERED = frozenset(p.value for p in (ADDITIVE | METAL_POWDER_BED | BINDER_JET_FAMILY))
_FEEDSTOCK = frozenset({ProcessType.FDM.value, ProcessType.SLA.value, ProcessType.DLP.value})
_PRINTER_KEY_PROCESSES: dict[str, frozenset] = {
    "nozzle_dia_mm": _FILAMENT,
    "enclosure": _FILAMENT,
    "max_chamber_c": _FILAMENT,
    "max_layer_um": _LAYERED,
    "stocked_materials": _FEEDSTOCK,
}


def _is_number(v: Any) -> bool:
    try:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    except OverflowError:
        return False


def _validate_capabilities(caps: Any, errors: list[str], process: Any = None) -> None:
    """Validate the per-family ``capabilities`` dict; append precise errors.

    Every recognised key is type/sign-checked; an UNKNOWN key is a reported error
    (never silently ignored — a typo'd capability must not vanish). An empty dict
    is valid: a machine may legitimately declare only some gates (the missing
    ones read ``unknown`` downstream, never a fabricated pass). Printer details
    are checked against ``process`` (a key the method can't carry is reported)
    and against each other (layer range order; a chamber limit needs a heated
    enclosure).
    """
    if caps is None:
        return
    if not isinstance(caps, dict):
        errors.append("capabilities must be a JSON object")
        return
    for key, allowed in _PRINTER_KEY_PROCESSES.items():
        if key in caps and isinstance(process, str) and process in _VALID_PROCESSES and process not in allowed:
            errors.append(
                f"capability '{key}' applies to {', '.join(sorted(allowed))} machines only (got {process})"
            )
    lo, hi = caps.get("min_layer_um"), caps.get("max_layer_um")
    if _is_number(lo) and _is_number(hi) and hi < lo:
        errors.append(f"max_layer_um ({hi}) must be >= min_layer_um ({lo})")
    if "max_chamber_c" in caps and caps.get("enclosure") != "heated":
        errors.append("max_chamber_c needs enclosure 'heated'")
    for key, val in caps.items():
        if key == MAKER_SPEC_KEY:
            _validate_maker_marker(val, errors)
            continue
        if key == "enclosure":
            if not isinstance(val, str) or val not in _ENCLOSURES:
                errors.append(f"enclosure must be one of {sorted(_ENCLOSURES)}")
            continue
        if key == "stocked_materials":
            _validate_material_list(val, errors, field_name="stocked_materials",
                                    process=process if isinstance(process, str) else None)
            continue
        if key == "achievable_it_grade":
            if isinstance(val, bool) or not isinstance(val, int):
                errors.append("achievable_it_grade must be an integer IT grade")
            elif not (0 <= val <= 18):
                errors.append("achievable_it_grade must be an IT grade in 0–18")
            continue
        if key == "axes":
            if isinstance(val, bool) or val not in (3, 4, 5):
                errors.append("axes must be one of 3, 4, 5")
            continue
        if key == "motion_mode":
            if not isinstance(val, str) or val not in _MOTION_MODES:
                errors.append(
                    f"motion_mode must be one of {sorted(_MOTION_MODES)}"
                )
            continue
        if key == "chamber_type":
            if not isinstance(val, str) or val not in _CHAMBER_TYPES:
                errors.append(
                    f"chamber_type must be one of {sorted(_CHAMBER_TYPES)}"
                )
            continue
        kind = _CAP_SPEC.get(key)
        if kind is None:
            errors.append(f"unknown capability '{key}'")
            continue
        if kind in (_POS, _NONNEG):
            if not _is_number(val):
                errors.append(f"capability '{key}' must be a finite number")
            elif kind == _POS and val <= 0:
                errors.append(f"capability '{key}' must be > 0 (got {val})")
            elif kind == _NONNEG and val < 0:
                errors.append(f"capability '{key}' must be >= 0 (got {val})")
        elif kind == _BOOL:
            if not isinstance(val, bool):
                errors.append(f"capability '{key}' must be a boolean")
        elif kind == _STR:
            if not isinstance(val, str) or not val.strip():
                errors.append(f"capability '{key}' must be a non-empty string")


# Common alloy/polymer shorthands → the registry name they unambiguously mean.
# The add-machine form's own placeholder suggests bare designations (``6061``,
# ``316L``, ``PP``) that are NOT registry names, so a shop owner's first natural
# inventory entry used to 400. Each entry here maps a real, unambiguous shorthand
# to a real registry material — no shorthand is added for an ambiguous stem
# (e.g. bare ``PA12`` / ``17-4`` / ``Ti-6Al-4V`` each match several registry
# entries), so we never GUESS which material the user meant. Keys are lower-case;
# lookup is case-insensitive.
_MATERIAL_ALIASES: dict[str, str] = {
    "6061": "6061-T6 Aluminum",
    "7075": "7075-T6 Aluminum",
    "316l": "SS316L",
    "ss316l": "SS316L",
    "304": "304 Stainless",
    "ss304": "304 Stainless",
    "pp": "PP (Molded)",
    "4130": "AISI 4130",
    "4140": "AISI 4140",
}

# Material names as a machine's own method uses them. The same word means a
# different registry material on a different machine: a filament printer's
# "Nylon" is the registry's Nylon (PA6), a powder printer's is PA12 or PA11.
# Product-line names makers sell a polymer under ("PLA Basic", "PETG HF") are
# that polymer; a filled grade maps only to the filled registry entry, never to
# its base. Keys are compared case-, space- and punctuation-insensitively
# (``_mkey``). ``None`` = a real material with no registry equivalent on that
# method: refused with that said, never swapped for a look-alike.
_METHOD_NAMES: dict[str, dict[str, tuple[str, ...]]] = {
    "fdm": {
        "PLA": ("PLA Basic", "PLA Matte", "PLA Silk", "PLA Silk+", "PLA+", "PLA Plus",
                "PLA Pro", "PLA Tough", "PLA Tough+", "PLA Lite", "PLA HF", "PLA High Flow",
                "PLA High Speed", "PLA HS", "PLA Translucent", "PLA Metal", "PLA Marble",
                "PLA Sparkle", "PLA Galaxy", "PLA Glow", "PLA Basic Gradient"),
        "PETG": ("PETG HF", "PETG Basic", "PETG Translucent", "PETG+", "PETG Pro",
                 "PETG HS", "PETG High Flow", "PET-G"),
        "ABS": ("ABS Basic", "ABS+", "ABS-M30"),
        "TPU 95A": ("TPU", "TPU 95A HF", "TPU for AMS", "TPU 95"),
        "Nylon (PA6)": ("Nylon", "PA", "PA6", "Nylon 6", "Nylon PA6"),
        "CF-Nylon": ("PA-CF", "PA6-CF", "PA12-CF", "PAHT-CF", "Nylon-CF", "CF Nylon",
                     "Nylon 12CF", "Carbon Fiber Nylon", "Carbon Fibre Nylon"),
        "ULTEM 9085": ("ULTEM", "PEI 9085"),
    },
    "sls": {
        "PA12 (Nylon 12)": ("PA12", "Nylon 12", "PA 2200"),
        "PA11": ("Nylon 11",),
        "Glass-filled PA12": ("PA-GF", "PA12-GF", "PA12 GF", "PA 3200 GF"),
        "TPU (SLS)": ("TPU",),
    },
    "mjf": {
        "PA12 (Nylon 12)": ("PA12", "Nylon 12"),
        "PA11": ("Nylon 11",),
        "PP (MJF)": ("PP", "Polypropylene"),
    },
    "sla": {
        "Standard Resin": ("Standard", "Grey Resin", "Clear Resin", "Black Resin", "White Resin"),
        "Tough Resin": ("Tough", "Tough 1500", "Tough 2000"),
        "Flexible Resin": ("Flexible", "Flexible 80A"),
        "Castable Resin": ("Castable", "Castable Wax"),
        "Dental Model Resin": ("Dental Model",),
    },
    "dlp": {
        "Standard Resin": ("Standard",),
        "Tough Resin": ("Tough",),
        "Flexible Resin": ("Flexible",),
        "Castable Resin": ("Castable",),
        "Dental Model Resin": ("Dental Model",),
    },
}
# A name that is several registry materials on that method: asked, not guessed.
_METHOD_AMBIGUOUS: dict[tuple[str, str], tuple[str, ...]] = {
    ("sls", "Nylon"): ("PA12 (Nylon 12)", "PA11"),
    ("sls", "PA"): ("PA12 (Nylon 12)", "PA11"),
    ("mjf", "Nylon"): ("PA12 (Nylon 12)", "PA11"),
    ("mjf", "PA"): ("PA12 (Nylon 12)", "PA11"),
}
# Polymers that are one registry material on any machine.
_ANY_METHOD_NAMES: dict[str, tuple[str, ...]] = {
    "PC (Polycarbonate)": ("PC", "Polycarbonate"),
    "Delrin (POM)": ("Delrin", "POM", "Acetal"),
}

_METHOD_LABEL = {
    "fdm": "a filament printer (FDM)", "sla": "a resin printer (SLA)",
    "dlp": "a resin printer (DLP)", "sls": "a powder printer (SLS)",
    "mjf": "a powder printer (MJF)", "cnc_3axis": "a 3-axis mill",
    "cnc_5axis": "a 5-axis mill", "cnc_turning": "a lathe", "wire_edm": "a wire EDM",
    "dmls": "a metal powder printer (DMLS)", "slm": "a metal powder printer (SLM)",
    "ebm": "a metal powder printer (EBM)", "binder_jetting": "a binder-jet printer",
    "sheet_metal": "a sheet-metal line", "injection_molding": "an injection molding machine",
}
_POLYMER_METHODS = frozenset({"fdm", "sla", "dlp", "sls", "mjf", "injection_molding"})


def _mkey(name: str) -> str:
    """Compare material names ignoring case, spaces and punctuation ("TPU-95A" = "tpu 95a")."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _method_table(process: Optional[str]) -> dict[str, Optional[str]]:
    """``{_mkey(name): registry name | None}`` for one method: its own names,
    the catalog's vendor names for it, and names that mean one material anywhere."""
    table: dict[str, Optional[str]] = {}
    for target, names in _ANY_METHOD_NAMES.items():
        for n in names:
            table[_mkey(n)] = target
    if isinstance(process, str):
        for (proc, name), target in _CATALOG_MATERIALS.items():
            if proc == process:
                table[_mkey(name)] = target
        for target, names in _METHOD_NAMES.get(process, {}).items():
            for n in names:
                table[_mkey(n)] = target
    return table


def _resolve_material(name: str, process: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """``(canonical stored form, None)`` or ``(None, problem)`` for one declared material.

    Order: a material CLASS → the machine's method names (``_METHOD_NAMES``, the
    catalog's vendor names) → a common metal/polymer SHORTHAND → an exact
    registry NAME (case-insensitive) → the same ignoring spaces and punctuation.
    An ambiguous or unknown name resolves to nothing and the problem names it.
    """
    stripped = name.strip()
    low = stripped.lower()
    if low in KNOWN_MATERIAL_CLASSES:
        return low, None
    key = _mkey(stripped)
    label = _METHOD_LABEL.get(process or "", "this method")
    for (proc, amb), options in _METHOD_AMBIGUOUS.items():
        if proc == process and _mkey(amb) == key:
            return None, (f"'{stripped}' could be {' or '.join(options)} on {label}. "
                          f"Name which one.")
    table = _method_table(process)
    if key in table:
        target = table[key]
        if target is None:
            return None, (f"unknown material '{stripped}' for {label}: ScaleCAD has no "
                          f"price for it on this method. Leave it out, or use "
                          f"{_known_for(process)}.")
        return target, None
    alias = _MATERIAL_ALIASES.get(low)
    if alias is not None:
        return alias, None
    prof = get_material_by_name(stripped)
    if prof is not None:
        return prof.name, None
    compact = [m.name for m in MATERIALS if _mkey(m.name) == key]
    if len(compact) == 1:
        return compact[0], None
    return None, _unknown_text(stripped, process, label)


def _method_materials(process: Optional[str]) -> list[str]:
    try:
        pt = ProcessType(process) if process else None
    except ValueError:
        pt = None
    return [m.name for m in get_materials_for_process(pt)] if pt is not None else []


def _known_for(process: Optional[str]) -> str:
    names = _method_materials(process)[:8]
    cls = "the class polymer" if process in _POLYMER_METHODS else "a class (aluminum, steel, stainless, titanium)"
    return (", ".join(names) + f", or {cls}") if names else cls


def _unknown_text(name: str, process: Optional[str], label: str) -> str:
    """One sentence: the entry, and the closest names ScaleCAD knows on that method."""
    import difflib

    pool = _method_materials(process) or [m.name for m in MATERIALS]
    key = _mkey(name)
    closest = [n for n in pool if _mkey(n) and key.startswith(_mkey(n))]
    by_low = {n.lower(): n for n in pool}
    closest += [by_low[c] for c in difflib.get_close_matches(name.lower(), list(by_low), n=3, cutoff=0.5)
                if by_low[c] not in closest]
    if closest:
        return f"unknown material '{name}' for {label}. Closest names ScaleCAD knows: {', '.join(closest[:3])}."
    return f"unknown material '{name}' for {label}. Known there: {_known_for(process)}."


def _canonical_material(name: str, process: Optional[str] = None) -> Optional[str]:
    """Resolve a declared material to its canonical stored form, or ``None`` if
    it is ambiguous or unknown on this method (see ``_resolve_material``)."""
    return _resolve_material(name, process)[0]


def _validate_material_list(materials: Any, errors: list[str], *, field_name: str,
                            process: Optional[str] = None) -> None:
    """Each entry must resolve on this machine's method (``_resolve_material``)."""
    if materials is None:
        return
    if not isinstance(materials, (list, tuple)):
        errors.append(f"{field_name} must be a list")
        return
    label = "material" if field_name == "materials" else field_name
    for m in materials:
        if not isinstance(m, str) or not m.strip():
            errors.append(f"{label} entries must be non-empty strings (got {m!r})")
            continue
        canon, problem = _resolve_material(m, process)
        if canon is not None:
            continue
        if field_name != "materials" and problem and problem.startswith("unknown material"):
            problem = f"{field_name} has {problem}"
        errors.append(problem or f"unknown material '{m.strip()}'")


def _validate_materials(materials: Any, errors: list[str], process: Optional[str] = None) -> None:
    """The machine's qualified materials (see ``_validate_material_list``)."""
    _validate_material_list(materials, errors, field_name="materials", process=process)


def _canonical_thickness_key(key: str, process: Optional[str] = None) -> Optional[str]:
    """Canonical stored form of a ``material_thickness_map`` key, or ``None``.

    The engine looks a part up by its registry material name, then its class,
    then ``@<class>`` (``makeability.fit_machine``), so a key must resolve the
    same way a declared material does; ``@`` is kept only on a material class.
    """
    text = key.strip()
    prefix = "@" if text.startswith("@") else ""
    canon = _canonical_material(text[len(prefix):], process)
    if canon is None or (prefix and canon not in KNOWN_MATERIAL_CLASSES):
        return None
    return prefix + canon


def _validate_thickness_map(tmap: Any, errors: list[str], process: Optional[str] = None) -> None:
    if tmap is None:
        return
    if not isinstance(tmap, dict):
        errors.append("material_thickness_map must be a JSON object")
        return
    seen: dict[str, str] = {}
    for k, v in tmap.items():
        if not isinstance(k, str) or not k.strip():
            errors.append("material_thickness_map keys must be material names")
        else:
            canon = _canonical_thickness_key(k, process)
            if canon is None:
                errors.append(
                    f"material_thickness_map has unknown material '{k.strip()}' "
                    f"(a material, or @ and a class such as @aluminum)"
                )
            elif canon in seen:
                errors.append(
                    f"material_thickness_map lists '{canon}' twice "
                    f"('{seen[canon]}' and '{k}')"
                )
            else:
                seen[canon] = k
        if not _is_number(v) or v <= 0:
            errors.append(
                f"material_thickness_map['{k}'] must be a positive number and finite"
            )


def validate_machine(fields: dict) -> None:
    """Raise ``ValueError`` (message = all problems, ``; ``-joined) unless
    ``fields`` is a structurally-valid, engine-consumable machine declaration.

    Validates: ``process`` ∈ ProcessType; ``count`` a positive int;
    ``max_workpiece_kg`` > 0; ``hourly_rate_usd`` >= 0; ``capital_frac`` ∈ [0,1];
    each ``capabilities`` scalar positive / typed per gate; ``achievable_it_grade``
    an int IT grade; printer details only on the methods they describe, with
    ``stocked_materials`` against the same vocabulary as ``materials``;
    ``materials`` against the material DB / class vocabulary;
    ``material_thickness_map`` a {name: positive} map. An unknown top-level field
    is reported like an unknown capability key, never silently dropped. Nothing
    is coerced — every violation is reported.
    """
    errors: list[str] = []

    for key in fields:
        if key == "provenance":
            if fields[key] not in _ACCEPTED_PROVENANCE:
                errors.append(
                    "provenance must be 'user' or 'catalog_template' "
                    "(a saved machine is always a USER declaration)"
                )
        elif key in _DISPLAY_ONLY_FIELDS:
            continue  # server-computed labels a catalog template carries; never stored
        elif key not in _MUTABLE_FIELDS:
            errors.append(f"unknown field '{key}'")

    process = fields.get("process")
    if not process or not isinstance(process, str):
        errors.append("process is required")
    elif process not in _VALID_PROCESSES:
        errors.append(f"unknown process '{process}'")

    count = fields.get("count")
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int):
            errors.append("count must be an integer")
        elif count <= 0:
            errors.append("count must be > 0")
        elif count > 2_147_483_647:
            errors.append("count must be at most 2147483647")

    mwk = fields.get("max_workpiece_kg")
    if mwk is not None:
        if not _is_number(mwk) or mwk <= 0:
            errors.append("max_workpiece_kg must be a positive number and finite")

    rate = fields.get("hourly_rate_usd")
    if rate is not None:
        if not _is_number(rate) or rate < 0:
            errors.append("hourly_rate_usd must be >= 0 and finite")

    cf = fields.get("capital_frac")
    if cf is not None:
        if not _is_number(cf) or not (0.0 <= cf <= 1.0):
            errors.append("capital_frac must be in [0,1] and finite")

    proc = process if isinstance(process, str) else None
    _validate_capabilities(fields.get("capabilities"), errors, fields.get("process"))
    _validate_materials(fields.get("materials"), errors, proc)
    _validate_thickness_map(fields.get("material_thickness_map"), errors, proc)

    if errors:
        raise ValueError("; ".join(errors))


# ── mutable field set (write/serialize never drift) ──────────────────────────
_MUTABLE_FIELDS = (
    "name",
    "process",
    "count",
    "max_workpiece_kg",
    "hourly_rate_usd",
    "capital_frac",
    "capabilities",
    "materials",
    "material_thickness_map",
    "notes",
)

# ``provenance`` is the one non-stored field a write may carry: a catalog
# template marks itself ``catalog_template`` and can be submitted as-is. It is
# never persisted — a saved machine is always serialized as ``user``.
_ACCEPTED_PROVENANCE = (None, "user", "catalog_template")  # tuple: values may be unhashable
# A catalog template also carries its maker spec and per-field labels for the
# form to show. They are recomputed by the server, so a submitted copy is ignored.
_DISPLAY_ONLY_FIELDS = frozenset({"spec", "field_provenance"})


def _normalize(fields: dict) -> dict:
    """Apply the non-fabricating defaults: ``count`` → 1, ``capabilities`` → {}.

    Nothing else is invented; absent optional fields stay ``None``.
    """
    out = {k: fields.get(k) for k in _MUTABLE_FIELDS}
    if out.get("count") is None:
        out["count"] = 1
    if out.get("capabilities") is None:
        out["capabilities"] = {}
    proc = out.get("process") if isinstance(out.get("process"), str) else None

    def canon_list(items):
        # Each name as its registry material on this method, once ("PLA Basic",
        # "PLA Matte" are both PLA).
        seen: list = []
        for m in items:
            c = (_canonical_material(m, proc) or m) if isinstance(m, str) else m
            if c not in seen:
                seen.append(c)
        return seen

    # Stocked filament/resin is stored under the same canonical names as materials.
    caps = out.get("capabilities")
    if isinstance(caps, dict) and isinstance(caps.get("stocked_materials"), (list, tuple)):
        caps = dict(caps)
        caps["stocked_materials"] = canon_list(caps["stocked_materials"])
        out["capabilities"] = caps
    # Canonicalize accepted materials (shorthand → registry name) so the stored
    # value is the real material the form advertised, not the bare shorthand.
    mats = out.get("materials")
    if isinstance(mats, (list, tuple)):
        out["materials"] = canon_list(mats)
    # Same for thickness-map keys, so the engine's registry-name / class lookup
    # actually finds the limit the user declared under a shorthand.
    tmap = out.get("material_thickness_map")
    if isinstance(tmap, dict):
        out["material_thickness_map"] = {
            (_canonical_thickness_key(k, proc) or k) if isinstance(k, str) else k: v
            for k, v in tmap.items()
        }
    # The maker-spec label is the server's to set: it names only the fields
    # whose saved value is still exactly the catalog machine's published value.
    caps = out.get("capabilities")
    if isinstance(caps, dict) and MAKER_SPEC_KEY in caps:
        marker = maker_marker(caps.get(MAKER_SPEC_KEY), out)
        caps = {k: v for k, v in caps.items() if k != MAKER_SPEC_KEY}
        if marker:
            caps[MAKER_SPEC_KEY] = marker
        out["capabilities"] = caps
    return out


# ── CSV bulk-import contract (mirrors manifest_service.parse_manifest_csv) ────
MACHINE_REQUIRED_COLUMNS = ("process",)
MACHINE_OPTIONAL_COLUMNS = (
    "name",
    "count",
    "max_workpiece_kg",
    "hourly_rate_usd",
    "capital_frac",
    "materials",  # pipe-separated list, e.g. "Ti6Al4V|Inconel 718|steel"
    "material_thickness_map",  # JSON object
    "capabilities",  # JSON object of the per-family scalars
    "notes",
)
MACHINE_HEADER = ",".join(MACHINE_REQUIRED_COLUMNS + MACHINE_OPTIONAL_COLUMNS)
_FLOAT_COLUMNS = ("max_workpiece_kg", "hourly_rate_usd", "capital_frac")


def _example_row() -> str:
    """One illustrative data row for the /import/template body.

    Built with csv.writer so the row matches MACHINE_HEADER's column order
    exactly and embedded JSON quotes are CSV-escaped — the template's own
    example must survive a round-trip through /machine-inventory/import.
    """
    caps = json.dumps({"x": 762, "y": 406, "z": 508, "axes": 3,
                       "achievable_it_grade": 9})
    row = {
        "process": "cnc_3axis",
        "name": "Haas VF-2 #1",
        "count": "1",
        "max_workpiece_kg": "200",
        "hourly_rate_usd": "75",
        "capital_frac": "0.4",
        "materials": "304 Stainless|steel",
        "material_thickness_map": "",
        "capabilities": caps,
        "notes": "shop floor A",
    }
    buf = io.StringIO()
    csv.writer(buf).writerow(
        [row[c] for c in MACHINE_REQUIRED_COLUMNS + MACHINE_OPTIONAL_COLUMNS]
    )
    return buf.getvalue().rstrip("\r\n")


def _clean(v) -> str:
    return (v or "").strip()


def parse_machine_csv(text: str):
    """Parse a machine-inventory CSV into ``(rows, errors)`` — STRICT and HONEST.

    ``rows`` are validated machine payloads (ready for ``import_machines``);
    ``errors`` is a list of ``{"line", "reason"}``. Mirrors
    ``manifest_service.parse_manifest_csv``: BOM-tolerant header, blank line
    skipped (never reported), a malformed HEADER yields ``([], [one error])``
    (empty file → ``line: 0``; missing ``process`` → ``line: 1``), and a malformed
    ROW is reported and SKIPPED — never coerced, never aborts the file.

    Per-line error classes: missing/invalid ``process``; non-numeric
    ``count``/float columns; invalid ``capabilities``/``material_thickness_map``
    JSON; and every ``validate_machine`` violation (negative scalar, bad IT grade,
    unknown material, ``capital_frac`` out of range, unknown capability, …).
    """
    rows: list = []
    errors: list = []

    if not text or not text.strip():
        return rows, [{"line": 0, "reason": "empty CSV (no header, no rows)"}]

    try:
        reader = iter(list(csv.reader(io.StringIO(text))))
    except csv.Error:
        return rows, [{"line": 0, "reason": "CSV could not be read. Check quoting and field sizes."}]
    try:
        header = next(reader)
    except StopIteration:
        return rows, [{"line": 0, "reason": "empty CSV (no header, no rows)"}]

    if header and header[0].startswith("﻿"):
        header[0] = header[0][1:]
    cols = [_clean(h).lower() for h in header]
    col_index = {name: i for i, name in enumerate(cols)}

    missing = [c for c in MACHINE_REQUIRED_COLUMNS if c not in col_index]
    if missing:
        return rows, [{
            "line": 1,
            "reason": (
                f"header missing required column(s): {', '.join(missing)}. "
                f"Expected header: {MACHINE_HEADER}"
            ),
        }]

    def cell(record: list, name: str) -> str:
        i = col_index.get(name)
        if i is None or i >= len(record):
            return ""
        return _clean(record[i])

    for offset, record in enumerate(reader):
        line = offset + 2  # header is line 1; first data row is line 2
        if not any(_clean(c) for c in record):
            continue

        row_errs: list[str] = []
        payload: dict[str, Any] = {
            "name": cell(record, "name") or None,
            "process": cell(record, "process") or None,
            "notes": cell(record, "notes") or None,
        }

        raw_count = cell(record, "count")
        if raw_count:
            try:
                payload["count"] = int(raw_count)
            except ValueError:
                row_errs.append(f"count not an integer ('{raw_count}')")
        else:
            payload["count"] = None

        for name in _FLOAT_COLUMNS:
            raw = cell(record, name)
            if not raw:
                payload[name] = None
                continue
            try:
                payload[name] = float(raw)
            except ValueError:
                row_errs.append(f"{name} not a number ('{raw}')")

        raw_mats = cell(record, "materials")
        payload["materials"] = (
            [m.strip() for m in raw_mats.split("|") if m.strip()]
            if raw_mats
            else None
        )

        for jname in ("capabilities", "material_thickness_map"):
            raw = cell(record, jname)
            if not raw:
                payload[jname] = None if jname == "material_thickness_map" else {}
                continue
            try:
                payload[jname] = json.loads(raw)
            except (ValueError, TypeError):
                row_errs.append(f"{jname} is not valid JSON")

        if not row_errs:
            try:
                validate_machine(payload)
            except ValueError as exc:
                row_errs.append(str(exc))

        if row_errs:
            errors.append({"line": line, "reason": "; ".join(row_errs)})
            continue
        rows.append(_normalize(payload))

    return rows, errors


# ── import (bulk INSERT; machines have no natural business key → append) ──────
async def import_machines(
    session: AsyncSession,
    org_id: str,
    created_by: Optional[int],
    rows: list,
) -> dict:
    """Persist parsed machine rows (bulk INSERT — append, not upsert).

    Unlike a manifest (keyed by ``part_id``), a machine has no natural business
    key (two "Haas VF-2 #3" are two machines), so each parsed row is a NEW
    instance. Per-row failures are captured as errors, never crash the batch.
    Org-scoped; does NOT commit — the caller owns the txn.

    Returns ``{"imported", "skipped", "total", "errors"}``.
    """
    imported = 0
    errors: list = []
    for idx, payload in enumerate(rows):
        try:
            async with session.begin_nested():
                row = MachineInstance(
                    org_id=org_id,
                    created_by=created_by,
                    **_normalize(payload),
                )
                session.add(row)
                await session.flush()
            imported += 1
        except DBAPIError as exc:
            if exc.connection_invalidated or str(getattr(exc.orig, "sqlstate", ""))[:2] not in {"22", "23"}:
                raise  # Availability/schema failures must abort the request.
            errors.append({"line": None, "index": idx, "reason": "The row could not be saved. Check its values and identifiers."})

    return {
        "imported": imported,
        "skipped": len(rows) - imported,
        "total": len(rows),
        "errors": errors,
    }


# ── CRUD (org-scoped) ─────────────────────────────────────────────────────────
async def get_machine(
    session: AsyncSession, org_id: str, ulid: str
) -> Optional[MachineInstance]:
    """A single owned machine by its public ULID, scoped to the org (or None)."""
    if not org_id:
        return None
    return (
        await session.execute(
            select(MachineInstance).where(
                MachineInstance.org_id == org_id,
                MachineInstance.ulid == ulid,
            )
        )
    ).scalars().first()


async def create_machine(
    session: AsyncSession,
    org_id: str,
    fields: dict,
    created_by: Optional[int] = None,
) -> MachineInstance:
    """Validate + insert one owned machine. ``ValueError`` on a malformed field."""
    validate_machine(fields)
    row = MachineInstance(
        org_id=org_id,
        created_by=created_by,
        **_normalize(fields),
    )
    session.add(row)
    await session.flush()
    return row


async def update_machine(
    session: AsyncSession,
    org_id: str,
    ulid: str,
    fields: dict,
) -> Optional[MachineInstance]:
    """Patch a machine's mutable fields (org-scoped). Only supplied keys change;
    the merged result is re-validated so a partial edit can't create an invalid
    machine. Returns ``None`` when no such machine exists in the org.
    """
    row = await get_machine(session, org_id, ulid)
    if row is None:
        return None
    merged = {k: getattr(row, k) for k in _MUTABLE_FIELDS}
    for k in _MUTABLE_FIELDS:
        if k in fields:
            merged[k] = fields[k]
    # Unknown / marker keys ride along so validate_machine reports them (they are
    # never stored — _normalize keeps only the mutable set).
    to_validate = {**merged, **{k: v for k, v in fields.items() if k not in _MUTABLE_FIELDS}}
    keep_tmap = "material_thickness_map" not in fields
    if keep_tmap:
        # A map stored before its keys were checked may name a non-registry
        # material. It is validated whenever it is written; re-checking it here
        # would block an unrelated edit (the form never shows this field).
        to_validate["material_thickness_map"] = None
    validate_machine(to_validate)
    merged = _normalize(merged)
    if keep_tmap:
        merged["material_thickness_map"] = row.material_thickness_map
    for k in _MUTABLE_FIELDS:
        setattr(row, k, merged[k])
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def delete_machine(session: AsyncSession, org_id: str, ulid: str) -> bool:
    """Delete one owned machine (org-scoped). Returns True iff a row was removed."""
    row = await get_machine(session, org_id, ulid)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── keyset-paginated list (order ulid ASC — unique, monotonic per org) ────────
MACHINE_LIST_MAX = 500


def _encode_cursor(ulid: str) -> str:
    return base64.urlsafe_b64encode(ulid.encode()).decode()


def _decode_cursor(cursor: str) -> str:
    return base64.urlsafe_b64decode(cursor.encode()).decode()


async def list_machines(
    session: AsyncSession,
    org_id: str,
    *,
    cursor: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """One keyset-paginated page of the org's owned machines, ``ulid`` ASC.

    Returns ``{"machines": [...], "next_cursor": str | None}``. ``org_id`` falsy →
    an empty page (never a cross-org read). ``limit`` bounded at ``MACHINE_LIST_MAX``.
    """
    if not org_id:
        return {"machines": [], "next_cursor": None}
    limit = max(1, min(int(limit), MACHINE_LIST_MAX))

    q = select(MachineInstance).where(MachineInstance.org_id == org_id)
    if cursor:
        q = q.where(MachineInstance.ulid > _decode_cursor(cursor))
    q = q.order_by(MachineInstance.ulid.asc()).limit(limit + 1)

    fetched = list((await session.execute(q)).scalars().all())
    has_more = len(fetched) > limit
    page = fetched[:limit]
    next_cursor = _encode_cursor(page[-1].ulid) if (has_more and page) else None
    return {
        "machines": [machine_to_public(r) for r in page],
        "next_cursor": next_cursor,
    }


# ── hydration to the pure Phase-B capability types (LOCKED contract) ──────────
async def load_org_inventory(session: AsyncSession, org_id: str) -> list:
    """Hydrate the org's machines to ``list[MachineCap]`` for the pure matcher.

    Mirrors ``load_org_ground_truth``: a DB-free snapshot the Phase-B engine
    consumes. Empty / absent org → ``[]`` (byte-identical when the feature is
    unused). Every ``MachineCap`` is built to the EXACT locked field set/order.
    """
    if not org_id:
        return []
    machines = (
        await session.execute(
            select(MachineInstance).where(MachineInstance.org_id == org_id)
        )
    ).scalars().all()
    return [
        MachineCap(
            process=m.process,
            name=m.name,
            count=int(m.count) if m.count is not None else 1,
            max_workpiece_kg=m.max_workpiece_kg,
            hourly_rate_usd=m.hourly_rate_usd,
            capital_frac=m.capital_frac,
            materials=tuple(m.materials or ()),
            material_thickness_map=dict(m.material_thickness_map or {}),
            capabilities=_engine_capabilities(m),
        )
        for m in machines
    ]


def _engine_capabilities(m: MachineInstance) -> dict:
    """The stored capabilities, with the maker-spec label re-checked against the
    current catalog so a verdict never cites a value the maker no longer gives."""
    caps = dict(m.capabilities or {})
    if MAKER_SPEC_KEY in caps:
        marker = maker_marker(caps.pop(MAKER_SPEC_KEY), {
            "process": m.process, "max_workpiece_kg": m.max_workpiece_kg,
            "materials": m.materials,
        })
        if marker:
            caps[MAKER_SPEC_KEY] = marker
    return caps


async def load_shop_caps(session: AsyncSession, org_id: str):
    """Hydrate the org's shop-level secondary ops to ``ShopCaps`` (or empty)."""
    row = await get_shop_capabilities(session, org_id) if org_id else None
    # Normalized on read too, so a row saved before names were canonicalized
    # (e.g. ``{"HIP": true}``) still satisfies the engine's ``hip``.
    return ShopCaps(ops=_normalize_shop_ops(row.ops) if row is not None else {})


# ── shop-level secondary-op capabilities (org-scoped, one row per org) ────────
async def get_shop_capabilities(
    session: AsyncSession, org_id: str
) -> Optional[ShopCapabilities]:
    if not org_id:
        return None
    return (
        await session.execute(
            select(ShopCapabilities).where(ShopCapabilities.org_id == org_id)
        )
    ).scalars().first()


def _canonical_op(name: str) -> str:
    """Op names match case- and separator-insensitively: the engine asks for
    ``hip`` / ``stress_relief`` / ``sinter`` / ``grinding``, so ``"HIP"`` or
    ``"Stress Relief"`` must name the same op rather than silently miss."""
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _normalize_shop_ops(ops: Any) -> dict:
    """``ops`` with canonical op names. On a (legacy) collision the entry already
    spelled canonically wins; otherwise the first spelling is kept."""
    out: dict = {}
    for key, val in (ops or {}).items():
        canon = _canonical_op(key) if isinstance(key, str) else key
        if canon not in out or key == canon:
            out[canon] = val
    return out


def validate_shop_ops(ops: Any) -> None:
    """Raise ``ValueError`` unless ``ops`` is a valid secondary-op map.

    ``{op: True | {size/temp limits}}``: each key a non-empty string; each value a
    bool OR a dict of numeric size/temp limits. Two keys naming the same op
    (``"HIP"`` and ``"hip"``) are reported. Malformed → reported, never coerced.
    """
    if ops is None:
        return
    if not isinstance(ops, dict):
        raise ValueError("shop capabilities 'ops' must be a JSON object")
    errors: list[str] = []
    seen: dict[str, str] = {}
    for key, val in ops.items():
        if not isinstance(key, str) or not key.strip():
            errors.append("op names must be non-empty strings")
            continue
        canon = _canonical_op(key)
        if canon in seen:
            errors.append(f"op '{key}' duplicates '{seen[canon]}' (both name '{canon}')")
        seen.setdefault(canon, key)
        if isinstance(val, bool):
            continue
        if isinstance(val, dict):
            for lk, lv in val.items():
                if not _is_number(lv) or lv <= 0:
                    errors.append(
                        f"op '{key}' limit '{lk}' must be a positive number and finite"
                    )
            continue
        errors.append(f"op '{key}' must be a boolean or a limits object")
    if errors:
        raise ValueError("; ".join(errors))


async def upsert_shop_capabilities(
    session: AsyncSession,
    org_id: str,
    ops: dict,
    created_by: Optional[int] = None,
) -> ShopCapabilities:
    """Insert or update the org's single shop-capabilities row (validated; op
    names stored canonically)."""
    validate_shop_ops(ops)
    ops = _normalize_shop_ops(ops)
    row = await get_shop_capabilities(session, org_id)
    if row is None:
        row = ShopCapabilities(org_id=org_id, ops=ops or {}, created_by=created_by)
        session.add(row)
    else:
        row.ops = ops or {}
        row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


# ── maker-spec labels (catalog values a saved machine still carries) ─────────
# A machine added from the catalog keeps the maker's published workpiece load and
# materials. They count like the shop's own values (the fit can say yes), but the
# API labels them so the form can say where they came from. The label lives in
# ``capabilities["maker_spec"]`` as ``{"catalog": <catalog name>, "fields": [...]}``
# and is always recomputed here: a field is labelled only while its value is
# still exactly the catalog's, so an edit makes it the shop's own declaration.
MAKER_SPEC_KEY = "maker_spec"
MAKER_SPEC_FIELDS = ("max_workpiece_kg", "materials")


def _catalog_profile(name: Any):
    if not isinstance(name, str):
        return None
    low = name.strip().lower()
    return next((m for m in MACHINES if m.name.lower() == low), None)


def _validate_maker_marker(val: Any, errors: list[str]) -> None:
    if (not isinstance(val, dict) or not isinstance(val.get("catalog"), str)
            or not val["catalog"].strip()
            or set(val) - {"catalog", "fields"}
            or not isinstance(val.get("fields", []), list)):
        errors.append(
            "capability 'maker_spec' must be {\"catalog\": <catalog machine name>} "
            "(set by the catalog prefill)"
        )


def _same_kg(a: Any, b: Optional[float]) -> bool:
    return b is not None and _is_number(a) and abs(float(a) - b) <= 1e-9 * max(1.0, abs(b))


def maker_marker(claim: Any, values: dict) -> Optional[dict]:
    """The label for the fields of ``values`` that still equal a catalog machine's
    maker spec, or ``None``. ``claim`` names the catalog machine; a different
    method, an unknown name or edited values earn no label."""
    if not isinstance(claim, dict):
        return None
    prof = _catalog_profile(claim.get("catalog"))
    if prof is None or prof.spec is None or values.get("process") != prof.process_type.value:
        return None
    fields: list[str] = []
    if _same_kg(values.get("max_workpiece_kg"), prof.spec.max_workpiece_kg):
        fields.append("max_workpiece_kg")
    mats, _ = _catalog_materials(prof)
    have = values.get("materials")
    if mats and isinstance(have, (list, tuple)) and len(have) == len(mats) and set(have) == set(mats):
        fields.append("materials")
    return {"catalog": prof.name, "fields": fields} if fields else None


def field_provenance(values: dict) -> dict:
    """``{field: label}`` for the values that came from a maker's spec.

    A field not listed is the shop's own declaration. Each label names the
    source (``maker_spec``: the maker publishes it; ``maker_described``:
    materials read conservatively from what the maker says the machine is for),
    the catalog machine, the maker's page and what it says.
    """
    caps = values.get("capabilities")
    marker = maker_marker(caps.get(MAKER_SPEC_KEY), values) if isinstance(caps, dict) else None
    if not marker:
        return {}
    prof = _catalog_profile(marker["catalog"])
    spec = prof.spec
    out: dict = {}
    if "max_workpiece_kg" in marker["fields"]:
        out["max_workpiece_kg"] = {
            "source": MAKER_SPEC, "catalog": prof.name, "maker": prof.manufacturer,
            "url": spec.source_url, "note": spec.kg_note, "checked": spec.checked,
        }
    if "materials" in marker["fields"]:
        out["materials"] = {
            "source": spec.materials_basis or MAKER_SPEC, "catalog": prof.name,
            "maker": prof.manufacturer, "url": spec.materials_url or spec.source_url,
            "note": spec.materials_note, "checked": spec.checked,
        }
    return out


def _spec_view(prof) -> Optional[dict]:
    """What the maker publishes for a catalog machine (GET /catalog ``spec``)."""
    spec = prof.spec
    if spec is None:
        return None
    return {
        "source_url": spec.source_url,
        "max_workpiece_kg": spec.max_workpiece_kg,
        "max_workpiece_kg_note": spec.kg_note,
        "materials_basis": spec.materials_basis,
        "materials_url": spec.materials_url or spec.source_url,
        "materials_note": spec.materials_note,
        "checked": spec.checked,
    }


# ── "add from catalog" template pre-fill (static MachineProfile reference) ────
def add_from_catalog(profile_name: str) -> dict:
    """Return an editable machine payload pre-filled from the static
    ``MachineProfile`` reference DB (spec §3.1 seed convenience).

    The catalog is the TEMPLATE; the org instance is the DECLARATION — the caller
    edits then submits. ``ValueError`` if no such profile. Envelope/resolution/axes
    are seeded from the profile; ``provenance`` marks it a catalog template so the
    UI never badges an unedited prefill as a real declaration.
    """
    prof = next(
        (m for m in MACHINES if m.name.lower() == (profile_name or "").lower()),
        None,
    )
    if prof is None:
        raise ValueError(f"no catalog machine profile named '{profile_name}'")
    return _profile_to_payload(prof)


# The static catalog names materials the way vendors do ("PA12", "Tough",
# "ABS-M30"); the validator accepts only registry vocabulary, so an UNEDITED
# prefill used to 400 on 11 of 19 entries. Each entry maps (process, catalog
# name) to the registry material the catalog machine is actually qualified for.
# ``None`` = no registry equivalent: left out of the prefill and named in its
# notes, never swapped for a look-alike or widened to a class. Names not listed
# here must already be registry vocabulary (a test enforces this).
_CATALOG_MATERIALS: dict[tuple[str, str], Optional[str]] = {
    ("fdm", "Nylon"): "Nylon (PA6)",
    ("fdm", "TPU"): "TPU 95A",
    ("fdm", "Nylon 12CF"): "CF-Nylon",
    ("fdm", "ABS-M30"): "ABS",
    ("fdm", "PA6/66"): None,           # copolymer; the registry has PA6 only
    ("sla", "Standard"): "Standard Resin",
    ("sla", "Tough"): "Tough Resin",
    ("sla", "Flexible"): "Flexible Resin",
    ("sla", "Castable"): "Castable Resin",
    ("dlp", "Standard"): "Standard Resin",
    ("dlp", "Castable"): "Castable Resin",
    ("dlp", "ABS-like"): None,
    ("dlp", "RPU 70"): None,
    ("dlp", "EPU 41"): None,
    ("dlp", "CE 221"): None,
    ("sls", "PA12"): "PA12 (Nylon 12)",
    ("sls", "PA-GF"): "Glass-filled PA12",
    ("sls", "TPU"): "TPU (SLS)",
    ("sls", "PP"): None,               # the registry's PP is MJF/molding only
    ("mjf", "PA12"): "PA12 (Nylon 12)",
    ("mjf", "PP"): "PP (MJF)",
    ("mjf", "TPU"): None,              # the registry's powder TPU is SLS-only
    ("binder_jetting", "17-4 PH"): "17-4 PH SS",
    # Sand molds and cores, not a part material: stored as "sand", so a sand
    # printer reads "prints sand molds and cores", never "materials not declared".
    ("binder_jetting", "Sand"): "sand",
}


def _catalog_materials(prof) -> tuple[list[str], list[str]]:
    """``(registry_materials, not_prefilled)`` for one catalog profile."""
    proc = prof.process_type.value
    resolved: list[str] = []
    skipped: list[str] = []
    for name in prof.materials or ():
        key = (proc, name)
        reg = _CATALOG_MATERIALS[key] if key in _CATALOG_MATERIALS else _canonical_material(name, proc)
        if reg is None:
            skipped.append(name)
        elif reg not in resolved:
            resolved.append(reg)
    return resolved, skipped


def _profile_to_payload(prof) -> dict:
    caps: dict[str, Any] = {}
    proc = prof.process_type.value
    bv = prof.build_volume
    if bv and len(bv) == 3:
        if proc == ProcessType.CNC_TURNING.value:
            # A lathe's catalog volume is (Ø, Ø, length). Declare it as the
            # swing/between-centers envelope the engine, API and turning form use.
            caps["swing_dia"] = float(min(bv[0], bv[1]))
            caps["between_centers"] = float(bv[2])
        else:
            caps["x"], caps["y"], caps["z"] = float(bv[0]), float(bv[1]), float(bv[2])
    if prof.min_layer_height:
        caps["min_layer_um"] = round(prof.min_layer_height * 1000.0, 3)
    if prof.max_layer_height and proc in _LAYERED:
        caps["max_layer_um"] = round(prof.max_layer_height * 1000.0, 3)
    if prof.resolution_xy:
        caps["min_feature_mm"] = float(prof.resolution_xy)
    materials, not_prefilled = _catalog_materials(prof)
    spec = prof.spec
    notes = f"Prefilled from catalog '{prof.name}' ({prof.manufacturer})."
    if spec is not None:
        from_maker = [label for label, v in (("Workpiece weight", spec.max_workpiece_kg),
                                             ("materials", materials)) if v]
        if from_maker:
            notes += (f" {' and '.join(from_maker).capitalize()} from the maker's spec;"
                      " edit anything your machine differs on.")
        if spec.max_workpiece_kg is None:
            notes += f" {spec.kg_note}"
    else:
        notes += " EDIT to your machine's real specs before saving."
    if not_prefilled:
        notes += (
            " Not prefilled (no registry material): "
            + ", ".join(not_prefilled) + "."
        )
    if proc == ProcessType.CNC_5AXIS.value:
        caps["axes"] = 5
        caps["motion_mode"] = "simultaneous_5"
    elif proc == ProcessType.CNC_3AXIS.value:
        caps["axes"] = 3
    if spec is not None:
        caps[MAKER_SPEC_KEY] = {"catalog": prof.name}
    payload = {
        "name": prof.name,
        "process": proc,
        "count": 1,
        "max_workpiece_kg": spec.max_workpiece_kg if spec is not None else None,
        "hourly_rate_usd": None,
        "capital_frac": None,
        "capabilities": caps,
        "materials": materials or None,
        "material_thickness_map": None,
        "notes": notes,
        # Honesty: an unedited catalog prefill is a TEMPLATE, not a declaration.
        "provenance": "catalog_template",
    }
    # The server's own label for the maker's values (the saved machine keeps it
    # while they're unedited), and what the maker publishes, page included.
    marker = maker_marker(caps.get(MAKER_SPEC_KEY), payload)
    if marker:
        caps[MAKER_SPEC_KEY] = marker
    else:
        caps.pop(MAKER_SPEC_KEY, None)
    payload["field_provenance"] = field_provenance(payload)
    payload["spec"] = _spec_view(prof)
    return payload


def catalog_options() -> list[dict]:
    """Every static ``MachineProfile`` as an editable prefill payload (GET /catalog)."""
    return [_profile_to_payload(m) for m in MACHINES]


# ── serialization ─────────────────────────────────────────────────────────────
def machine_to_public(r: MachineInstance) -> dict:
    """The API view of a stored owned machine (ULID as the opaque public id).

    ``provenance`` is always ``"user"`` — a declared capability is a USER assertion,
    never a measurement of the machine.
    """
    return {
        "id": r.ulid,
        "name": r.name,
        "process": r.process,
        "count": r.count,
        "max_workpiece_kg": r.max_workpiece_kg,
        "hourly_rate_usd": r.hourly_rate_usd,
        "capital_frac": r.capital_frac,
        "capabilities": r.capabilities or {},
        "materials": r.materials,
        "material_thickness_map": r.material_thickness_map,
        "notes": r.notes,
        "provenance": "user",
        # Values still exactly as the maker publishes them (from the catalog),
        # labelled with the maker's page. Absent field = the shop's own value.
        "field_provenance": field_provenance({
            "process": r.process,
            "max_workpiece_kg": r.max_workpiece_kg,
            "materials": r.materials,
            "capabilities": r.capabilities or {},
        }),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def serialize_shop_capabilities(row: Optional[ShopCapabilities]) -> dict:
    """The API view of an org's shop-level secondary ops (empty when unset)."""
    return {
        "ops": (row.ops or {}) if row is not None else {},
        "provenance": "user",
        "updated_at": (
            row.updated_at.isoformat() if (row and row.updated_at) else None
        ),
    }
