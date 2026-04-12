"""Process-specific DFM analyzers organized by category.

Every supported ProcessType will eventually have a ProcessAnalyzer class
in one of the subpackages:

    processes/additive/         - FDM, SLA, DLP, SLS, MJF, DMLS, SLM, EBM,
                                  Binder Jetting, DED, WAAM
    processes/subtractive/      - CNC 3/5-axis, CNC turning, wire EDM
    processes/formative/        - Injection molding, die casting,
                                  investment casting, sand casting,
                                  sheet metal, forging

Phase 1 ships the registry + protocol. Phase 2 ships the 21 concrete classes.
"""

from src.analysis.processes.base import (
    ProcessAnalyzer,
    get_analyzer,
    register,
    registered_processes,
)

__all__ = [
    "ProcessAnalyzer",
    "get_analyzer",
    "register",
    "registered_processes",
]
