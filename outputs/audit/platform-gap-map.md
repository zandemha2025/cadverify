# CadVerify — Full-Platform Gap Map (5-lens expert audit, synthesized)

**The honest headline:** the *core loop* is genuinely real and differentiated — but it's a **single-seat demo of a real idea, not an enterprise platform**, and the numbers themselves have correctness gaps a real cost/manufacturing engineer catches in minutes. Against 2026 category table stakes it's **~15–20% of a platform.** The gaps cluster into six themes.

---

## ✅ What's genuinely REAL (verified by running it)
- **Glass-box cost architecture** — itemized Σ=unit_cost invariant, provenance tags (MEASURED/USER/DEFAULT/SHOP), honest "not-yet-validated" confidence, sound make-vs-buy crossover math.
- **Per-shop calibration is substantive** (not a stub) — a real shop profile swings a part 2.3× with every line re-tagged SHOP.
- **DFM is a real deterministic geometry engine** — wall thickness, draft, overhangs, undercuts, rotational symmetry, feature fit, all genuinely computed with citations; earlier routing bugs fixed.
- **Auth core is above-average** — Argon2id, HMAC-indexed API keys, signed server-gated sessions, RBAC with a CI guardrail, exportable audit log.
- API + persistence layer + 7 clean Alembic migrations + deploy topology (on paper).

## ❌ The six gap themes (what stops it being real/buyable)

### 1. The numbers aren't right yet (correctness) — the trust blocker
- **CNC cost is FLAT across quantity** (verified identical at qty 100 / 1k / 100k). Real machined parts drop 30–60% from 100→10k. **This breaks the make-vs-buy crossover — the platform's core value prop rests on a machining cost that doesn't behave like machining.**
- **No tolerance / GD&T / surface-finish input anywhere** — the #1 cost driver after material+size. Identical geometries at ±0.1 vs ±0.005 cost the same. A sourcing/QE org won't trust that.
- **Systematic under-costing** — hull-based CNC stock (~2.6× low roughing), no feature-based cycle time, no programming/NRE/inspection, no secondary-finishing cost lines. Material mislabels (CNC "steel" → sheet stock); several $/kg 2–5× off.
- **±40% is asserted, not measured (n=0)** — shop-rate variance alone is 2.3×, so honest uncalibrated uncertainty is ~±2–3×.

### 2. The DFM over-flags — the exact trust-killer you saw on screen
- **"78 flags · 15 critical" is summed across all 21 processes** and *contradicts the DFM-clean recommended process*. Reproduced 58/11 on a bracket whose recommended process has 0 flags. **A real engineer's trust dies on the first part.** (Fixable: scope flags to the recommended process.)
- Verdicts are **orientation-sensitive** (rotate the STL 90° → flag counts change). Tolerance/GD&T subsystem is **dead code**. Feature detection is **holes+flats only** (no threads/pockets). CNC-3axis falsely marked "not DFM-ready" on routinely machinable parts.

### 3. The flagship output is ephemeral — the #1 product hole
- **The should-cost decision is computed in-memory and thrown away** (routes.py: "nothing is persisted"). It **can't be saved, PDF-exported, shared, versioned, or compared.** The product's headline deliverable leaves no artifact a buyer can keep. PDF export is DFM-only; no cost report.

### 4. It's single-seat, not a platform
- **No org / team / tenant model in the schema** — "there is no team to sell seats to." No quote/RFQ/order object (the buyer workflow Paperless/Xometry own). Batch is **DFM-only, not cost** (no portfolio should-cost — the core aPriori/3D Spark enterprise use case). No admin UI. No AI/copilot in an AI-native category.

### 5. The plumbing won't survive real users (production-readiness)
- **Engine memory bomb (P0):** GeometryContext.build allocates **19 GB RAM on an ordinary 37k-face part** (pure-Python ray casting; sample threshold is backwards) → OOM-kills a normal machine. This is the single biggest scaling blocker.
- **The async tier is silently dead** — no Redis, no worker running; batch/webhooks/reconstruction orphan; **`/health` falsely reports OK.** Image-to-mesh can't run (torch absent; default egresses images to Replicate). S3 batch input is `NotImplementedError`. Tests all run on SQLite (false green CI).

### 6. Enterprise/compliance is a scaffold (blocks Zoox/Aramco)
- **SAML is 100% mocked** (never tested vs a real IdP) and its config path is broken. **No multi-tenant isolation** (admin is global → cross-tenant exposure). **No encryption at rest** (disqualifying for ITAR). No SOC2/pen-test artifacts. Webhook SSRF. Every SSO login mints a new orphan API key. No security headers.

---

## What only a real human closes (the validation queue)
- **Cost/DFM number correctness** → the **Zoox Head of Manufacturing** on real parts w/ real quotes (load into groundtruth.py held-out eval). *No agent can self-certify this.*
- **SAML vs a real IdP + a pen test** → a security engineer / accredited firm.
- **SOC 2 readiness** → a qualified auditor. **ITAR/export-control** → legal.
- **Load/soak test** on real Postgres+Redis+worker hardware → SRE.

## Honest priority (if the goal is a credible demo → then a platform)
1. **Fix the demo-killers first** (they make even the demo fail): DFM over-flag scoping, the flat-CNC-cost that breaks the crossover, the 19 GB memory bomb.
2. **Persist + export + share the cost decision** (the flagship artifact).
3. **Deepen the cost model toward trust** (tolerances, volume/learning, feature-based cycle, real stock) — then validate with Zoox.
4. **Then the platform/enterprise layer** (org/tenant model, portfolio-cost batch, real async tier, encryption/SOC2/SAML).

*Sources: outputs/audit/{audit-cost, audit-dfm, audit-product, audit-enterprise, audit-arch}.md*
