"""Machine and material profile database."""

from __future__ import annotations

from typing import Optional

from src.analysis.models import ProcessType
from src.profiles.models import (
    MAKER_DESCRIBED,
    MAKER_SPEC,
    MachineProfile,
    MakerSpec,
    MaterialProfile,
)
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

# Each entry carries its maker's published spec (``MakerSpec``): the rated
# workpiece load where the maker publishes one, and the page its materials were
# read from. A value the maker doesn't publish stays None and the note says so.
# Pages read 2026-10-19. CNC ``materials`` are engine material classes.
_CHECKED = "2026-10-19"
_NO_PLATE_LOAD = "The maker publishes no build-plate load; the build volume governs."

MACHINES: list[MachineProfile] = [
    # FDM
    MachineProfile(
        "Bambu Lab X1C", "Bambu Lab", ProcessType.FDM, (256, 256, 256), 0.04, 0.4, 0.4,
        ["PLA", "PETG", "ABS", "Nylon", "TPU"],
        spec=MakerSpec(
            "https://public-cdn.bambulab.com/store/bambulab-X1-carbon-tech-specs.pdf",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note="Bambu Lab lists PLA, PETG, TPU, ABS, ASA, PET, PA and PC.",
            checked=_CHECKED)),
    MachineProfile(
        "Prusa MK4S", "Prusa Research", ProcessType.FDM, (250, 210, 220), 0.05, 0.35, 0.4,
        ["PLA", "PETG"],
        spec=MakerSpec(
            "https://www.prusa3d.com/product/original-prusa-mk4s-3d-printer-5/",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note=("Prusa lists PLA, PETG, Flex, PVA, PC, PP, CPE and PVB. ABS, ASA, HIPS "
                            "and PA need the Original Prusa Enclosure with filtration, so they aren't prefilled."),
            checked=_CHECKED)),
    MachineProfile(
        "Stratasys F900", "Stratasys", ProcessType.FDM, (914.4, 609.6, 914.4), 0.127, 0.508, 0.4,
        ["ULTEM 9085", "Nylon 12CF", "ABS-M30"],
        spec=MakerSpec(
            "https://www.stratasys.com/en/3d-printers/printer-catalog/fdm-printers/f900-printer/",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note="Stratasys lists ULTEM 9085, FDM Nylon 12CF and ABS-M30 among its F900 materials.",
            checked=_CHECKED)),
    MachineProfile(
        "BigRep ONE", "BigRep", ProcessType.FDM, (1005, 1005, 1005), 0.1, 1.0, 0.6,
        ["PLA", "PETG", "PA6/66"],
        spec=MakerSpec(
            "https://bigrep.com/bigrep-one/",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note="BigRep lists rPLA, rPETG, PRO HT, TPU 98A and PA6/66 among others.",
            checked=_CHECKED)),
    # SLA/DLP
    MachineProfile(
        "Formlabs Form 4", "Formlabs", ProcessType.SLA, (200, 125, 210), 0.025, 0.3, 0.05,
        ["Standard", "Tough", "Flexible", "Castable"],
        spec=MakerSpec(
            "https://formlabs.com/products/form-4-complete-package/",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_url="https://formlabs.com/global/materials/",
            materials_note="Formlabs lists Standard, Tough, Flexible and Castable Wax resins for the Form 4.",
            checked=_CHECKED)),
    MachineProfile(
        "Carbon M2", "Carbon", ProcessType.DLP, (189, 118, 326), 0.025, 0.1, 0.075,
        ["RPU 70", "EPU 41", "CE 221"],
        spec=MakerSpec(
            "https://learn.carbon3d.com/hardware/m1-m2-features",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_url="https://docs.carbon3d.com/files/design-guides/dg_dls-design-quick-guide.pdf",
            materials_note="Carbon lists RPU 70, EPU 41 and CE 221.",
            checked=_CHECKED)),
    MachineProfile(
        "Elegoo Saturn 4 Ultra", "Elegoo", ProcessType.DLP, (218.88, 122.88, 220), 0.01, 0.2, 0.019,
        ["Standard", "ABS-like"],
        spec=MakerSpec(
            "https://us.elegoo.com/products/saturn-4-ultra-12k-10inch-monochrome-lcd-resin-3d-printer",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note=("12K model, 405 nm. Elegoo lists its Standard, ABS-like, water-washable, "
                            "plant-based and tough resins; no castable resin."),
            checked=_CHECKED)),
    # SLS
    MachineProfile(
        "EOS P 396", "EOS", ProcessType.SLS, (340, 340, 600), 0.06, 0.18, 0.15,
        ["PA12", "PA11", "PA-GF"],
        spec=MakerSpec(
            "https://www.eos.info/polymer-solutions/polymer-printers/data-sheets/sds-eos-p-396",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note="EOS lists PA 2200 (PA12), PA 1101 (PA11) and PA 3200 GF among 14 materials.",
            checked=_CHECKED)),
    MachineProfile(
        "Farsoon HT1001P", "Farsoon", ProcessType.SLS, (1000, 500, 450), 0.06, 0.2, 0.15,
        ["PA12", "PA-GF", "TPU", "PP"],
        spec=MakerSpec(
            "https://www.farsoon-gl.com/products/ht1001p/",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note=("Farsoon lists FS3300PA (PA12), FS3401GB (glass-bead PA12), FS1092A and "
                            "FS1088A TPU and Ultrasint PP among its powders. PA11 and PEEK aren't listed "
                            "for this machine."),
            checked=_CHECKED)),
    # MJF
    MachineProfile(
        "HP Jet Fusion 5200", "HP", ProcessType.MJF, (380, 284, 380), 0.08, 0.08, 0.08,
        ["PA12", "PA11", "TPU", "PP"],
        spec=MakerSpec(
            "https://www.hp.com/us-en/printers/3d-printers/products/multi-jet-fusion-5200.html",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note="HP lists HR PA 11, HR PA 12, HR PA 12 S, HR PA 12 GB, HR PP and Ultrasint TPU01.",
            checked=_CHECKED)),
    # Metal AM
    MachineProfile(
        "EOS M 400-4", "EOS", ProcessType.DMLS, (400, 400, 400), 0.02, 0.1, 0.04,
        ["Ti6Al4V", "Inconel 718", "SS316L", "AlSi10Mg"],
        spec=MakerSpec(
            "https://www.eos.info/metal-solutions/metal-printers/eos-m-400-4",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note=("EOS lists aluminium, case-hardening steel, nickel alloys, stainless steel, "
                            "titanium and tool steel."),
            checked=_CHECKED)),
    MachineProfile(
        "SLM 500", "SLM Solutions", ProcessType.SLM, (500, 280, 365), 0.02, 0.09, 0.04,
        ["Ti6Al4V", "Inconel 718", "AlSi10Mg"],
        spec=MakerSpec(
            "https://nikon-slm-solutions.com/slm-systems/slm500/",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note=("Nikon SLM Solutions lists aluminium, cobalt, copper, nickel, steel, titanium "
                            "and niobium alloys, naming Ti-6Al-4V, AlSi10Mg and IN718."),
            checked=_CHECKED)),
    MachineProfile(
        "Arcam Q20plus", "GE Additive", ProcessType.EBM, (350, 380, 380), 0.05, 0.2, 0.1,
        ["Ti6Al4V"],
        spec=MakerSpec(
            "https://www.ge.com/additive/additive-manufacturing/machines/ebm-machines/arcam-ebm-q20plus/",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note=("GE Additive (now Colibrium Additive) listed Ti6Al4V Grade 5 and Grade 23; "
                            "its page is offline since the rename. CoCr isn't listed for this machine."),
            checked=_CHECKED)),
    MachineProfile(
        "ExOne S-Max Pro", "ExOne", ProcessType.BINDER_JET, (1800, 1000, 700), 0.28, 0.5, 0.3,
        ["Sand"],
        spec=MakerSpec(
            "https://exone.com/en-US/3D-printing-systems/sand-3D-Drucker/S-MAX-Pro",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note=("ExOne lists foundry sands from silica to ceramic with furan, phenolic or "
                            "inorganic binders: it prints sand molds and cores, not metal parts."),
            checked=_CHECKED)),
    MachineProfile(
        "Desktop Metal Shop System", "Desktop Metal", ProcessType.BINDER_JET, (350, 220, 200), 0.05, 0.2, 0.1,
        ["17-4 PH", "SS316L"],
        spec=MakerSpec(
            "https://www.desktopmetal.com/uploads/2024_Q2.1_DesktopMetal_MaterialsGuide.pdf",
            kg_note=_NO_PLATE_LOAD, materials_basis=MAKER_SPEC,
            materials_note="Desktop Metal qualifies 17-4 PH and 316L on the Shop System.",
            checked=_CHECKED)),
    # CNC: ``materials`` are engine material classes, kept conservative.
    MachineProfile(
        "Haas VF-2", "Haas", ProcessType.CNC_3AXIS, (762, 406, 508), notes="30x16x20 inches, 8100 RPM",
        materials=["aluminum", "steel"],
        spec=MakerSpec(
            "https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2.html",
            max_workpiece_kg=1361.0,
            kg_note="Max weight on table, evenly distributed: 3000 lb (1361 kg).",
            materials_basis=MAKER_DESCRIBED,
            materials_url="https://www.haascnc.com/productivity/spindles/8-1k-40t-in.html",
            materials_note=("Haas lists no materials; it calls the standard 8100-rpm 40-taper spindle "
                            "all-purpose. Aluminum and steel only: add stainless or titanium if you cut them."),
            checked=_CHECKED)),
    MachineProfile(
        "DMG MORI DMU 50", "DMG MORI", ProcessType.CNC_5AXIS, (650, 520, 475),
        notes="3rd generation, 5-axis simultaneous",
        materials=["aluminum", "steel", "stainless"],
        spec=MakerSpec(
            "https://us.dmgmori.com/products/machines/milling/5-axis-milling/dmu/dmu-50",
            max_workpiece_kg=300.0,
            kg_note="DMU 50 3rd Generation: max. table load 300 kg (661 lb).",
            materials_basis=MAKER_DESCRIBED,
            materials_url="https://us.dmgmori.com/news-and-media/news/dmu-50-3rd-generation",
            materials_note=("DMG MORI lists no materials; it names general mechanical engineering, fixture "
                            "construction, aerospace, medical and automotive work. Aluminum, steel and "
                            "stainless: add titanium if you cut it."),
            checked=_CHECKED)),
    MachineProfile(
        "Haas ST-20", "Haas", ProcessType.CNC_TURNING, (254, 254, 533), notes="8.3-inch chuck, 4000 RPM",
        materials=["aluminum", "steel"],
        spec=MakerSpec(
            "https://www.haascnc.com/service/troubleshooting-and-how-to/reference-documents/lathe-work-piece-weight-limits.html",
            max_workpiece_kg=68.0,
            kg_note=("Max weight per chuck: 150 lb (68 kg), workholding excluded. 300 lb (136 kg) between "
                     "centers needs a tailstock. Haas calls these estimates, not a safe setup."),
            materials_basis=MAKER_DESCRIBED,
            materials_url="https://www.haascnc.com/machines/lathes/st/models/standard/st-20.html",
            materials_note="Haas lists no materials for the ST-20. Aluminum and steel only: add stainless or titanium if you turn them.",
            checked=_CHECKED)),
    MachineProfile(
        "Sodick ALC600G", "Sodick", ProcessType.WIRE_EDM, (600, 400, 350), notes="Linear motor, 0.01mm accuracy",
        materials=["aluminum", "steel", "stainless", "titanium"],
        spec=MakerSpec(
            "https://sodick.com/product/alc600g-ige/",
            max_workpiece_kg=1000.0,
            kg_note="Maximum workpiece weight: 2,204 lb (1,000 kg).",
            materials_basis=MAKER_SPEC,
            materials_url="https://sodick.com/machines/wire-edm/",
            materials_note=("Sodick: wire EDM cuts any electrically conductive material, including hardened "
                            "tool steels, carbide, titanium and superalloys. Plastics aren't conductive."),
            checked=_CHECKED)),
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
