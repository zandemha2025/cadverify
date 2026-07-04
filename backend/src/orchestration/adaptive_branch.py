"""AB-MCTS-style adaptive-branching orchestrator (from-scratch implementation).

A reusable primitive for allocating a *fixed* compute / attempt budget across
candidate "arms" produced by one or more generators. At every step it decides,
adaptively and from data, whether to go

    * **wider**  — spend the next unit of budget spawning a brand-new candidate
      (the special ``GEN`` action), or
    * **deeper** — refine the most-promising *existing* candidate,

and *which* named generator to sample next — all via **Thompson sampling** over
conjugate Bayesian posteriors. It is generator-agnostic: the arms can be
multiple cost estimators, multiple build agents / model tiers, or any
generate-and-evaluate loop whatsoever.

--------------------------------------------------------------------------------
Provenance / clean-room note
--------------------------------------------------------------------------------
This is our own clean-room implementation of the *published* AB-MCTS algorithm.
It is written from the paper's description, not from Sakana's code, and is not a
copy of TreeQuest.

    Sakana AI — "Wider or Deeper? Scaling LLM Inference-Time Compute with
    Adaptive Branching Tree Search" (AB-MCTS), NeurIPS 2025 spotlight,
    arXiv:2503.04412. Reference impl: SakanaAI/treequest (Apache-2.0).
    Blog: https://sakana.ai/ab-mcts/

See also ``outputs/research/orchestration-moat.md`` §1.2 (the mechanism) and §5
(Design B — the agent/build harness), which this module implements.

--------------------------------------------------------------------------------
How the pieces map onto the paper (§1.2 of the moat brief)
--------------------------------------------------------------------------------
* **The GEN-node trick (wider vs. deeper).** Standard MCTS has a fixed set of
  child arms per node. AB-MCTS adds a special ``GEN`` action at *every* node:
  choosing ``GEN`` calls a generator and spawns a *new* child (go wider);
  choosing an existing child descends into it and, eventually, refines it (go
  deeper — a ``GEN`` fired at a deeper node conditions on that node's
  candidate). Arms are therefore created *dynamically*, so UCT's fixed-arm bound
  does not apply — selection uses Thompson sampling instead (``select``).

* **Thompson sampling over a Bayesian posterior.** For each available action we
  draw one sample from its posterior over reward and take the argmax
  (``select``). Because ``GEN`` at a fresh node has *no* direct observations,
  its posterior is the prior — built-in optimism (heavy-tailed prior) keeps
  exploration alive so a promising-but-untried width is never starved.

* **AB-MCTS-A (conjugate, closed-form).** The paper gives two posteriors:
  AB-MCTS-**M** (mixed-effects, MCMC) and AB-MCTS-**A** (conjugate, closed
  form). We implement the **A** variant: a **Normal-Inverse-χ²** posterior over
  each arm's reward (see ``NormalInvChiSqPosterior``). We picked Normal-Inv-χ²
  over Beta because our rewards are **unbounded / real-valued** (e.g. negative
  error, a quality score, a noisy function value) rather than confined to
  ``[0, 1]``; Normal-Inv-χ² is the natural conjugate for a Gaussian likelihood
  with *both* mean and variance unknown, and every update is closed form (no
  MCMC). If your reward is genuinely a bounded rate in ``[0, 1]``, a Beta
  posterior would be simpler; we deliberately support the general case.

* **Multi-LLM / multi-generator selection.** Each generator gets its *own*
  ``GEN`` posterior at each node, so Thompson sampling also chooses *which*
  generator to sample next; a generator that keeps producing good candidates is
  sampled increasingly often, exactly as "more promising models become
  increasingly likely to be chosen" in the paper.

--------------------------------------------------------------------------------
Why this beats fixed fan-out (the design intent)
--------------------------------------------------------------------------------
Fixed fan-out (N builders / M verifiers, or "sample K times") is either
all-width-no-exploitation or all-depth-and-stuck-on-a-bad-start. Here a bad
first candidate simply keeps a *low* posterior and is quietly abandoned, while
budget flows to the arm whose posterior is climbing; a strong generator is
sampled more and more over time. The wider-vs-deeper mix is chosen *per node
from data*, not fixed up front. See ``RunResult`` for the telemetry that makes
this observable (per-generator pull counts; the wider→deeper shift).

--------------------------------------------------------------------------------
Determinism
--------------------------------------------------------------------------------
All randomness is drawn from an explicitly-seeded, *local* ``numpy`` Generator
(``numpy.random.default_rng``). No global RNG state is ever touched, so runs are
byte-for-byte reproducible given the same ``seed`` (and deterministic
``generate_fns`` / ``evaluate_fn``). ``run`` threads that one Generator through
selection, generation and evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Union

import numpy as np

# A generator produces a candidate. It receives the parent candidate to refine
# (``None`` when spawning fresh at the root) and the run's RNG, so generators can
# be stochastic *and* reproducible.
GenerateFn = Callable[[Optional[Any], np.random.Generator], Any]
# An evaluator scores a candidate. Higher reward is better. Reward is
# real-valued and unbounded (that is why we use a Normal-Inverse-χ² posterior).
EvaluateFn = Callable[[Any], float]

RngLike = Union[int, np.random.Generator, None]


def _as_rng(rng: RngLike) -> np.random.Generator:
    """Coerce a seed / Generator / None into a local numpy Generator.

    Never uses or mutates global RNG state — reproducibility is by construction.
    """
    if isinstance(rng, np.random.Generator):
        return rng
    return np.random.default_rng(rng)


# ──────────────────────────────────────────────────────────────────────────────
# Conjugate posterior — AB-MCTS-A style (Normal-Inverse-χ²)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class NormalInvChiSqPosterior:
    """Conjugate Normal-Inverse-χ² posterior over an arm's (unbounded) reward.

    Models rewards as ``y ~ Normal(theta, sigma^2)`` with *both* the mean
    ``theta`` and variance ``sigma^2`` unknown, under the conjugate
    Normal-Inverse-χ² prior parameterised by:

        mu0       prior mean of theta
        kappa0    prior strength (pseudo-observations) on the mean
        nu0       prior degrees of freedom for the variance
        sigma2_0  prior scale for the variance

    Updates are the standard closed-form conjugate recursions (Gelman, BDA3,
    §3.3) — no MCMC. Sufficient statistics are accumulated online with a
    numerically-stable Welford recursion, so ``update`` is O(1) and exact.

    A larger prior ``sigma2_0`` (relative to the reward scale) gives an untried
    arm a heavier-tailed predictive → more optimistic Thompson draws → the
    built-in exploration the GEN action relies on.
    """

    mu0: float = 0.0
    kappa0: float = 1.0
    nu0: float = 1.0
    sigma2_0: float = 1.0

    # Online sufficient statistics: count, running mean, sum of squared deviations.
    n: int = 0
    _mean: float = 0.0
    _m2: float = 0.0

    def copy(self) -> "NormalInvChiSqPosterior":
        """A fresh posterior with the same *prior* (no accumulated data)."""
        return NormalInvChiSqPosterior(
            mu0=self.mu0, kappa0=self.kappa0, nu0=self.nu0, sigma2_0=self.sigma2_0
        )

    # -- conjugate update -----------------------------------------------------
    def update(self, reward: float) -> None:
        """Fold one observed reward into the posterior (closed form)."""
        r = float(reward)
        self.n += 1
        delta = r - self._mean
        self._mean += delta / self.n
        self._m2 += delta * (r - self._mean)

    # -- posterior parameters (closed form) -----------------------------------
    @property
    def kappa_n(self) -> float:
        return self.kappa0 + self.n

    @property
    def nu_n(self) -> float:
        return self.nu0 + self.n

    @property
    def mu_n(self) -> float:
        """Posterior mean of ``theta`` — a precision-weighted blend of prior and data."""
        return (self.kappa0 * self.mu0 + self.n * self._mean) / self.kappa_n

    @property
    def sigma2_n(self) -> float:
        """Posterior scale for the variance."""
        num = (
            self.nu0 * self.sigma2_0
            + self._m2
            + (self.kappa0 * self.n / self.kappa_n) * (self._mean - self.mu0) ** 2
        )
        return num / self.nu_n

    @property
    def mean(self) -> float:
        """Point estimate of the arm's reward (posterior mean of ``theta``)."""
        return self.mu_n

    @property
    def mean_variance(self) -> float:
        """Variance of the marginal posterior over ``theta`` (a Student-t).

        Equal to ``(sigma2_n / kappa_n) * nu_n / (nu_n - 2)`` when ``nu_n > 2``,
        else infinite. This is the quantity that **shrinks toward 0 as more
        rewards are observed** (kappa_n grows ∝ n), i.e. the posterior sharpens.
        """
        if self.nu_n <= 2:
            return math.inf
        scale2 = self.sigma2_n / self.kappa_n
        return scale2 * self.nu_n / (self.nu_n - 2)

    # -- Thompson sampling ----------------------------------------------------
    def sample(self, rng: np.random.Generator) -> float:
        """Draw one Thompson sample of the arm's mean reward ``theta``.

        Samples from the marginal posterior over ``theta`` (a Student-t):
        draw ``sigma^2`` from the scaled-inverse-χ² posterior, then draw
        ``theta ~ Normal(mu_n, sigma^2 / kappa_n)``. With no data this reduces
        to a draw from the prior — the optimism that keeps GEN explored.
        """
        chi2 = rng.chisquare(self.nu_n)
        # Guard the (measure-zero) chi2==0 draw so we never divide by zero.
        if chi2 <= 0.0:
            chi2 = 1e-12
        sigma2 = self.nu_n * self.sigma2_n / chi2
        return self.mu_n + math.sqrt(sigma2 / self.kappa_n) * rng.standard_normal()


# ──────────────────────────────────────────────────────────────────────────────
# Tree
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Node:
    """A node in the adaptive-branching tree.

    The root (``candidate is None``) holds no candidate; every other node holds
    one evaluated candidate. Each node carries:

      * ``subtree_post`` — a posterior over rewards observed *anywhere in this
        node's subtree*. Its parent uses this to Thompson-sample the "descend
        into this child (go deeper)" action.
      * ``gen_post`` — one posterior *per generator* over the reward of children
        spawned via ``GEN`` at this node. Used to Thompson-sample the
        "spawn a new child with generator g (go wider)" action.
    """

    candidate: Any = None
    generator: Optional[str] = None  # which generator produced this node's candidate
    reward: Optional[float] = None
    depth: int = 0
    parent: Optional["Node"] = None
    children: list["Node"] = field(default_factory=list)

    subtree_post: NormalInvChiSqPosterior = field(default_factory=NormalInvChiSqPosterior)
    gen_post: dict[str, NormalInvChiSqPosterior] = field(default_factory=dict)


@dataclass
class Action:
    """A selected action at a node.

    ``kind`` is ``"GEN"`` (go wider — spawn a new child with ``generator``) or
    ``"DEEPEN"`` (go deeper — descend into ``child``). ``score`` is the Thompson
    sample that won the argmax (exposed for debugging / telemetry).
    """

    kind: str
    score: float
    generator: Optional[str] = None
    child: Optional[Node] = None


def select(
    node: Node,
    generators: list[str],
    rng: np.random.Generator,
    prior: NormalInvChiSqPosterior,
) -> Action:
    """Thompson-sample one action at ``node``.

    Candidate actions are: one ``GEN`` per generator (go wider with that
    generator) and one ``DEEPEN`` per existing child (go deeper). We draw a
    single posterior sample for each and return the argmax. Ties (and the fully
    unobserved root, where every GEN posterior equals the prior) are broken by
    the RNG draw itself, so exploration among untried generators is automatic.
    """
    best: Optional[Action] = None

    # Go-wider arms: one GEN posterior per generator at this node.
    for g in generators:
        post = node.gen_post.get(g)
        if post is None:
            post = prior.copy()
            node.gen_post[g] = post
        s = post.sample(rng)
        if best is None or s > best.score:
            best = Action(kind="GEN", score=s, generator=g)

    # Go-deeper arms: one per existing child, scored by the child's subtree posterior.
    for child in node.children:
        s = child.subtree_post.sample(rng)
        if best is None or s > best.score:
            best = Action(kind="DEEPEN", score=s, child=child)

    assert best is not None  # generators is non-empty (checked in run())
    return best


# ──────────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class RunResult:
    """Outcome of a :func:`run`.

    Attributes
    ----------
    best_candidate / best_reward
        The single highest-reward candidate produced across the whole budget.
    root
        The fully-expanded tree (for inspection).
    n_evaluations
        Number of candidates generated & evaluated (== ``budget``).
    generator_counts
        How many candidates each generator produced — a strong arm dominates.
    wider_count / deeper_count
        Generations that spawned a fresh top-level candidate (wider, depth 1)
        vs. refined an existing candidate (deeper, depth > 1). The ratio shifts
        from wider→deeper as good candidates emerge.
    action_log
        Per-step ``(mode, generator, reward, depth)`` where ``mode`` is
        ``"wider"`` or ``"deeper"`` — the raw trace the tests assert on.
    """

    best_candidate: Any
    best_reward: float
    root: Node
    n_evaluations: int
    generator_counts: dict[str, int]
    wider_count: int
    deeper_count: int
    action_log: list[tuple[str, str, float, int]] = field(default_factory=list)


def run(
    generate_fns: Mapping[str, GenerateFn],
    evaluate_fn: EvaluateFn,
    budget: int,
    *,
    rng: RngLike = None,
    prior: Optional[NormalInvChiSqPosterior] = None,
) -> RunResult:
    """Drive adaptive branching for ``budget`` generate-and-evaluate steps.

    Parameters
    ----------
    generate_fns
        Named callables, the "multiple models / methods". Each is
        ``fn(parent_candidate, rng) -> candidate``. ``parent_candidate`` is
        ``None`` when spawning fresh at the root (go wider) and the parent's
        candidate when refining (go deeper). The provided ``rng`` MUST be used
        for any randomness to keep the run reproducible.
    evaluate_fn
        ``fn(candidate) -> float`` reward; higher is better; unbounded.
    budget
        Number of candidates to generate & evaluate (total compute units).
    rng
        Seed (int), an existing ``numpy`` Generator, or ``None``. Threaded
        through selection, generation and evaluation for full determinism.
    prior
        Prior template for every arm's posterior. Copied per arm. Defaults to a
        weakly-informative Normal-Inv-χ² (``mu0=0, kappa0=1, nu0=1,
        sigma2_0=1``); scale ``sigma2_0`` to your reward magnitude for more/less
        exploration.

    Returns
    -------
    RunResult
        Best candidate found plus telemetry (per-generator pulls, wider/deeper
        mix, full action log).

    Algorithm (one iteration = one budget unit):
        1. Descend from the root, at each node Thompson-sampling ``select``.
           Descend through ``DEEPEN`` actions until a ``GEN`` action is chosen
           (a childless candidate offers only ``GEN``, so descent always
           terminates in a generation).
        2. Call the chosen generator on the current node's candidate → new
           candidate; evaluate it; attach it as a child.
        3. Back-propagate the reward: update the ``GEN`` posterior of the node
           that generated (for that generator) and the ``subtree`` posterior of
           that node and every ancestor up to the root.
        4. Track the best candidate seen.
    """
    if budget <= 0:
        raise ValueError("budget must be a positive integer")
    generators = list(generate_fns.keys())
    if not generators:
        raise ValueError("generate_fns must contain at least one generator")

    _rng = _as_rng(rng)
    _prior = prior if prior is not None else NormalInvChiSqPosterior()

    root = Node(candidate=None, depth=0)

    best_candidate: Any = None
    best_reward: float = -math.inf
    gen_counts: dict[str, int] = {g: 0 for g in generators}
    wider_count = 0
    deeper_count = 0
    action_log: list[tuple[str, str, float, int]] = []

    for _ in range(budget):
        # 1. Descend to the node where generation will happen.
        path: list[Node] = [root]
        node = root
        while True:
            action = select(node, generators, _rng, _prior)
            if action.kind == "GEN":
                gen_name = action.generator
                assert gen_name is not None
                break
            # DEEPEN: descend into the chosen child and keep selecting.
            assert action.child is not None
            node = action.child
            path.append(node)

        # 2. Generate & evaluate.
        parent_candidate = node.candidate  # None at the root → fresh; else refine.
        candidate = generate_fns[gen_name](parent_candidate, _rng)
        reward = float(evaluate_fn(candidate))

        child = Node(
            candidate=candidate,
            generator=gen_name,
            reward=reward,
            depth=node.depth + 1,
            parent=node,
        )
        node.children.append(child)

        # 3. Back-propagate.
        #    GEN posterior of the generating node (per generator).
        gp = node.gen_post.get(gen_name)
        if gp is None:
            gp = _prior.copy()
            node.gen_post[gen_name] = gp
        gp.update(reward)
        #    Subtree posterior of the new node and every ancestor (incl. root).
        child.subtree_post.update(reward)
        for anc in path:
            anc.subtree_post.update(reward)

        # 4. Telemetry + best tracking.
        gen_counts[gen_name] += 1
        mode = "wider" if child.depth == 1 else "deeper"
        if mode == "wider":
            wider_count += 1
        else:
            deeper_count += 1
        action_log.append((mode, gen_name, reward, child.depth))

        if reward > best_reward:
            best_reward = reward
            best_candidate = candidate

    return RunResult(
        best_candidate=best_candidate,
        best_reward=best_reward,
        root=root,
        n_evaluations=budget,
        generator_counts=gen_counts,
        wider_count=wider_count,
        deeper_count=deeper_count,
        action_log=action_log,
    )
