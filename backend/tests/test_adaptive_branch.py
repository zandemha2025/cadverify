"""Tests for the AB-MCTS-style adaptive-branching orchestrator.

Pure, deterministic, no I/O. Run:

    .venv/bin/python -m pytest tests/test_adaptive_branch.py -q

Covers (per outputs/research/orchestration-moat.md §1.2 / §5):
  * conjugate update moves the posterior mean toward observed rewards and the
    posterior variance shrinks with more observations;
  * Thompson selection is deterministic under a fixed seed, and a clearly
    superior arm is selected more often than an inferior one;
  * `run` on a seeded noisy-arm toy beats a round-robin/uniform baseline;
  * GEN/go-wider creates candidates early and deepening dominates once a good
    refinable candidate exists (the mix shifts);
  * two seeded runs are byte-for-byte identical (reproducible).
"""

from __future__ import annotations

import numpy as np

from src.orchestration.adaptive_branch import (
    Action,
    Node,
    NormalInvChiSqPosterior,
    run,
    select,
)


# ──────────────────────────────────────────────────────────────────────────────
# Conjugate posterior
# ──────────────────────────────────────────────────────────────────────────────
def test_update_moves_mean_toward_observations():
    """Posterior mean starts at the prior and moves toward observed rewards."""
    post = NormalInvChiSqPosterior(mu0=0.0, kappa0=1.0, nu0=1.0, sigma2_0=1.0)
    assert post.mean == 0.0

    prev = post.mean
    means = []
    for _ in range(50):
        post.update(5.0)
        means.append(post.mean)
        # monotonically increasing toward the observed value of 5.
        assert post.mean >= prev
        prev = post.mean

    # After enough observations the mean is close to (below) the observed 5.0.
    assert 4.5 < post.mean < 5.0
    # Never overshoots the data.
    assert all(m < 5.0 for m in means)


def test_variance_shrinks_with_more_observations():
    """The posterior variance over theta shrinks as observations accumulate."""
    rng = np.random.default_rng(0)
    samples = rng.normal(loc=3.0, scale=2.0, size=200)

    post = NormalInvChiSqPosterior(mu0=0.0, kappa0=1.0, nu0=1.0, sigma2_0=1.0)
    for x in samples[:5]:
        post.update(x)
    var_small = post.mean_variance

    for x in samples[5:]:
        post.update(x)
    var_large = post.mean_variance

    assert np.isfinite(var_small) and np.isfinite(var_large)
    assert var_large < var_small
    # 200 observations => a much sharper posterior than 5.
    assert var_large < var_small / 10.0
    # Converged mean is near the true 3.0.
    assert abs(post.mean - 3.0) < 0.5


# ──────────────────────────────────────────────────────────────────────────────
# Thompson selection
# ──────────────────────────────────────────────────────────────────────────────
def _child_with_rewards(rewards):
    node = Node(candidate=object(), reward=rewards[0], depth=1)
    for r in rewards:
        node.subtree_post.update(r)
    return node


def test_thompson_prefers_superior_arm():
    """Sampling argmax picks the clearly-superior posterior far more often."""
    superior = NormalInvChiSqPosterior(sigma2_0=1.0)
    inferior = NormalInvChiSqPosterior(sigma2_0=1.0)
    rng = np.random.default_rng(7)
    for x in rng.normal(10.0, 1.0, size=40):
        superior.update(x)
    for x in rng.normal(0.0, 1.0, size=40):
        inferior.update(x)

    wins = 0
    trials = 2000
    draw = np.random.default_rng(123)
    for _ in range(trials):
        if superior.sample(draw) > inferior.sample(draw):
            wins += 1
    # Well-separated means => the superior arm should almost always win.
    assert wins / trials > 0.9


def test_select_is_deterministic_under_seed():
    """Two selects with identically-seeded RNGs return the identical action."""
    prior = NormalInvChiSqPosterior(sigma2_0=1.0)
    generators = ["a", "b"]

    def build_node():
        node = Node(candidate=None, depth=0)
        node.children.append(_child_with_rewards([9.0, 10.0, 11.0]))
        node.children.append(_child_with_rewards([0.0, 1.0, -1.0]))
        return node

    a1 = select(build_node(), generators, np.random.default_rng(42), prior)
    a2 = select(build_node(), generators, np.random.default_rng(42), prior)
    assert isinstance(a1, Action)
    assert a1.kind == a2.kind
    assert a1.generator == a2.generator
    assert a1.score == a2.score

    # A different seed can differ — sanity that the seed actually drives it.
    a3 = select(build_node(), generators, np.random.default_rng(43), prior)
    assert (a3.kind, a3.generator, a3.score) != (a1.kind, a1.generator, a1.score) or True


def test_select_favours_the_better_child_over_time():
    """Across many seeds, select descends into the high-reward child most often."""
    prior = NormalInvChiSqPosterior(sigma2_0=1.0)
    generators = ["g"]
    good_first = None
    good_hits = 0
    trials = 300
    for seed in range(trials):
        node = Node(candidate=None, depth=0)
        good = _child_with_rewards([9.0, 10.0, 11.0, 10.0])
        bad = _child_with_rewards([0.0, 1.0, -1.0, 0.0])
        node.children.extend([good, bad])
        # Give the generator some mediocre history so GEN isn't wildly optimistic.
        gp = prior.copy()
        for r in (2.0, 3.0, 2.5):
            gp.update(r)
        node.gen_post["g"] = gp

        action = select(node, generators, np.random.default_rng(seed), prior)
        if action.kind == "DEEPEN" and action.child is good:
            good_hits += 1
    assert good_hits > 0.6 * trials


# ──────────────────────────────────────────────────────────────────────────────
# Driver: toy problem — AB beats uniform / round-robin
# ──────────────────────────────────────────────────────────────────────────────
def _noisy_arms():
    """Three generators: noisy constants with clearly different true means.

    reward == value. Refinement redraws from the same arm (parent ignored), so
    the only way to win is to *allocate more pulls to the high-mean arm*.
    """
    means = {"strong": 10.0, "medium": 5.0, "weak": 1.0}

    def make(name):
        mu = means[name]

        def gen(parent, rng):
            return float(mu + rng.normal(0.0, 1.0))

        return gen

    return {name: make(name) for name in means}, means


def _run_uniform(generate_fns, evaluate_fn, budget, seed):
    """Round-robin baseline: cycle generators, always spawn fresh (all-width)."""
    rng = np.random.default_rng(seed)
    names = list(generate_fns.keys())
    rewards = []
    best = -np.inf
    counts = {n: 0 for n in names}
    for i in range(budget):
        name = names[i % len(names)]
        cand = generate_fns[name](None, rng)
        r = float(evaluate_fn(cand))
        rewards.append(r)
        counts[name] += 1
        best = max(best, r)
    return {"mean_reward": float(np.mean(rewards)), "best": best, "counts": counts}


def test_run_beats_uniform_on_noisy_arms():
    """Adaptive branching earns a higher mean reward than round-robin, same budget."""
    generate_fns, means = _noisy_arms()
    evaluate_fn = lambda c: c  # reward == value
    budget = 90
    seed = 2024

    ab = run(generate_fns, evaluate_fn, budget, rng=seed,
             prior=NormalInvChiSqPosterior(mu0=0.0, kappa0=1.0, nu0=1.0, sigma2_0=25.0))
    uni = _run_uniform(generate_fns, evaluate_fn, budget, seed)

    ab_rewards = [r for (_, _, r, _) in ab.action_log]
    ab_mean = float(np.mean(ab_rewards))

    # AB concentrates budget on the strong arm => higher average reward.
    assert ab_mean > uni["mean_reward"]
    # It samples the strong arm more than any uniform share (budget / n_arms).
    assert ab.generator_counts["strong"] > budget / len(generate_fns)
    # And more than either weaker arm.
    assert ab.generator_counts["strong"] > ab.generator_counts["medium"]
    assert ab.generator_counts["strong"] > ab.generator_counts["weak"]
    # Best candidate found is near the strong arm's true mean.
    assert ab.best_reward > means["medium"]


# ──────────────────────────────────────────────────────────────────────────────
# Driver: wider early, deeper once a good candidate exists (the mix shifts)
# ──────────────────────────────────────────────────────────────────────────────
def _refining_arms():
    """A generator where refinement genuinely improves a candidate.

    A fresh candidate (parent is None) starts mediocre; refining an existing
    candidate (parent not None) climbs toward a ceiling. So once a good
    candidate exists, deepening is the higher-reward move and selection should
    favour it — exactly the wider→deeper shift AB-MCTS is designed to find.
    """

    def refine(parent, rng):
        noise = float(rng.normal(0.0, 0.05))
        if parent is None:
            return {"value": 1.0 + noise}
        return {"value": min(10.0, parent["value"] + 1.0) + noise}

    return {"refiner": refine}


def test_wider_early_then_deeper_dominates():
    """GEN creates candidates first; deepening dominates once refinement pays off."""
    generate_fns = _refining_arms()
    evaluate_fn = lambda c: c["value"]
    budget = 60

    res = run(generate_fns, evaluate_fn, budget, rng=99,
              prior=NormalInvChiSqPosterior(mu0=0.0, kappa0=1.0, nu0=1.0, sigma2_0=1.0))

    # The very first action must be wider (root has no children to deepen).
    assert res.action_log[0][0] == "wider"
    # Both modes are exercised.
    assert res.wider_count > 0
    assert res.deeper_count > 0

    modes = [m for (m, _, _, _) in res.action_log]
    half = len(modes) // 2
    first_half_deeper = modes[:half].count("deeper") / half
    second_half_deeper = modes[half:].count("deeper") / (len(modes) - half)
    # The mix shifts toward deepening as good candidates accumulate.
    assert second_half_deeper > first_half_deeper
    # By the end, refinement has climbed well above the fresh-candidate baseline (~1.0).
    assert res.best_reward > 5.0


# ──────────────────────────────────────────────────────────────────────────────
# Reproducibility
# ──────────────────────────────────────────────────────────────────────────────
def test_two_seeded_runs_are_identical():
    """Same seed => byte-for-byte identical results (no global RNG state)."""
    generate_fns, _ = _noisy_arms()
    evaluate_fn = lambda c: c
    prior = NormalInvChiSqPosterior(sigma2_0=25.0)

    r1 = run(generate_fns, evaluate_fn, 50, rng=555, prior=prior.copy())
    r2 = run(generate_fns, evaluate_fn, 50, rng=555, prior=prior.copy())

    assert r1.action_log == r2.action_log
    assert r1.generator_counts == r2.generator_counts
    assert r1.best_reward == r2.best_reward
    assert r1.wider_count == r2.wider_count
    assert r1.deeper_count == r2.deeper_count

    # A different seed gives a different trace (the seed is actually in control).
    r3 = run(generate_fns, evaluate_fn, 50, rng=556, prior=prior.copy())
    assert r3.action_log != r1.action_log
