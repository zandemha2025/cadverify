# Wave B — W6 Portfolio Exposure (Programs) — Scorecard

- **Persona:** P2 — Sourcing / Procurement lead (portfolio / risk view)
- **Workflow:** W6 — portfolio exposure
- **Surface driven:** `/verify` → **Programs** screen (`src/components/verify/program-screen.tsx`, `ProgramScreen`),
  backed by `GET /api/v1/catalog/portfolio` + `PUT /api/v1/part-context/{mesh_hash}`.
- **Stack:** worktree `waveB-w6b` @ 14ce7f0, backend :8047 (postgres:true), frontend :3047. Date 2026-07-10.
- **Method:** real browser (Playwright/chromium headless), real clicks/typing. Signed up, costed 4 real parts
  (cube.step, bracket_A.stl, bracket_A_rev.stl, torus_unrelated.stl), built 2–3 programs, declared volumes,
  edited/unassigned, checked withheld + empty + isolation branches. Numbers reconciled against the raw
  `/catalog/portfolio` JSON and hand math.
- **Screenshots:** `waveB-shots/w6-*.png`

> Note (honesty): a mid-run 429 (portfolio GET rate-limited at 60/hour) was tripped by my API polling.
> To finish driving the UI I restarted the backend with the code's documented E2E switch
> `RATE_LIMIT_DISABLED=1` (dev-only; production keeps limits). The rate-limit itself is reported as a real
> finding below — the UI refetches the whole portfolio on mount and after **every** mutation.

---

## Reconciliation (Data fidelity — the core of W6)

Raw `/catalog/portfolio` after building the portfolio (verbatim):

| Part | unit cost | declared vol | part `annualized_cost_usd` | hand check |
|---|---|---|---|---|
| cube.step | $30.00 (fdm, MODEL) | 5000 | **150000** | 30×5000 ✓ |
| bracket_A.stl | $40.00 (dlp, MODEL) | 2000 | **80000** | 40×2000 ✓ |
| torus_unrelated.stl | $37.89 (fdm, MODEL) | 1200 | **45468** | 37.89×1200 ✓ |
| bracket_A_rev.stl | $40.00 (dlp, MODEL) | 500 | **20000** | 40×500 ✓ |

Program rollups (`summary.programs[]`) vs index cards vs hand math — **all three agree exactly**:
- Hydraulic actuator = 150000 + 80000 = **230000** → backend rollup 230000, card "$230,000/yr" ✓
- Compressor skid = 45468 + 20000 = **65468** → backend rollup 65468, card "$65,468/yr" ✓
- After editing cube 5000→6000: part 180000, program 260000 ✓ (recomputed live)
- After unassigning bracket_A: program parts=1, exposure 180000 (cube only) ✓
- Assigning a part with NO volume (Valve body): part annual = null, program exposure = null → UI "exposure withheld" ✓

**Provenance preserved at portfolio level:** each unit cost carries a `● MODEL` chip (not MEASURED),
each program/volume a `● USER` dot, and the exposure bar is **hatched** with "inherits the unit cost's band —
hatched until validated by measured actuals." `posture` shows `default:27, grounded_pct:0, validated:false` for
every driver — and the UI **discloses** this rather than presenting the $230k as validated fact. No dishonest
rollup found.

---

## Bucket-A category vector (0–100, evidence)

| # | Category | Score | Evidence |
|---|---|---|---|
| 1 | Functional correctness | **88** | create/assign/edit-volume/unassign/withheld all correct (shots 05–11). Gaps: no row→part drill-through, no sort/group controls. |
| 2 | Data fidelity | **95** | rollups reconcile exactly (table above); provenance chips preserved; org-scoped. |
| 3 | AI fidelity | **N/A** | no LLM/AI on this surface — deterministic engine rollup. Not exercised. |
| 4 | Interaction fidelity | **90** | inputs, Enter-to-save, blur-to-save, numeric filtering, toasts, back-nav all work (shots 06,08). |
| 5 | Visual fidelity | **90** | clean grid, no overlap/clipping, clear hierarchy (shots 06,08,11). Polish: headline 30px vs caveat 9.5px. |
| 6 | Performance | **90** | portfolio GET 64–127 ms warm (4 curl samples); UI snappy. Cold Next compile slow (dev only). |
| 7 | Reliability | **78** | reconciliation consistent across index/detail/backend and across edits. **Capped:** portfolio GET 60/hour cap on a refetch-on-every-mutation surface → 429 + 1h lockout (finding #1). |
| 8 | Conversational | **N/A** | no chat on this surface. |
| 9 | Error recovery | **80** (partial) | load failure → inline "couldn't load the portfolio — {error}" + safe empty fallback; honest empty/withheld states. Not tested: mid-assign network loss, dup-submit. |
| 10 | Security | **92** | fresh org sees parts=0/rows=0/programs=[] — zero cross-tenant leak (shot 13); endpoint `require_role(viewer)`, org_id-scoped fold. Only 2-org isolation tested, not intra-org roles. |
| 11 | Accessibility | **82** | keyboard-reachable; `:focus-visible` 2px outline present + visible on Tab (shot 12, `matches(':focus-visible')==true`). Caps: candidate-row volume input relies on placeholder only (no aria-label); mono captions 9.5–10.5px small. |
| 12 | Regression | **N/A** | registry replay not driven this run. |

**W6 exercised-Bucket-A minimum ≈ 78** (Reliability — the portfolio-read rate limit), reported alongside the vector, not averaged.

---

## Findings (schema)

### F1 — Portfolio read (`GET /catalog/portfolio`) rate-limited at 60/hour on a refetch-heavy surface  [severity: major, confidence: medium-high, status: open]
- **observed:** `@limiter.limit("60/hour;500/day")` on `get_portfolio` (backend/src/api/catalog.py:187). `ProgramScreen`
  calls `getPortfolio()` on mount **and** `refresh()` after every `assignContext` / `setVolume` / `unassign`. Building a
  real portfolio (assign N parts, tweak volumes, unassign) issues one full-portfolio GET per mutation plus every
  re-mount. I hit HTTP 429 `{"code":"rate_limited"}` with `retry-after: 3600`, `x-ratelimit-limit: 60`,
  `x-ratelimit-remaining: 0` — a 1-hour lockout of the whole portfolio view.
- **expected:** a procurement lead triaging a portfolio can assign/edit dozens of parts in one session without the
  exposure view locking out for an hour.
- **evidence:** `curl … /catalog/portfolio` → 429 + headers (captured); reset only via `RATE_LIMIT_DISABLED=1`.
- **failure_reason:** read endpoint shares a low write-grade limit; client refetches the entire portfolio on every
  small mutation.
- **recommended_fix (#1):** raise the read limit substantially (e.g. 600/hour) and/or split burst vs sustained; and
  update `context`/`annual_volume` responses to return the affected row so the client can patch state instead of a
  full refetch. Shorten the lockout. *(honest caveat: my specific trip was amplified by API polling, but the
  on-every-mutation refetch pattern makes 60/hour reachable in normal heavy use.)*

### F2 — No drill-through from a program's member part into that part's cost/provenance  [minor, high, open]
- **observed:** program detail lists assigned parts with unit cost + exposure but no row is clickable to the part
  screen; only "view all in Parts →" which jumps to the full catalog and loses program context (shot 06).
- **expected:** click a member → its cost breakdown / drivers / provenance (P2 wants to defend a number).
- **recommended_fix:** link each assigned/member row to the part screen (mesh_hash), preserving return-to-program.

### F3 — "Exposure" = annualized spend only; no risk-concentration lens  [minor, medium, open]
- **observed:** the only portfolio metric is $/yr = Σ(unit cost × volume). No make/buy split, single-process /
  single-source concentration, or cost-at-risk — which is what a sourcing/risk lead means by "exposure."
- **evidence:** shots 06/08; `_group_by_program` sums annualized cost/savings only.
- **recommended_fix:** add concentration rollups (e.g. % of program exposure on one process/route; unvalidated-cost
  exposure as its own tile).

### F4 — Rolled-up `annualized_savings_usd` computed but never surfaced; headline dwarfs its caveat  [polish, high, open]
- **observed:** `summary.programs[]` returns `annualized_savings_usd` (13600 / 15440) — never rendered. And the
  $230k headline is 30px while the "inherits the unit cost's band" honesty caveat is 9.5px mono (shot 06).
- **recommended_fix:** surface savings exposure, or drop the dead field; lift the uncertainty caveat's prominence.

### F5 — Dead/duplicate component `programs-screen.tsx` (ProgramsScreen) not wired  [informational, high, open]
- **observed:** the shell renders `program-screen.tsx` (`ProgramScreen`, verify-app.tsx:421). `programs-screen.tsx`
  (`ProgramsScreen`, uses `programs-api.ts` + `fetchPortfolio`) is imported nowhere in the shell — divergent second
  implementation of the same surface.
- **recommended_fix:** delete the unused file/module or converge, to avoid maintenance drift.

---

## Positives (evidence-backed)
- Exposure math reconciles exactly across per-part, backend rollup, index card, detail sum, and hand math, incl.
  after live edits (shots 06/08/09/10; recon JSON).
- Honesty is strong: withheld exposure says "not guessed, not extrapolated" (shot 11); every unit cost tagged
  `MODEL` + hatched band "until validated by measured actuals"; empty state is honest (shots 02/13).
- Org isolation clean: fresh org portfolio fully empty (shot 13).
- Keyboard focus ring visible via `:focus-visible` (shot 12).
- Portfolio read fast warm (64–127 ms).

## Screenshot index
- w6-01 verify home · w6-02 programs empty (first run) · w6-04 index empty · w6-05 prog1 detail empty
- w6-06 prog1 exposure $230k (assigned + candidates + honesty band) · w6-07 prog2 · w6-08 both cards
- w6-09 volume-edited $260k · w6-10 after unassign $180k · w6-11 exposure withheld (no-volume)
- w6-12 a11y focus ring · w6-13 isolation fresh-org empty

## Bucket B (not part of product score)
- Cost/exposure accuracy vs real ground truth: `validated=false`, `grounded_pct=0` — method proven, number gated
  on real customer actuals. UI discloses it. Not a product defect.
