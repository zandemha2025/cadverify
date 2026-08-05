"""The CadVerify knowledge corpus — domain knowledge the engine is allowed to know.

Machine-readable packs (``packs/*.yaml``) back DFM rules, environment filtering
and audit narration; the written library (``library/**/*.md``) carries the 101s,
the expert heuristics and the auditor playbooks.

Everything here is DEFAULT provenance. A shop-measured value always wins.
See ``README.md`` for the corpus contract.
"""

from src.knowledge.loader import (
    KnowledgeValidationError,
    library_documents,
    load_knowledge,
)
from src.knowledge.models import (
    AuditChecklist,
    ChecklistItem,
    DamageMechanism,
    DesignRule,
    Environment,
    FindingSeverity,
    GlossaryTerm,
    KnowledgeBase,
    RedFlag,
    Relation,
    Source,
    SourceTier,
)

__all__ = [
    "AuditChecklist",
    "ChecklistItem",
    "DamageMechanism",
    "DesignRule",
    "Environment",
    "FindingSeverity",
    "GlossaryTerm",
    "KnowledgeBase",
    "KnowledgeValidationError",
    "RedFlag",
    "Relation",
    "Source",
    "SourceTier",
    "library_documents",
    "load_knowledge",
]
