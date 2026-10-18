"""Machine and material profile database."""

from __future__ import annotations

from typing import Optional

from src.analysis.models import ProcessType
from src.profiles.models import MachineProfile, MaterialProfile
from src.profiles.loader import merge_materials, MATERIALS_STRUCTURED, _YAML_MATERIALS


# ──────────────────────────────────────────────
# Materials (hardcoded base)
# ──────────────────────────────────────────────

_HARDCODED_MATERIALS: list[MaterialProfile] = [
    # FDM
    MaterialProfile("PLA", [ProcessType.FDM], 0.8, 60, 50, 6, 1.24, 25, "Easy to print, biodegradable"),
    MaterialProfile("PETG", [ProcessType.FDM], 0.8, 80, 50, 23, 1.27, 30, "Good chemical resistance"),
    MaterialProfile("ABS", [ProcessType.FDM], 1.0, 100, 40, 25, 1.04, 25, "Requires heated enclosure"),
    MaterialProfile("Nylon (PA6)", [ProcessType.FDM], 0.8, 180, 70, 30, 1.14, 50, "Strong, flexible, hygroscopic"),
    MaterialProfile("ULTEM 9085", [ProcessType.FDM], 1.0, 185, 72, 6, 1.34, 350, "Aerospace-grade, FST rated"),
    MaterialProfile("CF-Nylon", [ProcessType.FDM], 0.8, 180, 120, 5, 1.20, 80, "Carbon fiber reinforced"),
    MaterialProfile("TPU 95A", [ProcessType.FDM], 1.0, 80, 30, 500, 1.21, 45, "Flexible, rubber-like"),
    # SLA/DLP
    MaterialProfile("Standard Resin", [ProcessType.SLA, ProcessType.DLP], 0.3, 60, 45, 6, 1.18, 50),
    MaterialProfile("Tough Resin", [ProcessType.SLA, ProcessType.DLP], 0.3, 70, 55, 24, 1.18, 80),
    MaterialProfile("Flexible Resin", [ProcessType.SLA, ProcessType.DLP], 0.5, 60, 8, 80, 1.1, 70),
    MaterialProfile("Castable Resin", [ProcessType.SLA, ProcessType.DLP], 0.3, None, 12, 3, 1.1, 100, "Zero ash burnout"),
    MaterialProfile("Dental Model Resin", [ProcessType.SLA, ProcessType.DLP], 0.3, 60, 50, 5, 1.2, 150),
    # SLS/MJF
    MaterialProfile("PA12 (Nylon 12)", [ProcessType.SLS, ProcessType.MJF], 0.7, 180, 48, 20, 1.01, 60),
    MaterialProfile("PA11", [ProcessType.SLS, ProcessType.MJF], 0.7, 185, 48, 30, 1.03, 70, "Higher elongation than PA12"),
    MaterialProfile("Glass-filled PA12", [ProcessType.SLS], 0.8, 180, 52, 3, 1.37, 80, "Higher stiffness"),
    MaterialProfile("TPU (SLS)", [ProcessType.SLS], 1.0, 80, 25, 400, 1.2, 90),
    MaterialProfile("PP (MJF)", [ProcessType.MJF], 0.5, 130, 25, 15, 0.9, 60, "Polypropylene"),
    # Metal AM
    MaterialProfile("Ti6Al4V", [ProcessType.DMLS, ProcessType.SLM, ProcessType.EBM], 0.4, 1660, 1100, 10, 4.43, 350, "Aerospace titanium"),
    MaterialProfile("Inconel 718", [ProcessType.DMLS, ProcessType.SLM], 0.4, 1350, 1240, 12, 8.19, 400, "High-temp nickel superalloy"),
    MaterialProfile("SS316L", [ProcessType.DMLS, ProcessType.SLM, ProcessType.BINDER_JET], 0.4, 1400, 550, 40, 7.99, 100, "Stainless steel"),
    MaterialProfile("AlSi10Mg", [ProcessType.DMLS, ProcessType.SLM], 0.4, 660, 350, 6, 2.67, 120, "Aluminum alloy"),
    MaterialProfile("CoCr", [ProcessType.DMLS, ProcessType.SLM, ProcessType.EBM], 0.4, 1350, 1050, 8, 8.3, 300, "Cobalt chrome, dental/medical"),
    MaterialProfile("17-4 PH SS", [ProcessType.BINDER_JET], 1.0, 1400, 900, 10, 7.78, 80, "Precipitation hardened steel"),
    # CNC
    MaterialProfile("6061-T6 Aluminum", [ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS], 0.5, 580, 310, 17, 2.7, 5),
    MaterialProfile("7075-T6 Aluminum", [ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS], 0.5, 480, 570, 11, 2.81, 8, "Aerospace aluminum"),
    MaterialProfile("304 Stainless", [ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS, ProcessType.CNC_TURNING], 0.5, 1400, 505, 40, 8.0, 4),
    MaterialProfile("Ti6Al4V (Wrought)", [ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS, ProcessType.CNC_TURNING], 0.5, 1660, 900, 14, 4.43, 30, "Difficult to machine"),
    MaterialProfile("Delrin (POM)", [ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS, ProcessType.CNC_TURNING], 0.5, 175, 70, 25, 1.41, 5, "Easy to machine"),
    MaterialProfile("PEEK", [ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS], 0.5, 340, 100, 30, 1.3, 100, "High-performance polymer"),
    # Injection Molding
    MaterialProfile("ABS (Molded)", [ProcessType.INJECTION_MOLDING], 0.5, 100, 40, 20, 1.04, 3),
    MaterialProfile("PC (Polycarbonate)", [ProcessType.INJECTION_MOLDING], 0.75, 140, 63, 110, 1.2, 5),
    MaterialProfile("PP (Molded)", [ProcessType.INJECTION_MOLDING], 0.5, 130, 35, 200, 0.9, 2),
    MaterialProfile("PA66-GF30", [ProcessType.INJECTION_MOLDING], 0.75, 250, 180, 4, 1.37, 6, "Glass-filled nylon"),
    # Casting
    MaterialProfile("A356 Aluminum", [ProcessType.DIE_CASTING, ProcessType.SAND_CASTING, ProcessType.INVESTMENT_CASTING], 1.0, 660, 230, 3, 2.68, 4),
    MaterialProfile("Zinc Alloy (Zamak 3)", [ProcessType.DIE_CASTING], 0.5, 380, 280, 10, 6.6, 3),
    MaterialProfile("Ductile Iron", [ProcessType.SAND_CASTING], 3.0, 1150, 420, 18, 7.1, 2),
    MaterialProfile("17-4 PH (Cast)", [ProcessType.INVESTMENT_CASTING], 1.0, 1400, 900, 10, 7.78, 15),
    # Sheet Metal
    MaterialProfile("Mild Steel", [ProcessType.SHEET_METAL], 0.5, 1500, 350, 25, 7.85, 1.5),
    MaterialProfile("304 SS (Sheet)", [ProcessType.SHEET_METAL], 0.5, 1400, 505, 40, 8.0, 4),
    MaterialProfile("5052 Aluminum (Sheet)", [ProcessType.SHEET_METAL], 0.5, 600, 230, 12, 2.68, 4),
    MaterialProfile("Copper C110 (Sheet)", [ProcessType.SHEET_METAL], 0.5, 1080, 220, 50, 8.94, 10),
]


# Merge: YAML overrides matching hardcoded entries, adds new ones
MATERIALS: list[MaterialProfile] = merge_materials(_HARDCODED_MATERIALS, _YAML_MATERIALS)


# ──────────────────────────────────────────────
# Machines
# ──────────────────────────────────────────────

MACHINES: list[MachineProfile] = [
    # FDM
    MachineProfile("Bambu Lab X1C", "Bambu Lab", ProcessType.FDM, (256, 256, 256), 0.04, 0.4, 0.4, ["PLA", "PETG", "ABS", "Nylon", "TPU"]),
    MachineProfile("Prusa MK4S", "Prusa Research", ProcessType.FDM, (250, 210, 220), 0.05, 0.35, 0.4, ["PLA", "PETG", "ABS"]),
    MachineProfile("Stratasys F900", "Stratasys", ProcessType.FDM, (914, 610, 914), 0.127, 0.508, 0.4, ["ULTEM 9085", "Nylon 12CF", "ABS-M30"]),
    MachineProfile("BigRep ONE", "BigRep", ProcessType.FDM, (1005, 1005, 1005), 0.1, 1.0, 0.6, ["PLA", "PETG", "PA6/66"]),
    # SLA/DLP
    MachineProfile("Formlabs Form 4", "Formlabs", ProcessType.SLA, (200, 125, 210), 0.025, 0.3, 0.05, ["Standard", "Tough", "Flexible", "Castable"]),
    MachineProfile("Carbon M2", "Carbon", ProcessType.DLP, (189, 118, 326), 0.025, 0.1, 0.075, ["RPU 70", "EPU 41", "CE 221"]),
    MachineProfile("Elegoo Saturn 4 Ultra", "Elegoo", ProcessType.DLP, (218, 123, 250), 0.01, 0.2, 0.019, ["Standard", "ABS-like", "Castable"]),
    # SLS
    MachineProfile("EOS P 396", "EOS", ProcessType.SLS, (340, 340, 600), 0.06, 0.18, 0.15, ["PA12", "PA11", "PA-GF"]),
    MachineProfile("Farsoon HT1001P", "Farsoon", ProcessType.SLS, (1000, 500, 450), 0.06, 0.2, 0.15, ["PA12", "PA11", "PEEK"]),
    # MJF
    MachineProfile("HP Jet Fusion 5200", "HP", ProcessType.MJF, (380, 284, 380), 0.08, 0.08, 0.08, ["PA12", "PA11", "TPU", "PP"]),
    # Metal AM
    MachineProfile("EOS M 400-4", "EOS", ProcessType.DMLS, (400, 400, 400), 0.02, 0.1, 0.04, ["Ti6Al4V", "Inconel 718", "SS316L", "AlSi10Mg"]),
    MachineProfile("SLM 500", "SLM Solutions", ProcessType.SLM, (500, 280, 365), 0.02, 0.09, 0.04, ["Ti6Al4V", "Inconel 718", "AlSi10Mg"]),
    MachineProfile("Arcam Q20plus", "GE Additive", ProcessType.EBM, (350, 380, 380), 0.05, 0.2, 0.1, ["Ti6Al4V", "CoCr"]),
    MachineProfile("ExOne S-Max Pro", "ExOne", ProcessType.BINDER_JET, (1800, 1000, 700), 0.28, 0.5, 0.3, ["Sand", "SS316", "Bronze"]),
    MachineProfile("Desktop Metal Shop System", "Desktop Metal", ProcessType.BINDER_JET, (350, 220, 200), 0.05, 0.2, 0.1, ["17-4 PH", "SS316L"]),
    # CNC
    MachineProfile("Haas VF-2", "Haas", ProcessType.CNC_3AXIS, (762, 406, 508), notes="30x16x20 inches, 8100 RPM"),
    MachineProfile("DMG MORI DMU 50", "DMG MORI", ProcessType.CNC_5AXIS, (500, 450, 400), notes="5-axis simultaneous"),
    MachineProfile("Haas ST-20", "Haas", ProcessType.CNC_TURNING, (254, 254, 533), notes="10-inch chuck, 4000 RPM"),
    MachineProfile("Sodick ALC600G", "Sodick", ProcessType.WIRE_EDM, (600, 400, 350), notes="Linear motor, 0.01mm accuracy"),

    # ── Depth expansion v2 (2026-09-14, data-plane lane) ─────────────────
    # Public manufacturer datasheet specs; where a process has no single
    # "machine envelope" (molding / casting / forging cells) build_volume is a
    # conservative max-part proxy and the notes carry the real datasheet lever.
    # FDM
    MachineProfile("Stratasys Fortus 450mc", "Stratasys", ProcessType.FDM, (406, 355, 406), 0.127, 0.33, 0.4, ["ABS-M30", "ULTEM 9085", "ULTEM 1010", "Nylon 12"], notes="Production FDM, 16x14x16 in, T-class tip 0.33 mm"),
    # SLA
    MachineProfile("Formlabs Form 4L", "Formlabs", ProcessType.SLA, (353, 196, 350), 0.025, 0.3, 0.05, ["Standard", "Tough", "Rigid", "Castable"], notes="LFD engine, 46 um XY pixel, 35.3x19.6x35.0 cm (datasheet)"),
    MachineProfile("3D Systems ProX 800", "3D Systems", ProcessType.SLA, (650, 750, 550), 0.05, 0.15, 0.1, ["Accura 60", "Accura 25", "Accura Xtreme"], notes="Production SLA, 650x750x550 mm (datasheet)"),
    # DLP
    MachineProfile("Stratasys Origin One", "Stratasys", ProcessType.DLP, (192, 108, 370), 0.05, 0.15, 0.05, ["Loctite IND405", "Somos BioSafe", "BASF RG35"], notes="P3 programmable photopolymerization, 192x108x370 mm (datasheet)"),
    # SLS
    MachineProfile("EOS P 770", "EOS", ProcessType.SLS, (700, 380, 580), 0.06, 0.12, 0.15, ["PA12", "PA11", "PA-GF"], notes="Twin-laser production SLS, 700x380x580 mm (datasheet)"),
    MachineProfile("Formlabs Fuse 1+ 30W", "Formlabs", ProcessType.SLS, (165, 165, 300), 0.11, 0.11, 0.2, ["PA12", "PA11", "TPU 90A"], notes="Benchtop SLS, fixed 110 um layer (datasheet)"),
    # MJF
    MachineProfile("HP Jet Fusion 4200", "HP", ProcessType.MJF, (380, 284, 380), 0.08, 0.08, 0.08, ["PA12", "PA11", "PA12-GB"], notes="Production MJF, 80 um layer (datasheet)"),
    # Metal AM
    MachineProfile("EOS M 290", "EOS", ProcessType.DMLS, (250, 250, 325), 0.02, 0.09, 0.04, ["Ti6Al4V", "Inconel 718", "SS316L", "AlSi10Mg"], notes="Workhorse DMLS, 250x250x325 mm (datasheet)"),
    MachineProfile("Colibrium M2 Series 5", "Colibrium Additive (GE)", ProcessType.DMLS, (250, 250, 350), 0.02, 0.1, 0.04, ["Ti6Al4V", "CoCr", "Inconel 718"], notes="Twin-laser, 250x250x350 mm (datasheet)"),
    MachineProfile("Nikon SLM 280", "Nikon SLM Solutions", ProcessType.SLM, (280, 280, 365), 0.02, 0.09, 0.04, ["Ti6Al4V", "Inconel 718", "AlSi10Mg", "SS316L"], notes="Twin-laser, 280x280x365 mm (datasheet)"),
    MachineProfile("GE Arcam EBM Spectra H", "GE Additive", ProcessType.EBM, (250, 250, 430), 0.05, 0.2, 0.1, ["Ti6Al4V", "TiAl"], notes="Cylindrical envelope dia 250x430 mm, high-temp alloys (datasheet)"),
    MachineProfile("HP Metal Jet S100", "HP", ProcessType.BINDER_JET, (430, 309, 200), 0.05, 0.1, 0.12, ["SS316L", "17-4 PH SS"], notes="Metal binder jet, 430x309x200 mm (datasheet)"),
    # DED / WAAM
    MachineProfile("Optomec LENS 850-R", "Optomec", ProcessType.DED, (900, 1500, 900), None, None, None, ["Ti6Al4V", "Inconel 718", "SS316L"], notes="Powder-fed DED, 3 kW IPG fiber, 5-axis, 900x1500x900 mm working volume (manufacturer page, verified 2026-09-14); layer thickness application-dependent ~0.3-1.0 mm"),
    MachineProfile("DMG MORI Lasertec 65 DED", "DMG MORI", ProcessType.DED, (735, 650, 560), None, None, None, ["SS316L", "Inconel 718", "Tool steel"], notes="Hybrid powder-nozzle DED + 5-axis milling, 735x650x560 mm (datasheet)"),
    MachineProfile("Sciaky EBAM 110", "Sciaky", ProcessType.WAAM, (1778, 1194, 1600), None, None, None, ["Ti6Al4V", "Inconel 718", "SS316L"], notes="Wire-fed electron-beam AM; base work envelope 70x47x63 in = 1778x1194x1600 mm (manufacturer tech data, verified 2026-09-14), up to 42 kW gun"),
    # Injection molding (envelope = conservative max-part proxy from tie-bar spacing; clamp force is the real lever, in notes)
    MachineProfile("Haitian Mars MA3800", "Haitian", ProcessType.INJECTION_MOLDING, (600, 600, 300), None, None, None, ["ABS (Molded)", "PP (Molded)", "PA66-GF30"], notes="380 t clamp, 70 mm screw, 730 mm tie-bar spacing (datasheet, verified 2026-09-14); envelope is max-part proxy from tie-bar spacing"),
    MachineProfile("Arburg Allrounder 570 A", "Arburg", ProcessType.INJECTION_MOLDING, (450, 450, 250), None, None, None, ["ABS (Molded)", "PC (Polycarbonate)", "PP (Molded)"], notes="2000 kN clamp, 570 mm tie-bar class (datasheet); envelope is max-part proxy"),
    MachineProfile("Engel victory 500", "Engel", ProcessType.INJECTION_MOLDING, (700, 700, 400), None, None, None, ["ABS (Molded)", "PP (Molded)", "PA66-GF30", "PC (Polycarbonate)"], notes="500 US t class tie-bar-less clamp; large platen for its tonnage; envelope is max-part proxy"),
    # Die casting (locking force is the real lever, in notes; envelope = structural-part proxy)
    MachineProfile("Buhler Carat 140", "Buhler", ProcessType.DIE_CASTING, (1200, 1200, 700), None, None, None, ["A356 Aluminum", "Zinc Alloy (Zamak 3)"], notes="14,000 kN two-platen locking force (Buhler Carat series 10,500-92,000 kN, verified 2026-09-14); giga/structural castings; envelope is part proxy"),
    MachineProfile("Buhler Evolution 420 D", "Buhler", ProcessType.DIE_CASTING, (600, 600, 400), None, None, None, ["A356 Aluminum", "Zinc Alloy (Zamak 3)"], notes="4,200 kN locking force class; mid-size cold chamber; envelope is part proxy"),
    # Casting / forging cells (no single machine envelope - honest cell profiles)
    MachineProfile("Vacuum investment-casting cell", "(process cell)", ProcessType.INVESTMENT_CASTING, (600, 600, 800), None, None, None, ["17-4 PH (Cast)", "Inconel 718", "A356 Aluminum"], notes="Cell profile, not one machine: shell line + vacuum pour; envelope is typical aerospace/structural pour envelope"),
    MachineProfile("Jobbing sand-casting cell", "(process cell)", ProcessType.SAND_CASTING, (2000, 1500, 1000), None, None, None, ["Ductile Iron", "A356 Aluminum"], notes="Cell profile, not one machine: no-bake/green-sand jobbing foundry; envelope is typical flask envelope"),
    MachineProfile("20 MN open-die forging press", "(process cell)", ProcessType.FORGING, (1500, 800, 800), None, None, None, ["AISI 4130", "7075-T6 Aluminum", "Ti6Al4V (Wrought)"], notes="Cell profile: 2,000 t open-die press + manipulator; envelope is typical billet/preform envelope"),
    # Sheet metal
    MachineProfile("Trumpf TruLaser 3030 fiber", "Trumpf", ProcessType.SHEET_METAL, (3000, 1500, 25), None, None, None, ["Mild Steel", "304 SS (Sheet)", "5052 Aluminum (Sheet)"], notes="Fiber laser, 3000x1500 mm sheet (datasheet); Z field used as max cut thickness: 25 mm mild steel, 20 mm stainless, 20 mm aluminum class"),
    MachineProfile("Amada HG-1003 ATC", "Amada", ProcessType.SHEET_METAL, (3000, 500, 500), None, None, None, ["Mild Steel", "304 SS (Sheet)", "5052 Aluminum (Sheet)", "Copper C110 (Sheet)"], notes="100 t x 3 m press brake with automatic tool change; envelope = max bend length x typical open height x typical stroke"),
    # CNC depth
    MachineProfile("Haas VF-4", "Haas", ProcessType.CNC_3AXIS, (1270, 508, 635), notes="50x20x25 in, 8100 RPM"),
    MachineProfile("Tormach 1100M", "Tormach", ProcessType.CNC_3AXIS, (460, 280, 262), notes="Prosumer VMC, 18x11x10.25 in"),
    MachineProfile("Hermle C 400", "Hermle", ProcessType.CNC_5AXIS, (850, 700, 600), notes="5-axis simultaneous, 850x700x600 mm (datasheet)"),
    MachineProfile("Haas UMC-750", "Haas", ProcessType.CNC_5AXIS, (762, 508, 508), notes="30x20x20 in trunnion 5-axis"),
    MachineProfile("Mazak QT-200", "Mazak", ProcessType.CNC_TURNING, (380, 380, 540), notes="8-inch chuck class, max dia ~380 mm, bar capacity 65 mm"),
    MachineProfile("Haas TL-1", "Haas", ProcessType.CNC_TURNING, (406, 406, 762), notes="16x30 in toolroom lathe"),
    MachineProfile("FANUC RoboCut alpha-C400iB", "FANUC", ProcessType.WIRE_EDM, (400, 300, 255), notes="400x300x255 mm travels (datasheet), +-2.5 um class"),
]


# ──────────────────────────────────────────────
# Query helpers
# ──────────────────────────────────────────────

def get_materials_for_process(process: ProcessType) -> list[MaterialProfile]:
    """Get all materials compatible with a given process."""
    return [m for m in MATERIALS if process in m.process_types]


def processes_for_material_class(material_class: str) -> frozenset[ProcessType]:
    """Every ProcessType that can actually be made in the given material class.

    Derived from the SAME source of truth the cost path uses — the merged
    ``MATERIALS`` profiles (their ``process_types``) keyed by the material-family
    map (``rates.MATERIAL_FAMILY``). A class → the union of the process_types of
    every material profile whose family == that class. This is authoritative and
    can never drift from costing's ``select_material`` (which also filters
    ``get_materials_for_process`` by ``MATERIAL_FAMILY == material_class``).

    Example (with the shipped/merged profiles):
      * ``"aluminum"`` → {cnc_3axis, cnc_5axis, cnc_turning, die_casting, dmls,
        forging, investment_casting, sand_casting, sheet_metal, slm}
        — NO resin/SLS/MJF/FDM/binder-jet (correctly excluded for a metal).
      * ``"polymer"`` → {fdm, sla, dlp, sls, mjf, injection_molding, cnc_3axis,
        cnc_5axis, cnc_turning} — polymer processes only.

    An unknown class returns an empty set (the caller must treat that as "no
    filter / material unknown", never as "nothing is makeable").
    """
    # Imported lazily: rates.py imports only src.analysis.models so there is no
    # import cycle either way, but keeping it local lets database.py be imported
    # by early bootstrap paths without pulling in the rate card.
    from src.costing.rates import MATERIAL_FAMILY

    procs: set[ProcessType] = set()
    for m in MATERIALS:
        if MATERIAL_FAMILY.get(m.name) == material_class:
            procs.update(m.process_types)
    return frozenset(procs)


def get_machines_for_process(process: ProcessType) -> list[MachineProfile]:
    """Get all machines for a given process."""
    return [m for m in MACHINES if m.process_type == process]


def get_all_processes() -> list[dict]:
    """Get summary of all manufacturing processes."""
    result = []
    for pt in ProcessType:
        materials = get_materials_for_process(pt)
        machines = get_machines_for_process(pt)
        result.append({
            "process": pt.value,
            "material_count": len(materials),
            "machine_count": len(machines),
            "materials": [m.name for m in materials],
            "machines": [m.name for m in machines],
        })
    return result


def get_material_by_name(name: str) -> Optional[MaterialProfile]:
    """Look up a material by exact name (case-insensitive).

    Returns None if no match is found.
    """
    name_lower = name.lower()
    for m in MATERIALS:
        if m.name.lower() == name_lower:
            return m
    return None


def get_compliant_materials(standard: str) -> list[MaterialProfile]:
    """Get all materials whose compliance dict has the given key set to True.

    Args:
        standard: Compliance key, e.g. "nace_mr0175", "biocompatible".

    Returns:
        List of MaterialProfile instances that are compliant.
    """
    return [m for m in MATERIALS if m.compliance.get(standard) is True]
