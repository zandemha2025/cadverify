"""Material grades: which engine material a parts list's words name.

A parts list names a material the way a buyer writes it ("6061-T6 aluminum",
"4140", "Delrin", "17-4 PH", "Inconel 718"). The cost engine prices named
materials (``costing.rates.MATERIAL_FAMILY``), several of which are the same
grade in another form ("304 Stainless" bar and "304 SS (Sheet)"). A *grade key*
is what both share: the words of a parts list and an engine material name map to
the same key when they are the same grade.

``grade_of(text)`` reads a key from free text; ``grade_key(name)`` is the same
read of an engine material's own name. ``family_of_grade`` says which priced
family a grade belongs to (the engine's own table decides where it can).

Pure: no I/O.
"""
from __future__ import annotations

import re
from typing import Optional

# (key, family, pattern), most specific first: "super duplex" before "duplex",
# "glass-filled PA12" before "PA12". Digits are matched with digit look-arounds,
# not \b, so "SS316L" and "Ti6Al4V" read as their grade.
_D = r"(?<!\d)"
_E = r"(?!\d)"
_GRADES: tuple[tuple[str, str, re.Pattern], ...] = tuple(
    (key, family, re.compile(pattern, re.I))
    for key, family, pattern in (
        # stainless
        ("super_duplex_2507", "stainless", rf"super\s*duplex|{_D}2507{_E}"),
        ("duplex_2205", "stainless", rf"duplex|{_D}2205{_E}"),
        ("super_13cr", "stainless", r"super\s*13\s*cr"),
        ("13cr", "stainless", rf"{_D}13\s*cr"),
        ("f6nm", "stainless", r"f6nm"),
        ("17-4ph", "stainless", rf"{_D}17-?4{_E}"),
        ("15-5ph", "stainless", rf"{_D}15-?5{_E}"),
        ("316l", "stainless", rf"{_D}316l?{_E}"),
        ("304", "stainless", rf"{_D}304l?{_E}"),
        ("303", "stainless", rf"{_D}303{_E}"),
        ("410", "stainless", rf"{_D}410{_E}"),
        ("420", "stainless", rf"{_D}420{_E}"),
        ("440c", "stainless", rf"{_D}440c?{_E}"),
        # nickel
        ("inconel_718", "nickel", r"(inconel|alloy|\bin)\s*-?\s*718"),
        ("inconel_625", "nickel", r"(inconel|alloy|\bin)\s*-?\s*625"),
        ("incoloy_825", "nickel", r"(incoloy|alloy)\s*-?\s*825"),
        ("hastelloy_c276", "nickel", r"hastelloy|c-?276"),
        ("monel", "nickel", r"monel"),
        # titanium
        ("ti6al4v", "titanium", r"ti-?6al-?4v|ti\s*6-4|ti64|grade\s*5|\bgr\.?\s*5\b"),
        # cobalt
        ("cocr", "cobalt", r"cocr|co-?cr|cobalt[- ]?chrom"),
        # aluminum
        ("alsi10mg", "aluminum", r"alsi10mg"),
        ("a356", "aluminum", r"a356"),
        ("5052", "aluminum", rf"{_D}5052{_E}"),
        ("6061", "aluminum", rf"{_D}6061{_E}"),
        ("6082", "aluminum", rf"{_D}6082{_E}"),
        ("7075", "aluminum", rf"{_D}7075{_E}"),
        ("2024", "aluminum", rf"{_D}2024{_E}"),
        ("mic6", "aluminum", r"mic-?6"),
        # steel
        ("4140", "steel", rf"{_D}4140{_E}"),
        ("4130", "steel", rf"{_D}4130{_E}"),
        ("4340", "steel", rf"{_D}4340{_E}"),
        ("a182_f22", "steel", rf"{_D}f22{_E}"),
        ("a105", "steel", rf"a105{_E}"),
        ("ductile_iron", "steel", r"ductile\s*iron"),
        ("mild_steel", "steel", rf"mild\s*steel|low[- ]carbon|{_D}a36{_E}|{_D}10(18|20){_E}"),
        # other metals the engine names
        ("copper_c110", "copper", r"c110|\bcopper\b"),
        ("zamak", "zinc", r"zamak"),
        # polymers
        ("pa12_gf", "polymer", r"glass[- ]?filled\s*(pa|nylon)\s*-?\s*12|pa\s*12\s*gf"),
        ("pa66_gf30", "polymer", r"pa\s*66\s*-?\s*gf|nylon\s*66\s*gf"),
        ("cf_nylon", "polymer", r"cf-?\s*nylon|carbon[- ]fib(er|re)\s*nylon|pa\s*-?\s*cf"),
        ("pa12", "polymer", r"pa\s*-?\s*12|nylon\s*-?\s*12"),
        ("pa11", "polymer", r"pa\s*-?\s*11|nylon\s*-?\s*11"),
        ("pa66", "polymer", r"pa\s*-?\s*66|nylon\s*-?\s*6/?6"),
        ("pa6", "polymer", rf"pa\s*-?\s*6{_E}|nylon\s*-?\s*6{_E}|\bnylon\b"),
        ("pom", "polymer", r"delrin|\bpom\b|acetal"),
        ("peek", "polymer", r"\bpeek\b"),
        ("ultem", "polymer", r"ultem|\bpei\b"),
        ("tpu", "polymer", r"\btpu\b"),
        ("petg", "polymer", r"\bpetg\b"),
        ("pla", "polymer", r"\bpla\b"),
        ("asa", "polymer", r"\basa\b"),
        ("abs", "polymer", r"\babs\b"),
        ("pc", "polymer", r"\bpc\b|polycarbonate"),
        ("pp", "polymer", r"\bpp\b|polypropylene"),
        ("standard_resin", "polymer", r"standard\s*resin"),
        ("tough_resin", "polymer", r"tough\s*resin"),
        ("flexible_resin", "polymer", r"flexible\s*resin"),
        ("castable_resin", "polymer", r"castable\s*resin"),
        ("dental_resin", "polymer", r"dental"),
    )
)

# Families a catalog run prices: the engine has machining and other routes for each.
PRICED_FAMILIES = ("polymer", "aluminum", "steel", "stainless", "titanium", "nickel")

FAMILY_WORDS = {
    "polymer": "plastic",
    "aluminum": "aluminum",
    "steel": "steel",
    "stainless": "stainless steel",
    "titanium": "titanium",
    "nickel": "nickel alloy",
    "cobalt": "cobalt-chrome",
    "copper": "copper",
    "zinc": "zinc alloy",
}


def grade_of(text: Optional[str]) -> Optional[str]:
    """The grade key a material's words name, or None when no grade is named."""
    t = (text or "").strip()
    if not t:
        return None
    for key, _family, pattern in _GRADES:
        if pattern.search(t):
            return key
    return None


def family_of_grade(key: Optional[str]) -> Optional[str]:
    for k, family, _pattern in _GRADES:
        if k == key:
            return family
    return None


def grade_key(material_name: Optional[str]) -> Optional[str]:
    """An engine material name's grade key ("304 SS (Sheet)" -> "304")."""
    return grade_of(material_name)


def same_grade(material_name: Optional[str], listed: Optional[str]) -> bool:
    """True when an engine material is the grade a list names (by key, else by name)."""
    if not material_name or not listed:
        return False
    a, b = grade_key(material_name), grade_of(listed)
    if a and b:
        return a == b
    return material_name.strip().lower() == listed.strip().lower()


def engine_names_for(listed: Optional[str]) -> list[str]:
    """Every engine material that is the listed grade (any form: bar, sheet, cast)."""
    from src.costing.rates import MATERIAL_FAMILY

    key = grade_of(listed)
    if key is None:
        exact = [n for n in MATERIAL_FAMILY if n.lower() == (listed or "").strip().lower()]
        return exact
    return [n for n in MATERIAL_FAMILY if grade_key(n) == key]


def substitutes_allowed(family: Optional[str]) -> bool:
    """Whether a route that doesn't run the listed grade may be priced in another
    grade of the same family. Metals: yes, a nearby grade of the same metal is a
    fair proxy for the route's cost (the row says which grade was used). Plastics:
    no. PLA, Delrin and PEEK are different parts, so a route that can't run the
    named plastic isn't priced for it."""
    return family not in (None, "polymer")
