"""Process-specific DFM analyzers organized by category.

Importing this package triggers @register on all 21 ProcessAnalyzer classes.
"""

from src.analysis.processes.base import (
    ProcessAnalyzer,
    get_analyzer,
    register,
    registered_processes,
)

# Import subpackages to trigger @register decorators
from src.analysis.processes import additive as _additive  # noqa: F401
from src.analysis.processes import subtractive as _subtractive  # noqa: F401
from src.analysis.processes import formative as _formative  # noqa: F401

__all__ = [
    "ProcessAnalyzer",
    "get_analyzer",
    "register",
    "registered_processes",
]
