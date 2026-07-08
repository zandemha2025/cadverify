"""Orchestration primitives for CadVerify.

Currently exposes the AB-MCTS-style adaptive-branching orchestrator
(``adaptive_branch``): a reusable primitive that allocates a fixed
compute/attempt budget across candidate "arms", deciding per step to go
*wider* (spawn a new candidate) vs *deeper* (refine an existing one) and
*which* generator to sample, via Thompson sampling over conjugate Bayesian
posteriors.

See ``adaptive_branch`` for the full docstring and citations.

──────────────────────────────────────────────────────────────────────────
STATUS — R&D BUILDING BLOCK, NOT WIRED INTO A LIVE PATH (honest disclosure).
As of 2026-07-04 nothing in the running product or request path imports this
module; it has no live consumer. It is a validated, deterministic, unit-tested
primitive (see ``tests/test_adaptive_branch.py``) built from the moat research
(``outputs/research/orchestration-moat.md`` §Design B), kept here so it is real
and reviewable rather than a slide. Its intended consumers are (a) the
estimator ensemble's *adaptive compute allocation* (spend more search on
high-disagreement parts — moat §4/§8 P2+), and (b) our own multi-agent build
harness. Until one of those wires it in, treat it as library/R&D — do NOT
describe it as a shipped feature.
──────────────────────────────────────────────────────────────────────────
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
