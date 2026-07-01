# Cycle 5 — Frontend Cost-Decision Surface (builder B notes)

Status: **DONE**. The cost decision is now a first-class product surface at `/cost`
(and `/dashboard/cost`). Typechecks, lints, and production-builds green; the
decision card renders process comparison, $/unit + lead-time, crossover,
make-vs-buy, and the provenance-tagged driver breakdown; errors (incl.
`GEOMETRY_INVALID`) are handled cleanly.

Per spec §B (`outputs/c5-spec.md`). No git commit (per instructions). No new
runtime deps.

---

## Files added / changed

| File | Change |
|---|---|
| `frontend/src/lib/api.ts` | **Added** cost types (`CostReport`, `CostEstimate`, `CostDriver`, `CostLeadTime`, `CostDecision`, `CostRecommendation`, `CostRedesigned`, `CostAssumption`, `CostGeometry`, `CostFeasibility`, `CostOptions`, `Provenance`), the `CostGeometryInvalidError` class, and the `costEstimate(file, opts)` client fn. |
| `frontend/src/components/CostDecisionCard.tsx` | **New.** Presentational decision card (`{ report }`) + exported `CostGeometryInvalidCard` repair card. |
| `frontend/src/app/(dashboard)/cost/page.tsx` | **New.** `"use client"` cost page: upload → cost, override controls, re-cost without re-upload, error/geometry-invalid handling. |
| `frontend/src/app/dashboard/cost/page.tsx` | **New.** Thin re-export (`export { default } from "../../(dashboard)/cost/page";`) matching the existing dual-route convention. |
| `frontend/src/app/(dashboard)/layout.tsx` | **Edited.** Added `{ href: "/cost", label: "Cost" }` to `NAV_ITEMS`. |

---

## The API call

`POST /api/v1/validate/cost` — multipart `FormData` (file + Form fields), via
the new `costEstimate(file, opts)` in `frontend/src/lib/api.ts`:

```ts
const form = new FormData();
form.append("file", file);
form.append("qty", opts.qty);            // "50,5000"
form.append("region", opts.region);      // US|EU|MX|CN|IN|SA
form.append("cavities", String(opts.cavities)); // >= 1
form.append("complexity", opts.complexity);      // simple|moderate|complex|very_complex
form.append("material_class", opts.material_class); // polymer|aluminum|steel|stainless|titanium

// auth Bearer from localStorage["cadverify_api_key"]; rate-limit tracking;
// 429 toast; 5xx -> Sentry; NO auto-retry (non-idempotent compute).
const res = await fetch(`${API_BASE}/validate/cost`, { method: "POST", body: form, headers });
```

Design note — why not `apiClient.fetch` directly: the wrapper consumes the body
and throws a flat `Error` on 4xx, which would discard the structured
`GEOMETRY_INVALID` geometry payload. `costEstimate` instead **replicates**
apiClient's auth + rate-limit + 429/5xx behavior (reusing the same module-private
`authHeaders` / `extractRateLimits` / `_latestRateLimits` / `toast` / `Sentry`)
and branches on the structured 400 so the repair card can show the measured
geometry. This mirrors the raw-fetch demo handler in `app/page.tsx`, which the
spec explicitly sanctions (§B.2).

Error handling (no unhandled rejections):
- **200** → `CostReport` (always `status:"OK"`).
- **400 `GEOMETRY_INVALID`** → throws `CostGeometryInvalidError(message, geometry)`;
  the page renders `CostGeometryInvalidCard` (reason + volume/bbox/watertight/faces + docs link).
- **429** → toast + throw (message surfaced in the page's error banner).
- **5xx** → toast + `Sentry.captureException` + throw.
- **other 4xx** (bad option / bad magic / unsupported suffix) → throw `Error(message)`.
- **network error** → toast + throw.

Client-side option validation mirrors the backend exactly (qty ≤ 6 ints in
1…10,000,000; cavities ≥ 1; region/complexity/material_class from fixed lists) so
the user never round-trips a 400 for a bad option (the qty box shows inline
validation and disables Re-cost while invalid).

---

## What the surface renders (the decision, not a number dump)

`CostDecisionCard`, top-to-bottom (spec §B.3):
1. **Make-vs-buy headline** — `decision.note` prominent, make-now process/material
   chip, tool/buy chip, and a crossover strip ("Crossover ≈ N units — make below
   with X; tool up with Y above it"), or an explicit "No crossover in range".
2. **Recommendation by quantity** — table over `quantities`: qty · process/material ·
   **$/unit** · lead `low–high d`, with a muted "cheaper if redesigned" sub-row when
   `if_redesigned[q]` is non-null, and a "not DFM-ready" chip when applicable.
3. **Process options · should-cost** — `estimates` grouped by process, per-qty
   $/unit, `±est_error_band_pct%` badge, MAKE-NOW highlight on the headline process,
   and a "Not DFM-ready as-modeled" warning showing `dfm_blockers[0]`.
4. **Cost drivers (glass-box)** — headline process's smallest-qty estimate: each
   driver as `name · value+unit · [PROVENANCE source]` with the
   MEASURED=blue / USER=green / DEFAULT=gray tag map, then the `line_items` map and a
   visible **Σ line items = unit cost** coherence line (flips red if it ever diverges).
5. **Lead time** — `low–high days` headline + `components` chips + capacity
   ("N machines × H hr/day [provenance]").
6. **Assumptions + notes** — every assumption with its provenance tag, the engine
   `notes[]` (±40–60% band / crossover-robustness disclaimer), and a fixed footnote:
   "STEP files are costed from a tessellated mesh (DFM + cost), not B-rep/GD&T."
7. **GEOMETRY_INVALID** — `CostGeometryInvalidCard` repair card (reason + geometry
   summary + docs link), mirroring the engine's G1 tone.

Reuse: `FileDropZone`, `ModelViewer` (STL preview; STEP shows its built-in
placeholder), `apiClient`-pattern auth/rate-limit, `API_BASE`, and the
badge/provenance-color idiom copied from `AnalysisDashboard.tsx` /
`ProcessScoreCard.tsx`. Nav item added.

Re-cost UX: the uploaded `File` is held in page state, so changing qty/region/
cavities/complexity/material_class and clicking **Re-cost** re-submits the same
bytes with new options — no re-upload (the cost path has zero persistence by
design; there is no server-side mesh to re-fetch, so re-cost = re-submit).

---

## How to view it

```bash
cd /Users/nazeem/Desktop/developer/cadverify/frontend
npm run dev          # then open http://localhost:3000/cost
```
Set an API key first (the page sends `Authorization: Bearer <localStorage.cadverify_api_key>`):
```js
localStorage.setItem("cadverify_api_key", "<your analyst key>")
```
Backend must be reachable at `NEXT_PUBLIC_API_BASE` (defaults to
`http://localhost:8000` in dev, `https://cadvrfy-api.fly.dev` in prod). Upload an
`.stl` / `.step` / `.stp`, adjust options, Re-cost to sweep.

---

## Evidence it builds

All commands run in `frontend/` (Next 16.2.3, Turbopack):

- `npx tsc --noEmit` → **exit 0** (clean).
- `npx eslint <new+edited files>` → **exit 0** (no errors/warnings on new code).
- `npm run lint` (full project) → **exit 0**; 0 errors, only 3 pre-existing
  warnings in untouched files (`reconstruct/.../ImageUploader.tsx`,
  `ModelViewer.tsx`, `ShareButton.tsx`). No new warnings.
- `npm run build` (`next build` == typecheck gate) → **green**:
  `✓ Compiled successfully`, `Finished TypeScript`, routes include
  `○ /cost` and `○ /dashboard/cost` (both prerendered).

### Contract verified against real numbers (bonus)

A live HTTP round-trip needs the backend running with an analyst key
(`require_role(analyst)` + kill-switch). Instead, the TS↔JSON contract was
verified directly against the backend serializer on a **real STL part**
(`…/scratchpad/parts/…EK_0BD1_ECU_Firewall_mount.stl`) via
`src.costing.report_to_dict(estimate_decision(...))`:

- Every serialized key set matches the new TS interfaces exactly: top-level,
  `geometry`, `estimates[i]`, `drivers[i]`, `lead_time`, `decision`,
  `recommendation[q]`, `if_redesigned[q]`, `assumptions[i]`, `engine_feasibility[i]`.
- Quantity keys JSON-serialize to **strings** (`['50','5000']`) — confirming the
  `Record<string, …>` typing used throughout the card.
- Real decision returned: `make_now = mjf / PP (Polypropylene)`, `crossover_qty = 739.2`.
- Invariant `abs(unit_cost_usd − Σ line_items) < 0.02` held for **all 16 estimates**
  (the card renders this Σ check visibly).

No backend code was modified by this workstream.
