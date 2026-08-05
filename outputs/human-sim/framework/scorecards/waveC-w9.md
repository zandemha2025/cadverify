# Wave C — W9: RFQ supplier evidence package — Scorecard

- **Persona:** P2 — Sourcing / Procurement lead
- **Workflow:** W9 — Build & export an RFQ supplier evidence package
- **Date:** 2026-07-10
- **Worktree:** `.claude/worktrees/waveC-w9` @ e3e9308 (migrations at head, 0032_rfq_packages applied)
- **Stack:** backend uvicorn :8052 (postgres:true), frontend Next dev :3052. Driven headless Chromium (Playwright), real clicks + vision.
- **Surface located:** `/rfq-packages` (list+builder) + `/rfq-packages/[id]` (detail). API `/api/v1/rfq-packages` (POST create, GET list/detail, GET `/{id}/download.zip`). Service `backend/src/services/rfq_package_service.py`. **The RFQ package is built from SAVED cost decisions** — not a free-form part list. Cost a part on `/cost` (auto-persists a decision) → pick decisions on `/rfq-packages` → generate → download ZIP.

## What was driven (real end-to-end)
1. Login (session cookie via Next proxy) → costed **bracket_A.stl** on `/cost` (MJF (HP), $10.14/unit, ±40% band) → auto-persisted decision. `w9-04`, `w9-05`.
2. Costed a 2nd part **torus_unrelated.stl** (~9.1s) → 2 saved decisions. `w9-06`.
3. `/rfq-packages`: empty builder, Generate button disabled at 0 selected. `w9-07`.
4. Selected both decisions, filled title/supplier/note, generated → toast "RFQ package generated", package row shows **0/2 approved · 4 warnings · ZIP**. `w9-08`, `w9-09`.
5. Opened detail page (stat cards + warnings + item table). `w9-10`.
6. Downloaded ZIP (200 KB) → unzipped and inspected every artifact for honesty.
7. API probes: cross-org isolation, auth gating, error branches, latency.

---

## Category vector (Bucket A)

| # | Category | Score | Severity of worst finding |
|---|---|---|---|
| 1 | Functional correctness | 90 | minor |
| 2 | Data fidelity | 95 | polish |
| 3 | AI fidelity (honesty/provenance) | 95 | none material |
| 4 | Interaction fidelity | 88 | minor |
| 5 | Visual fidelity | 92 | polish |
| 6 | Performance | 70 | major |
| 7 | Reliability | 84 | major (shared w/ perf) |
| 8 | Error recovery | 92 | minor |
| 9 | Security (RFQ scoping / cross-org) | 96 | none observed |
| 10 | Accessibility | 78 | minor |

**W9 Product min = 70 (Performance)** — driven by ZIP-download latency that scales linearly with item count.

> **Overclaim verdict (the P2 acid test): NO overclaim found.** The supplier package does NOT present any estimate as a firm quote and does NOT present any default as a measured fact. This is a model of honest, provenance-tagged evidence. Details in Data/AI fidelity below.

---

## Findings (schema)

### F1 — ZIP download regenerates all PDFs on every request; O(n) latency, timeout risk at scale — **MAJOR**
- persona P2 · flow W9 · branch download/export · category Performance/Reliability
- **observed:** `GET /{id}/download.zip` for a **2-item** package = **6.26s** (measured, curl `time_total`), vs create=36ms, list=16ms. `build_zip` calls `generate_cost_pdf(decision)` for every item on **every** download with no caching. MAX_ITEMS=25 → an estimated ~60–75s download for a full package.
- **expected:** a supplier ZIP downloads in <1–2s; PDF rendering cached/precomputed at create time (create is where the user waits, and it's already 36ms).
- **evidence:** curl timings (create 0.036s / download 6.26s / list 0.016s); `rfq_package_service.build_zip` loop calling `generate_cost_pdf` per item.
- **failure_reason:** per-decision PDF rendered synchronously inside the zip build; nothing memoized.
- **severity:** major · **confidence:** high
- **recommended_fix:** render each decision's `should-cost-report.pdf` once at create/persist time (or memoize by decision mesh/params hash) and stream stored bytes at download; a 25-item package must not risk a gateway timeout.
- **status:** open

### F2 — Row "Pick" checkboxes have no accessible label — **MINOR (a11y)**
- category Accessibility · flow W9 · branch decision selection
- **observed:** each decision-picker checkbox has `aria-label=null`, no `id`, and is **not** wrapped in a `<label>` (DOM probe). A screen-reader user hears "checkbox, unchecked" with no indication of which part it selects.
- **expected:** `aria-label="Select {filename}"` or a wrapping label tying the checkbox to the decision row.
- **evidence:** `a11y.mjs` output — `checkboxLabels: [{ariaLabel:null,id:"",inLabel:false} ×2]`. (Headings semantic H1/H3, buttons all have accessible names, Title/Supplier/raw-CAD inputs ARE labeled — so this is isolated to the table checkboxes.)
- **severity:** minor · **confidence:** high
- **recommended_fix:** add `aria-label` to `frontend/src/app/(app)/rfq-packages/rfq-packages-client.tsx` row checkbox (and the same pattern would help keyboard users identify rows).
- **status:** open

### F3 — Generated packages are immutable; no in-place remove-part / regenerate — **MINOR (by-design, note)**
- category Functional/Interaction · branch remove a part / regenerate
- **observed:** a package is a snapshot. There is no UI to remove a part from an existing package or regenerate it in place; you build a new package with a different selection. Selection state resets to empty after a successful generate (verified — button returned to "Generate package (0)").
- **expected:** acceptable for an auditable evidence artifact (immutability is arguably correct for provenance). Flagged only because the runbook asked for the remove/regenerate branch — it is honestly absent, not broken.
- **severity:** polish · **confidence:** high · **status:** open (design note, not a defect)

### F4 — "Uncosted part" cannot be added to an RFQ (honest gate) — **INFO**
- category Functional · branch RFQ with an uncosted part
- **observed:** the builder only lists **saved cost decisions**. A part that was never costed simply isn't selectable — there is no path to smuggle an uncosted/unpriced item into a supplier package. Attempting to reference an unknown decision id via API → `404 "One or more cost decisions were not found."`
- **expected:** exactly this — a supplier package must not carry an item with no evidence. Honest.
- **severity:** none · **status:** honest-gate (positive)

---

## Category detail + evidence

### 1. Functional correctness — 90
Cost→persist→pick→generate→detail→download all work; the package assembles the **right** parts with the right process (mjf), crossover qty, and per-decision drivers. Empty selection disables generate (`w9-07`); after generate, list + detail + ZIP all reflect the exact selection (`w9-09`,`w9-10`). Deductions: F1 (download scaling), and no remove/regenerate branch (F3, by-design).

### 2. Data fidelity — 95
ZIP contents match source exactly. `line-items.csv`, `package_manifest.json`, `supplier-brief.md`, `cost-decisions.json` + per-decision `cost-decision.json` / `cost-drivers.csv` / `should-cost-report.pdf`. Every assumption row carries `provenance: "DEFAULT"` with a `source` string (labor_rate, region_*, margin, overhead, utilization, stock_allowance…). Geometry block is measured facts (bbox 80×50×12, vol 46.65 cm³, 144 faces, watertight) — the UI tags these "MEASURED · FROM YOUR GEOMETRY" (`w9-04`). Warnings (unapproved ×2, unvalidated ×2) preserved consistently across manifest, brief, CSV, and both UI pages.

### 3. AI fidelity / honesty — 95 (**no overclaim**)
Every estimate in `cost-drivers.csv` and `cost-decision.json` carries `confidence_validated=False`, label **"assumption-based, not yet validated"**, `est_error_band_pct` (40–60%), and explicit `confidence_low/high`. The should-cost is never a firm price: `supplier-brief.md` opens *"This package is should-cost evidence for an RFQ handoff. It is not a supplier quote, supplier commitment, or live procurement transaction."* Injection-molding line is flagged *"the cost shown is 'if redesigned,' not a current quote."* `metadata.contract = "should_cost_evidence_not_supplier_quote"`. A default is never dressed as measured (assumptions=DEFAULT, geometry=measured, cleanly separated). This is precisely the honesty P2 needs before handing numbers to a supplier.

### 4. Interaction fidelity — 88
Checkbox toggles, form fields, generate, refresh, row→detail nav, download all responsive. Selection correctly clears post-generate. Deduction: no select-all for many decisions; row checkboxes give no textual affordance (see F2).

### 5. Visual fidelity — 92
Clean dark-theme layout across builder (`w9-09`) and detail (`w9-10`) — stat cards (Approved/Stale/Unvalidated/Raw CAD), amber warning rows, item table, no overlap/clipping/contrast issues observed by vision. Amber "unapproved" badges legible. One transient: first visit to `/rfq-packages/[id]` showed "Loading…/Compiling…" (Next dev compile, not a prod defect) — re-rendered clean on next load.

### 6. Performance — 70
create 36ms, list 16ms, cost-a-part ~9s (acceptable: parse+cost+persist). **Download 6.26s for 2 items** and scales linearly (F1) — the gate on this category.

### 7. Reliability — 84
Create/list/download deterministic across repeated calls; generate produced a consistent snapshot. Cross-org probes stable. Docked for the download-latency scaling risk (shared root cause with F1) and limited high-N stress within the time box.

### 8. Error recovery — 92
Structured, correct errors with `doc_url`: empty `decision_ids` → **400** BAD_REQUEST; unknown decision id → **404**; bogus package id → **404**; unauth → **401**. UI surfaces failures via toast (`toast.error`).

### 9. Security — 96 (RFQ scoping airtight)
Org2 (fresh signup = separate org) probes against Org1's package `01KX645…`:
- GET package by id → **404** NOT_FOUND
- LIST → `{"packages":[]}`
- download.zip → **404**
- create package referencing Org1's decision id → **404** "cost decisions were not found"
- unauthenticated GET → **401**

No cross-org leak on any read, download, or by-reference create. Enforced via `caller_org_subquery` scoping in the service.

### 10. Accessibility — 78
Semantic headings (H1 "RFQ packages", H3 sections), all buttons have accessible names, Title/Supplier/note/raw-CAD inputs labeled, keyboard focus advances. Docked for F2 (unlabeled row checkboxes).

---

## Screenshots (`scorecards/waveC-shots/`)
- `w9-01-login.png` login · `w9-02-after-login.png` dashboard
- `w9-03-cost-landing.png` drop-a-part · `w9-04-cost-result.png` should-cost w/ MEASURED facts + ±40% band + "not a current quote" · `w9-04b` breakeven · `w9-05-cost-decisions-list.png` persisted + honesty banner
- `w9-06-cost2-torus.png` 2nd decision
- `w9-07-rfq-empty.png` empty builder (generate disabled)
- `w9-08-rfq-filled.png` selection + title/supplier/note
- `w9-09-rfq-generated.png` package created (0/2 approved · 4 warnings · ZIP)
- `w9-10-rfq-detail.png` detail (stat cards + warnings + items)

## #1 fix
**F1** — precompute/cache each decision's should-cost PDF at create time (or memoize by decision hash) and stream stored bytes on download, so a full 25-item supplier package downloads in <2s instead of an estimated ~60–75s timeout-risk render.
