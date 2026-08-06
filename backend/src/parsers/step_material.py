"""No-kernel STEP material scan (spec: honest "material read from CAD" slice).

This deliberately does NOT use the AP242/OCP kernel path (``step_ap242_parser``,
not installable in this container). It is a plain TEXT scan of the raw
ISO-10303-21 STEP bytes for a declared material annotation — the conventional
places CAD authoring tools (SolidWorks, Inventor, NX, Creo, ...) stash a
material name when they export STEP. It never resolves the full entity graph
(no B-rep/PMI extraction), so it can miss materials expressed only as a
cross-referenced representation-item chain; when it finds nothing, it returns
None rather than guessing.

Two public functions:
  * ``scan_step_material`` — returns the raw declared material string, or None.
  * ``map_material_to_class`` — maps that raw string to one of the engine's
    costed material classes (``rates.MATERIAL_FAMILY`` values), or None if it
    can't be confidently mapped.
  * ``material_class_from_step`` — the two composed.

Both are pure, defensive, and never raise: a malformed/binary/empty file simply
yields None, same as "no material found".
"""

from __future__ import annotations

import re

# ── translator / software noise to reject as a "material" ──────────────────
# STEP files carry the exporting tool's name and boilerplate in HEADER (and
# sometimes echoed into PRODUCT names in DATA); none of that is a material.
_SOFTWARE_NOISE = (
    "step translator", "step ap203", "step ap214", "step ap242",
    "open cascade", "opencascade", "solidworks", "catia", "autodesk",
    "inventor", "pro/engineer", "creo", "siemens nx", " nx ", "freecad",
    "fusion 360", "sketchup", "rhinoceros", "unknown",
)

_GENERIC_JUNK = {"", "$", "*", "none", "n/a", "material", "material name",
                  "material designation"}


def _is_noise(candidate: str) -> bool:
    c = candidate.strip()
    if not c:
        return True
    lc = c.lower()
    if lc in _GENERIC_JUNK:
        return True
    return any(tag in lc for tag in _SOFTWARE_NOISE)


# ── carrier patterns, tried in priority order ───────────────────────────────
# 1) An explicit MATERIAL_DESIGNATION-style entity: the first quoted argument
#    is taken directly as the material name.
_RE_MATERIAL_DESIGNATION = re.compile(
    r"\b\w*MATERIAL_DESIGNATION\w*\s*\(\s*'([^']*)'", re.IGNORECASE
)

# 2) A quoted 'material' / 'material name' / 'material designation' keyword
#    immediately followed by a quoted value — this is how most CAD exporters
#    stash a material through DESCRIPTIVE_REPRESENTATION_ITEM('material', '<name>')
#    or a PROPERTY_DEFINITION('material', '<name>', ...).
_RE_KEYWORD_VALUE = re.compile(
    r"'\s*material(?:\s*[_ ]\s*(?:name|designation))?\s*'\s*,\s*'([^']+)'",
    re.IGNORECASE,
)

# 3) Generic fallback: any DATA-section line that mentions the MATERIAL token
#    somewhere, carrying at least one quoted string that isn't noise/keyword.
_RE_MATERIAL_TOKEN = re.compile(r"\bMATERIAL\b", re.IGNORECASE)
_RE_QUOTED = re.compile(r"'([^']*)'")


def scan_step_material(data: bytes) -> "str | None":
    """No-kernel scan of ISO-10303-21 STEP text for a declared material name.

    Returns the raw material string or None. Never raises."""
    if not data:
        return None
    try:
        text = data.decode("latin-1", errors="ignore")
    except Exception:
        return None

    try:
        # Carrier 1: explicit *MATERIAL_DESIGNATION* entity.
        m = _RE_MATERIAL_DESIGNATION.search(text)
        if m and not _is_noise(m.group(1)):
            return m.group(1).strip()

        # Carrier 2: quoted 'material'-ish keyword -> quoted value (covers
        # DESCRIPTIVE_REPRESENTATION_ITEM and PROPERTY_DEFINITION shapes).
        for m in _RE_KEYWORD_VALUE.finditer(text):
            candidate = m.group(1)
            if not _is_noise(candidate):
                return candidate.strip()

        # Carrier 3 (fallback): a line that mentions MATERIAL and carries a
        # quoted value that isn't the keyword itself or translator noise.
        for line in text.splitlines():
            if not _RE_MATERIAL_TOKEN.search(line):
                continue
            quoted = _RE_QUOTED.findall(line)
            for candidate in reversed(quoted):
                if not _is_noise(candidate):
                    return candidate.strip()
    except Exception:
        return None

    return None


# ── raw material string -> engine material_class ────────────────────────────
def _build_exact_lookup() -> dict:
    from src.costing.rates import MATERIAL_FAMILY

    return {name.lower(): cls for name, cls in MATERIAL_FAMILY.items()}


# Alias layer: (compiled pattern, class). Order matters — more distinctive/
# specific alloy families are checked before generic ones so e.g. "Ti-6Al-4V"
# resolves to titanium (checked before the "al" aluminum alias could fire).
# Only classes that actually exist as MATERIAL_FAMILY values are ever returned
# (enforced again at lookup time against the live table, not hardcoded here).
_ALIAS_PATTERNS = (
    (re.compile(r"\b(inconel|incoloy|hastelloy|monel|nickel)\b", re.IGNORECASE), "nickel"),
    (re.compile(r"\b(ti|titanium)\b", re.IGNORECASE), "titanium"),
    (re.compile(r"\b(ss|stainless|304|316|17-4|duplex|13cr)\b", re.IGNORECASE), "stainless"),
    (re.compile(r"\b(steel|carbon steel|4140|4130|1018|a105|a182)\b", re.IGNORECASE), "steel"),
    (re.compile(r"\b(al|alu|aluminum|aluminium|6061|7075|5052|a356|alsi)\b", re.IGNORECASE), "aluminum"),
    (re.compile(r"\b(brass|bronze|copper)\b", re.IGNORECASE), "copper"),
    (re.compile(r"\b(zinc|zamak)\b", re.IGNORECASE), "zinc"),
    (re.compile(r"\b(cocr|cobalt)\b", re.IGNORECASE), "cobalt"),
    (re.compile(
        r"\b(pp|abs|nylon|pa|pa\d+|polymer|plastic|peek|petg|pla|tpu|delrin|pom|pc)\b",
        re.IGNORECASE,
    ), "polymer"),
)


def map_material_to_class(name: "str | None") -> "str | None":
    """Map a raw CAD material string to a material_class using MATERIAL_FAMILY
    (inverted) plus a small alias layer. Returns None if not confidently mapped."""
    if not name:
        return None
    n = name.strip()
    if not n:
        return None

    try:
        from src.costing.rates import MATERIAL_FAMILY

        available = set(MATERIAL_FAMILY.values())

        exact = _build_exact_lookup().get(n.lower())
        if exact and exact in available:
            return exact

        for pattern, cls in _ALIAS_PATTERNS:
            if cls in available and pattern.search(n):
                return cls
    except Exception:
        return None

    return None


def material_class_from_step(data: bytes) -> "str | None":
    """Scan STEP bytes for a declared material and map it to a material_class.

    Returns None on no material found, an unmappable material, or any error —
    this is a best-effort honesty add-on, never a hard requirement."""
    name = scan_step_material(data)
    return map_material_to_class(name) if name else None
