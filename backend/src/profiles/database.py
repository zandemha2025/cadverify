"""Machine and material profile database."""

from __future__ import annotations

from src.analysis.models import ProcessType
from src.profiles.models import MachineProfile, MaterialProfile


# ──────────────────────────────────────────────
# Materials
# ──────────────────────────────────────────────

MATERIALS: list[MaterialProfile] = [
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
    MaterialProfile("Mild Steel (Sheet)", [ProcessType.SHEET_METAL], 0.5, 1500, 350, 25, 7.85, 1.5),
    MaterialProfile("304 SS (Sheet)", [ProcessType.SHEET_METAL], 0.5, 1400, 505, 40, 8.0, 4),
    MaterialProfile("5052 Aluminum (Sheet)", [ProcessType.SHEET_METAL], 0.5, 600, 230, 12, 2.68, 4),
    MaterialProfile("Copper C110 (Sheet)", [ProcessType.SHEET_METAL], 0.5, 1080, 220, 50, 8.94, 10),
]

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
]


def get_materials_for_process(process: ProcessType) -> list[MaterialProfile]:
    """Get all materials compatible with a given process."""
    return [m for m in MATERIALS if process in m.process_types]


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
