# CadVerify — Human-Sim Adversarial E2E Harness (Fable-orchestrated)

**Not smoke tests. Not PR green-lights.** Hardcore power-user and org personas drive the
REAL web app through a real browser with REAL files, trying to break it and criticizing
everything, until every persona can honestly say **"holy fuck, this is great."** Then loop:
critique → Fable synthesizes → fix-builders → re-test → repeat until the bar is met.

Unit/integration tests remain regression guards. They are NOT proof. **A simulated human
driving the real surface is the proof.**

---

## 0. Surface & tooling
- **Surface:** the web app (Next 16 frontend + FastAPI backend + Postgres), driven through
  **Chromium via Playwright** (pre-installed: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`;
  never `playwright install`). Real clicks, real uploads, real navigation.
- **Persona agents are VISION-CAPABLE.** They take screenshots at every meaningful step and
  **look at them** to judge correctness — they do not trust HTTP 200s or DOM presence alone.

## 1. The two non-negotiable visual checks (the product's whole thesis)
Every core-flow persona MUST verify, by LOOKING at screenshots (not API assertions):
1. **Part fidelity** — after uploading a real STEP/IGES part, the 3D stage renders the part
   as ITSELF (the real tessellated shell), not a bounding box, not a wrong shape. The persona
   knows what it uploaded (e.g. a NIST bracket with a bore + slots) and must judge: *does the
   render actually look like that part?* A box, a blank canvas, a mangled shell, or a mismatch
   = FAIL, reported with the screenshot.
2. **Environment reaction** — after declaring a service environment (e.g. sour/H₂S, high-temp,
   offshore), the UI must VISIBLY and CORRECTLY react: non-compliant materials struck with
   cited standards (NACE/API), the makeability verdict changes, the part re-seats in context.
   Screenshot BEFORE and AFTER; the persona judges: *did the answer actually change, and is the
   change correct for that environment?* No visible/correct reaction = FAIL.

## 2. Personas (hardcore, adversarial — each tries to break it)
Each persona has a real-world mandate, a set of real files, and license to be brutal. They rate
each flow 1–5 and only 5 = "holy fuck". Anything < 5 needs a specific, reproducible critique.

- **P1 — EPC design engineer (Aramco/Exxon vendor).** Uploads real NIST PMI STEP parts (GD&T,
  tolerances, mm). Cares about: part renders correctly, DFM findings are right, sour-service
  environment strikes the right alloys with real citations, verdict is defensible, it's fast.
  Hates: a part that becomes a box, a wrong/hand-wavy verdict, fabricated numbers, slow parses.
- **P2 — Sourcing / procurement lead.** Bulk-uploads a parts manifest, wants portfolio triage
  at scale, make-vs-buy crossover, provenance. Hates: any number presented as fact that's
  actually a default/estimate, unvalidated claims, opaque math.
- **P3 — Shop owner / in-house manufacturing manager.** Configures machine inventory, expects
  per-machine makeability, gap analysis ("what machine closes the gap"), marginal cost on owned
  capital. Hates: wrong routing, a verdict that ignores their actual machines.
- **P4 — Org admin / IT.** Sets up the org, invites users, configures SSO group→role mappings,
  checks SCIM + health. Hates: broken flows, security holes, confusing setup, dead ends.
- **P5 — Skeptical CFO / exec.** Reads the glass-box cost + provenance and decides whether to
  trust it. Hates: anything opaque, overclaimed, or that can't show its work.

## 3. User-flow tree (branch every decision)
Each persona walks branches, not a happy path. Examples of branch points that MUST be exercised:
- Upload: valid STEP · valid IGES · valid STL · **the periodic-surface part that fails to parse**
  · huge file · wrong file type · empty file · inch-authored-vs-mm.
- Environment: none declared (honest withheld verdict) · sour · high-temp · offshore · switch
  between them (does the answer re-derive?).
- Machines: none owned (outsource-only) · owns the right machine (in-house) · owns a near-miss
  (gap + "what machine closes it") · steel+sour routed to an unowned 5-axis.
- Cost: default assumptions · edit an assumption (real re-cost) · bind a shop · qty crossover.
- Auth/org: signup · login (incl. brute-force lockout) · invite · accept · SSO mapping · remove
  member · non-admin hitting an admin page.
- Failure branches: backend down · degraded health · rate-limited · unsupported input.

## 4. Adversarial rubric (per flow, 1–5)
5 = "holy fuck, this is great" — flawless, fast, correct, trustworthy, nothing to nitpick.
4 = great but a real nit. 3 = works, visible rough edges. 2 = works but I'd distrust/abandon it.
1 = broken/wrong/misleading. **Score honestly and low; the whole point is to find what's < 5.**
Each < 5 finding: {persona, flow, branch, severity, what's wrong, screenshot, repro, expected}.

## 5. The loop (Fable orchestrates)
1. **Round N:** spawn persona agents (Opus, isolated worktrees, own DB+ports). Each stands up the
   live stack, drives its flows with real files, screenshots + LOOKS, scores 1–5, files findings.
2. **Synthesize:** Fable dedupes/ranks findings by severity × persona-impact.
3. **Fix:** Fable spawns fix-builders (gated + re-verified as always).
4. **Round N+1:** re-run the personas on the fixed app.
5. **Stop only when** every core flow scores 5 from every relevant persona — a genuine "holy
   fuck", not a rubber stamp. Fable does not declare victory; the personas do.

## 6. Real-file corpus (no toys)
`data/real-corpus/` (gitignored, re-fetchable): **33 real NIST PMI STEP parts** (ASME B89 MBE
PMI test cases, AP203 + AP242, GD&T/tolerances, mm) — sha256-pinned from NIST, download via
`scripts/prehuman/real_cad_corpus.py`. Plus `backend/tests/assets/cube.step`. Range 7 KB → 6 MB.
Known real gap already found (Round 0): `nist_ctc_04_asme1_rd.stp` → gmsh "Impossible to mesh
periodic surface" → generic 400. Real parts find real bugs; that is the point.

## 7. Honesty
Screenshots are the evidence. No persona "passes" a flow it didn't actually drive and look at.
A found bug is a WIN, not a failure to hide. Fabricated praise is the only real failure.
