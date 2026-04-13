"""Additive manufacturing analyzers — 11 processes, FDM through WAAM.

Importing this package triggers @register on all classes.
"""

from src.analysis.processes.additive import (  # noqa: F401
    fdm,
    sla,
    dlp,
    sls,
    mjf,
    dmls,
    slm,
    ebm,
    binder_jetting,
    ded,
    waam,
)
