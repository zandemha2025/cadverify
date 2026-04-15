"""Manufacturing DFM thresholds — single source of truth.

All process analyzers import from here. Changing a threshold requires
touching only this file.
"""
from __future__ import annotations

from src.analysis.models import ProcessType


# ──────────────────────────────────────────────────────────────
# Additive thresholds
# ──────────────────────────────────────────────────────────────
# Minimum wall thickness by process (mm)
MIN_WALL_THICKNESS: dict[ProcessType, float] = {
    ProcessType.FDM: 0.8,
    ProcessType.SLA: 0.3,
    ProcessType.DLP: 0.3,
    ProcessType.SLS: 0.7,
    ProcessType.MJF: 0.5,
    ProcessType.DMLS: 0.4,
    ProcessType.SLM: 0.4,
    ProcessType.EBM: 0.7,
    ProcessType.BINDER_JET: 1.0,
    ProcessType.DED: 1.5,
    ProcessType.WAAM: 2.0,
}

# Maximum overhang angle (degrees from vertical) before supports needed
SUPPORT_ANGLE_THRESHOLD: dict[ProcessType, float] = {
    ProcessType.FDM: 45.0,
    ProcessType.SLA: 30.0,
    ProcessType.DLP: 30.0,
    ProcessType.SLS: 90.0,    # Self-supporting (powder bed)
    ProcessType.MJF: 90.0,    # Self-supporting
    ProcessType.DMLS: 45.0,
    ProcessType.SLM: 45.0,
    ProcessType.EBM: 50.0,
    ProcessType.BINDER_JET: 90.0,  # Self-supporting
    ProcessType.DED: 60.0,
    ProcessType.WAAM: 60.0,
}

# Minimum feature size (mm) — smaller features may not resolve
MIN_FEATURE_SIZE: dict[ProcessType, float] = {
    ProcessType.FDM: 0.4,     # ~nozzle diameter
    ProcessType.SLA: 0.05,
    ProcessType.DLP: 0.05,
    ProcessType.SLS: 0.3,
    ProcessType.MJF: 0.2,
    ProcessType.DMLS: 0.15,
    ProcessType.SLM: 0.15,
    ProcessType.EBM: 0.3,
    ProcessType.BINDER_JET: 0.5,
    ProcessType.DED: 1.0,
    ProcessType.WAAM: 2.0,
}

# ──────────────────────────────────────────────────────────────
# Additive build volumes (typical per-process machine envelope, mm)
# ──────────────────────────────────────────────────────────────
BUILD_VOLUMES: dict[ProcessType, tuple[int, int, int]] = {
    ProcessType.FDM: (300, 300, 350),       # Bambu X1C / Prusa MK4
    ProcessType.SLA: (145, 145, 175),        # Formlabs Form 4
    ProcessType.DLP: (192, 120, 200),        # Elegoo Saturn
    ProcessType.SLS: (340, 340, 600),        # EOS P 396
    ProcessType.MJF: (380, 284, 380),        # HP Jet Fusion 5200
    ProcessType.DMLS: (400, 400, 400),       # EOS M 400-4
    ProcessType.SLM: (500, 280, 365),        # SLM 500
    ProcessType.EBM: (350, 380, 380),        # Arcam Q20plus
    ProcessType.BINDER_JET: (800, 500, 400), # ExOne S-Max
    ProcessType.DED: (1500, 1500, 1500),     # Large format
    ProcessType.WAAM: (5000, 3000, 3000),    # Very large format
}

# ──────────────────────────────────────────────────────────────
# CNC thresholds
# ──────────────────────────────────────────────────────────────
# Standard tool library — common end mill diameters (mm)
STANDARD_TOOL_DIAMETERS: list[float] = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0]

# Max workpiece size (mm) for typical CNC machines
MAX_WORKPIECE: dict[ProcessType, tuple[float, float, float]] = {
    ProcessType.CNC_3AXIS: (1000, 500, 500),
    ProcessType.CNC_5AXIS: (800, 500, 500),
    ProcessType.CNC_TURNING: (300, 300, 1000),  # Diameter, Diameter, Length
    ProcessType.WIRE_EDM: (500, 350, 300),
}

# Maximum pocket depth-to-width ratio
MAX_POCKET_DEPTH_RATIO: dict[ProcessType, float] = {
    ProcessType.CNC_3AXIS: 4.0,
    ProcessType.CNC_5AXIS: 6.0,
}

# ──────────────────────────────────────────────────────────────
# Molding / casting thresholds
# ──────────────────────────────────────────────────────────────
# Minimum draft angle (degrees) by process
MIN_DRAFT_ANGLE: dict[ProcessType, float] = {
    ProcessType.INJECTION_MOLDING: 1.0,
    ProcessType.DIE_CASTING: 1.0,
    ProcessType.INVESTMENT_CASTING: 0.5,
    ProcessType.SAND_CASTING: 3.0,
    ProcessType.FORGING: 5.0,
}

# Wall thickness ranges (mm) — [min, max, ideal]
WALL_THICKNESS_RANGE: dict[ProcessType, tuple[float, float, float]] = {
    ProcessType.INJECTION_MOLDING: (0.5, 6.0, 2.5),
    ProcessType.DIE_CASTING: (0.8, 12.0, 3.0),
    ProcessType.INVESTMENT_CASTING: (1.0, 50.0, 5.0),
    ProcessType.SAND_CASTING: (3.0, 100.0, 8.0),
    ProcessType.FORGING: (3.0, 200.0, 10.0),
}

# Minimum fillet radius (mm) — sharp internal corners cause stress concentration and cracking
MIN_FILLET_RADIUS: dict[ProcessType, float] = {
    ProcessType.INVESTMENT_CASTING: 0.5,
    ProcessType.SAND_CASTING: 3.0,
    ProcessType.DIE_CASTING: 1.0,
}

# ──────────────────────────────────────────────────────────────
# Sheet metal
# ──────────────────────────────────────────────────────────────
# Bend radius multipliers by material (radius = thickness * multiplier)
BEND_RADIUS_MULTIPLIER: dict[str, float] = {
    "mild_steel": 1.0,
    "stainless_steel": 1.5,
    "aluminum": 0.5,
    "copper": 0.3,
    "titanium": 3.0,
}

# Standard sheet thicknesses (mm)
STANDARD_GAUGES: list[float] = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]
