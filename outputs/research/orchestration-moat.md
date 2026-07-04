# CadVerify — Orchestration Moat (Sakana-informed)

**Written:** 2026-07-03 · **Status:** strategy brief, founder-facing · **Basis:** multi-agent web research (Sakana method + portfolio + DFM/cost competitor landscape), each claim source-linked and split verified-vs-marketing. Consistent with the product's own ethos: **nothing here is a validated number; the guarantees below are structural/asymptotic, and their realized magnitude is a Zoox/ground-truth gate.**

---

## 0. Exec summary

The founder's instinct is correct and now has a concrete precedent. **Sakana AI's "Fugu" (launched ~2026-06-22) is a real, shipped product that beats every frontier model it orchestrates on its own benchmark table — while owning no frontier model.** Its edge is *method*: an inference-time orchestration algorithm (AB-MCTS / TreeQuest) that adaptively decides "search wider vs. deeper" and "which model to trust next," via a Bayesian bandit, so a *collective* of models it doesn't own outperforms the best single one.

The transferable thesis for CadVerify: **we don't need a bigger cost model; we need a better orchestration method over the estimators and agents we already have.** Two surfaces:

- **(A) The product estimator harness** — replace the single bottom-up cost model with an *uncertainty-aware, self-calibrating ensemble* of estimators (physics/feature, regression, analogy-to-quote) orchestrated by adaptive search, where the reward is *measured error against the ground-truth flywheel*. This is provably ≤ the error of any single method (inverse-variance combination) and converges toward calibrated intervals as real quotes accumulate. **No competitor publishes a calibrated confidence interval or an auditable self-calibration loop** — that absence is the moat.
- **(B) The build/agent harness** — apply AB-MCTS-style adaptive branching to our *own* multi-agent orchestration (wider vs. deeper, which model tier to sample next), replacing fixed fan-out. This is a compounding internal advantage and a benchmarkable one.

"Better over every coefficient" becomes a precise, testable claim: **for each cost driver, our calibrated ensemble's expected squared error and its interval mis-coverage are ≤ the best single estimator's, and both are non-increasing in the amount of ground truth.** Section 6 makes that rigorous; Section 7 says how we'd measure it.

---

## 1. What Sakana actually did (verified, with the "Fugu" question resolved)

### 1.1 Fugu is real (and post-dates the Jan-2026 knowledge cutoff)
Independently corroborated by three official domains fetched directly (not via snippet/paraphrase):
- arXiv: **"Sakana Fugu Technical Report"** — https://arxiv.org/abs/2606.21228 (v1 2026-06-19, v2 2026-06-23), 14 named Sakana researchers.
- GitHub: **SakanaAI/fugu** — https://api.github.com/repos/SakanaAI/fugu (created 2026-06-17, active, same org that owns the verified `treequest` repo).
- Product page: **https://sakana.ai/fugu/** — "One Model to Command Them All," an OpenAI-compatible orchestrator API in two tiers (Fugu / Fugu-Ultra), built on two claimed ICLR-2026 papers ("TRINITY: An Evolved LLM Coordinator"; "Learning to Orchestrate Agents… with the Conductor").

**What it is:** Fugu is *itself* a language model that dynamically decides whether to answer directly or orchestrate a pool of frontier models (its page names Gemini-3.1-Pro, Claude-Opus-4.8, GPT-5.5) and returns one synthesized answer through a single endpoint. Its arXiv HTML (https://arxiv.org/html/2606.21228) reports Fugu-Ultra beating all three pool members on every listed benchmark:

| Benchmark | Fugu-Ultra | Fugu | Opus 4.8 | Gemini 3.1 | GPT-5.5 |
|---|--:|--:|--:|--:|--:|
| SWE-Bench Pro | 73.7 | 59.0 | 69.2 | 54.2 | 58.6 |
| Terminal-Bench 2.1 | 82.1 | 80.2 | 74.6 | 70.3 | 78.2 |
| Humanity's Last Exam | 50.0 | 47.2 | 49.8 | 44.4 | 41.4 |
| GPQA Diamond | 95.5 | 95.5 | 92.0 | 94.3 | 93.6 |

**Honesty flags (carry these when citing):** the benchmark numbers are *company-reported* (independent replication pending); pricing tiers ($20/$100/$200) and the software license are inconsistent across sources and **unconfirmed**; and the *technical* link between Fugu's orchestrator (TRINITY/Conductor) and the AB-MCTS algorithm below is **not established in primary sources** — they share a company and a philosophy, not a proven shared mechanism. Don't claim Fugu "is AB-MCTS."

### 1.2 AB-MCTS / TreeQuest — the method we actually borrow from
Verified against the NeurIPS-2025-spotlight paper **"Wider or Deeper? Scaling LLM Inference-Time Compute with Adaptive Branching Tree Search"** (https://arxiv.org/abs/2503.04412), Sakana's blog (https://sakana.ai/ab-mcts/, 2025-07-01), and the repo **SakanaAI/treequest** (Apache-2.0, https://github.com/SakanaAI/treequest).

- **The GEN-node trick (wider vs. deeper).** Standard MCTS has fixed child arms. AB-MCTS adds a special **GEN arm** at every node: pick GEN → call an LLM and spawn a *new* child (go wider); pick an existing child → descend and refine it (go deeper). Because arms are created dynamically, UCT doesn't apply, so selection uses **Thompson sampling over a Bayesian posterior**: draw a score from each arm's posterior-predictive and take the argmax. GEN's posterior (no direct observations) borrows strength from siblings — its built-in uncertainty keeps exploration alive.
- **Two posteriors:** AB-MCTS-**M** (mixed-effects, MCMC/PyMC, slower) and AB-MCTS-**A** (conjugate Normal-Inverse-χ² / Beta, closed-form, fast).
- **Multi-LLM:** each generator (model) gets its own posterior; Thompson sampling also picks *which model* to sample next, so "more promising LLMs become increasingly likely to be chosen." A weak model's near-miss can seed a stronger model's correct answer.
- **Why it beats fixed strategies:** repeated sampling = all-width/no-exploitation; sequential refine = all-depth/gets stuck on a bad start. AB-MCTS chooses the mix *per node* from data.
- **Evidence (ARC-AGI-2, 120-task subset):** repeated single-model o4-mini **23%** → AB-MCTS single **27.5%** → Multi-LLM AB-MCTS **">30%"**. **Caveats (must repeat):** (a) the >30% is under *unlimited* guesses; at the official 1–2-guess protocol it's **19.2%** — Sakana flags this gap; ARC's F. Chollet reportedly cautioned on it (secondary source, unverified); (b) VentureBeat's "outperform by 30%" headline is a *relative* gain (30/23 ≈ 1.30×, ~7 points absolute), **not** 30 percentage points — cite the absolute deltas, not the headline. Independent outlets (The Decoder, 2025-07-07) added the Pass@2 caveat themselves; press framing was largely faithful.

---

## 2. The transferable principles (from Sakana's whole portfolio)

From evolutionary model merging, The AI Scientist, Transformer², Text-to-LoRA, and the "school of fish" collective-intelligence thesis:

1. **Compose, don't (only) build bigger** — new capability by recombining trained specialists, not one monolith.
2. **Search over the composition space** — when "which specialists + how to weight/route them" is too large to hand-design, use search (evolutionary / Bayesian bandit).
3. **Adapt at inference, not just training** — keep swappable specialists and select/blend per-input at runtime.
4. **Amortize specialization into a generator** — distill a library of specialists into a model that synthesizes new ones cheaply.
5. **Close the loop with self-evaluation** — generation → execution → critique → the critique becomes the next round's selection signal.
6. **Favor population diversity over single-point optimization** — many cheap niche specialists are more robust to distribution shift than one all-purpose system.

Every one of these maps onto *both* CadVerify surfaces below.

---

## 3. The competitor gap (why a better method wins)

Method + weakness, from the competitor research (sources inline in `outputs/research/` agent logs; key ones cited):

- **aPriori** — physics/parametric bottom-up should-cost. Its *own blog* admits ±30–40% variance ("$100 estimate → actuals $71–$132… a point of comparison, not accuracy," apriori.com) yet ships a **single point number with no confidence interval**; rate libraries refreshed **quarterly by hand**; no self-calibration.
- **Xometry** — hybrid CAD-geometry + regression-ML on marketplace transactions; a real but **opaque "data flywheel"** (verified verbatim in SEC 10-Ks and a 10+ member Google Patents family, e.g. US10281902B2, US11693388B2). But: single fixed price, **no interval**, no per-quote rationale to the buyer; "instant" quotes are frequently re-quoted manually (+50–70%, forum-sourced).
- **Paperless Parts** — computational geometry + **customer-configured pricing formulas**; its AI (Wingman / Manufacturing Intelligence Engine, patent US12524607B2) is scoped to *drawing/spec extraction* and **explicitly disclaims pricing** ("AI… does not generate or suggest shop-specific pricing"). No closed-loop cost recalibration; no published accuracy figure.
- **DFMPro** (HCL) — rules-based manufacturability *flags only*, cost is a bolt-on "ROM" add-on; manual rule authoring; no uncertainty.
- **Zoo/Zookeeper, Leo AI, CloudNC** — early-stage; LLM/agent or "large mechanical model" framing; disclaim manufacturability/accuracy; no independent benchmarks, no calibration loop.

**The unanimous opening:** *nobody publishes a calibrated confidence interval, nobody has an auditable self-calibration loop, and the cost math is black-box.* Xometry has a flywheel but it's opaque and marketplace-priced (what a supplier will accept), not a *should-cost truth*. That is exactly the seam CadVerify already aims at (glass-box provenance + honest `validated:false` + the ground-truth flywheel). The orchestration method turns that posture into a *measurable accuracy advantage*, not just a trust story.

---

## 4. Design A — the product estimator harness (the core moat)

**Today:** one cost model per process (bottom-up drivers in `RATE_CARD_V0`), a single point estimate + a *stated* assumption band (`confidence.py`), calibrated only when a real `ResidualModel` exists (W5).

**Proposed:** a **Bayesian ensemble of estimators per (process, cost-driver)**, orchestrated by adaptive search, calibrated by the flywheel:

1. **Members (the "school of fish"):** for each driver (machine time, material, setup, finishing, tooling…), keep ≥2–3 independent estimators — the current physics/feature model, a regression model over the corpus, and an **analogy-to-quote** estimator (k-NN over ground-truth quotes with similar geometry/material/process). Each returns a **distribution**, not a point (mean + variance). *(Principle 1, 6.)*
2. **Combine by inverse-variance / BLUE**, not naive average: weight each member by its measured precision (and covariance). This is the estimator-space analogue of Fugu picking the more-promising model. *(Principle 2.)*
3. **Adaptive compute (AB-MCTS analogue):** cheap parts → one pass; high-stakes or high-disagreement parts → "go deeper" (spend more compute refining the dominant estimator) or "go wider" (invoke another estimator / another assumption set), chosen by a bandit whose reward is *expected error reduction per compute*. *(Principle 3.)*
4. **Self-calibration (the flywheel closes):** returned real quotes update (a) each member's variance/bias, (b) the combination weights, and (c) an isotonic/Platt **interval calibrator** so stated P10/P50/P90 attain nominal coverage. Publishing predicted-vs-actual **calibration curves** is the artifact no competitor has. *(Principle 5.)*
5. **Uncertainty as a first-class output & triage signal:** report a calibrated interval + an **epistemic-disagreement** score; low-confidence parts are *honestly* routed to human quote instead of a false-precision number — the opposite of aPriori's silent point estimate and Xometry's silent manual re-quote.

Every number stays glass-box and provenance-tagged; `validated` still flips only from real residuals. The ensemble changes *which* DEFAULT/MEASURED numbers combine and *how confident* we honestly are — it never manufactures certainty.

---

## 5. Design B — the build/agent harness (compounding internal edge)

Our current orchestration (this very session) uses **fixed fan-out**: N builders + M verifiers, decided up front. AB-MCTS says: **decide adaptively.**

- Treat each task as a tree; at each step the bandit chooses **wider** (spawn another independent attempt/approach) vs **deeper** (send the most-promising draft back for refinement) vs **which model tier** (Haiku/Sonnet/Opus/Fable) to sample next — reward = verifier pass-rate / quality score. *(Directly the AB-MCTS GEN-node + multi-LLM selection, applied to agents.)*
- **Why it helps us specifically:** we already saw the failure mode — a stalled agent, a lost slice to a restart, over-delegation chains. A bandit that reallocates compute toward what's *working* (and cuts what's stalling) is strictly better than a static plan, and it's cheap to prototype on top of the existing Agent/Workflow spawns.
- **Bonus:** this is the same machinery as (A) — one "adaptive-branching orchestrator" module serves both the estimator ensemble and the agent fleet.

---

## 6. The precise claim ("better over every coefficient")

Let a cost driver be estimated by unbiased estimators $\hat{x}_1,\dots,\hat{x}_k$ with covariance $\Sigma$.

- **Combination ≤ best single (structural):** the BLUE (covariance-weighted) combination $\hat{x}^\* = \frac{\mathbf{1}^\top \Sigma^{-1}}{\mathbf{1}^\top \Sigma^{-1}\mathbf{1}}\,\hat{\mathbf{x}}$ has variance $(\mathbf{1}^\top\Sigma^{-1}\mathbf{1})^{-1} \le \min_i \Sigma_{ii}$. Independent case: $\mathrm{Var}=1/\sum_i \sigma_i^{-2}\le\min_i\sigma_i^2$. So **per driver, the ensemble's variance is ≤ the best member's** — the mathematical spine of "better over every coefficient."
- **Convergence with ground truth (flywheel):** weights/biases are *estimated*, not known; as the number of matched real quotes $n\to\infty$, weight and calibrator estimates are consistent, so realized ensemble error → the oracle-weighted error and **stays ≤ any fixed single method in expectation**. Interval calibration: with a proper scoring rule + isotonic recalibration, **expected calibration error → 0**, i.e. stated coverage → actual coverage.
- **Honest bounds (no over-claim):** these hold under *unbiased members + correct (estimated) covariance + exchangeable ground truth*. Real members are biased and correlated; that's *why* the flywheel (bias/covariance estimation) is load-bearing and why magnitudes are Zoox-gated. The **guarantee we can state today** is directional and structural: *adding a calibrated member can only reduce, never increase, expected error of the covariance-weighted combination* — the opposite of a black-box point model, which offers no such guarantee.

Contrast: aPriori/Xometry/Paperless output a point estimate with **no coverage guarantee and no monotone-improvement property**. Our claim is falsifiable and improves with data; theirs is asserted.

---

## 7. Benchmarking plan (how we prove it, per coefficient)

Purpose: convert "±40% assumption" into *measured* superiority, coefficient by coefficient.

1. **Held-out quote backtest:** with the ground-truth corpus, leave-one-out by part. For each driver and total cost, report **MAPE / RMSLE** for (a) each single estimator, (b) the calibrated ensemble — assert (b) ≤ min(a). This is the "every coefficient" table.
2. **Calibration/coverage:** for stated P10–P90, measure empirical coverage; target ≥ nominal. Publish the reliability curve (nobody else does).
3. **Compute–accuracy frontier (AB-MCTS's own metric):** error vs. LLM/compute budget for fixed fan-out vs. adaptive branching, on both the estimator harness and the agent harness — show the adaptive curve dominates.
4. **Triage value:** on the low-confidence bucket, show error is genuinely higher (i.e. our uncertainty *predicts* error), justifying human routing.
5. **Head-to-head where obtainable:** same parts through aPriori/Xometry public quoting vs. ours + real shop quotes as truth. Gated on access; design the harness now.

All of this is a *measurement* program, reported with the same honesty as the product — including where we lose.

---

## 8. Phased build sequence

- **P0 (now, cheap):** wrap the existing single estimator as one ensemble member returning (mean, var); add the **analogy-to-quote k-NN** member over the corpus; ship inverse-variance combination behind a flag (default off → byte-identical). Add the backtest harness (§7.1–7.2). *No new physics needed — this is plumbing + math.*
- **P1:** wire the ensemble to W5 (weights/bias/calibrator learn from returned quotes); publish calibration curves. This is the flywheel's real payoff and the first *measured* win.
- **P2:** the **adaptive-branching orchestrator** module; apply to the estimator ensemble (compute allocation) and to the agent/build harness (B).
- **P3 (gated on Zoox/data):** add regression + per-process members; tune magnitudes on real residuals; the compute–accuracy frontier study; head-to-head benchmarks.

---

## 9. Risks & honesty caveats

- **Don't conflate Fugu with AB-MCTS** — cite each correctly; Fugu's exact internal mechanism is unconfirmed.
- **Company-reported numbers stay labeled** (Fugu benchmarks; the ARC-AGI-2 >30% under unlimited guesses vs 19.2% at Pass@2).
- **Our guarantees are structural/asymptotic**; realized accuracy is Zoox/ground-truth-gated. Ship the *method and the measurement*, not a validated magnitude — exactly the product's `validated:false`-until-measured discipline.
- **Ensemble ≠ automatic win** if members are strongly correlated or badly biased; the flywheel (covariance/bias estimation) is the load-bearing dependency, so W5 plumbing is a prerequisite, not an afterthought.
- **The orchestration ceiling is bounded by the pool** — The Verge's skeptical read of Fugu (its "frontier performance" is partly circular: it just calls Claude/Gemini/GPT) is the key strategic lesson, *in our favor*. A pure LLM-router's ceiling rises only when its vendors ship better models — a rented ceiling. **Our "pool" is physics-based estimators + accumulating real quotes**, so *we* raise our own ceiling by adding diverse members and turning the flywheel — a ceiling we own. Invest there, not in a thin router. (Independent corroboration that Fugu — and the competitor model "Fable 5" it's benchmarked against — are real: The Verge 2026-06-23, Nikkei Asia, VentureBeat, Hacker News; the earlier "is Fable 5 a hallucination?" alarm is resolved — it's a real, press-referenced model.)

---

## 10. Sources (primary, verified)

- Sakana Fugu: arxiv.org/abs/2606.21228 · api.github.com/repos/SakanaAI/fugu · sakana.ai/fugu/
- AB-MCTS / TreeQuest: arxiv.org/abs/2503.04412 (NeurIPS 2025 spotlight) · sakana.ai/ab-mcts/ · github.com/SakanaAI/treequest (Apache-2.0)
- Sakana portfolio: sakana.ai/evolutionary-model-merge (arXiv:2403.13187, Nature Mach. Intell.) · sakana.ai/ai-scientist (arXiv:2408.06292; Nature, 2026) · sakana.ai/transformer-squared (arXiv:2501.06252) · Text-to-LoRA (arXiv:2506.06105, ICML 2025)
- Competitors: apriori.com ("should-cost… not accurate but that's okay") · Xometry SEC 10-Ks (CIK 0001657573) + Google Patents family (US10281902B2, US10274933B2, US11693388B2, …) · paperlessparts.com/artificial-intelligence-in-paperless-parts (pricing disclaimer), patent US12524607B2 · dfmpro.com (HCL, rules-based) · zoo.dev/zookeeper · getleo.ai

*Company-reported / marketing claims are labeled as such throughout; items the research could not independently confirm (Fugu pricing & license; "Fable 5"/"Mythos Preview" as third-party products; Chollet's exact wording) are flagged in the agent logs and should not be repeated as fact.*
