"""One material, many names: which registry names are the same material.

The registry holds some materials twice under different names: a printing
powder row next to a wrought bar row (Ti6Al4V and Ti-6Al-4V Grade 5), a molding
pellet next to a printing powder (PP (Molded), PP (MJF), PP (Polypropylene)).
A machine declared for one of them is qualified for the material, whichever
row a route is priced in. ``material_identity`` maps any of those names (and the
aliases the material files list) to one key; two names are the same material
when their keys are equal. Comparison ignores case, spaces and punctuation.

This says nothing about price or form: a route is still priced in its own row.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Rows that are the same alloy or polymer under different registry names.
_SAME: tuple[tuple[str, ...], ...] = (
    ("Ti-6Al-4V", "Ti6Al4V", "Ti6Al4V (Wrought)", "Ti-6Al-4V Grade 5", "Ti64", "TC4"),
    ("PP", "PP (Polypropylene)", "PP (MJF)", "PP (Molded)", "Polypropylene"),
    ("CoCr", "CoCr ASTM F75", "CoCrMo"),
    ("ABS", "ABS (Molded)"),
    ("304 Stainless", "304 SS (Sheet)", "304", "SS304"),
    ("17-4 PH", "17-4 PH SS", "17-4 PH (Cast)", "17-4PH"),
    ("PA12 (Nylon 12)", "PA12", "Nylon 12", "PA2200"),
    ("SS316L", "316L"),
)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    table: dict[str, str] = {}
    for group in _SAME:
        ident = _key(group[0])
        for n in group:
            table[_key(n)] = ident
    # The material files' own aliases name the same material too.
    try:
        from src.profiles.loader import _YAML_MATERIALS_RAW_ALIASES
    except ImportError:  # pragma: no cover - loader without alias export
        _YAML_MATERIALS_RAW_ALIASES = {}
    for name, aliases in _YAML_MATERIALS_RAW_ALIASES.items():
        ident = table.get(_key(name), _key(name))
        table.setdefault(_key(name), ident)
        for a in aliases:
            table.setdefault(_key(a), ident)
    return table


def material_identity(name: str) -> str:
    """The key shared by every name of one material (its own compact name when it has no other)."""
    k = _key(name)
    return _table().get(k, k)


def same_material(a: str, b: str) -> bool:
    return bool(a) and bool(b) and material_identity(a) == material_identity(b)
