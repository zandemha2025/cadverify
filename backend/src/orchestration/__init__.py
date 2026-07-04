"""Orchestration primitives for CadVerify.

Currently exposes the AB-MCTS-style adaptive-branching orchestrator
(``adaptive_branch``): a reusable primitive that allocates a fixed
compute/attempt budget across candidate "arms", deciding per step to go
*wider* (spawn a new candidate) vs *deeper* (refine an existing one) and
*which* generator to sample, via Thompson sampling over conjugate Bayesian
posteriors.

See ``adaptive_branch`` for the full docstring and citations.
"""

from src.orchestration.adaptive_branch import (
    Action,
    Node,
    NormalInvChiSqPosterior,
    RunResult,
    run,
    select,
)

__all__ = [
    "Action",
    "Node",
    "NormalInvChiSqPosterior",
    "RunResult",
    "run",
    "select",
]
