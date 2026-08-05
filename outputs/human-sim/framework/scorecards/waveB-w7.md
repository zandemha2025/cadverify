# Wave B — W7 Calibration / Ground-Truth Flywheel — Scorecard

- **Persona:** P5 — Skeptical CFO / cost engineer (adversarial, honesty-first)
- **Workflow:** W7 — Calibration & truth surface → ingest real quotes → recalibrate → measured band
- **Date:** 2026-07-10
- **Stack:** worktree `waveB-w7` (HEAD 6697222), backend :8046 (`cadverify_w7` DB), frontend :3046, Playwright/chromium headless, vision-verified.
- **Surface driven:** `/verify` SPA → "Calibration & truth" screen (hotkey `c`) → THE HALLMARK — GROUND-TRUTH FLYWHEEL panel (`calibration-screen.tsx` `HallmarkPanel`), backend `src/api/groundtruth.py` + `src/services/groundtruth_service.py`.
- **Shots:** `waveB-shots/w7-*.png`

## Headline verdict

**The cardinal sin — "does it ever claim validated/accurate without real held-out data?" — NO.** Across every branch the app only ever printed `validated=true` when it had actually costed real parts and measured residuals on a leakage-safe held-out split. When it *couldn't* (STEP parts uncostable in-container → all records skipped), it printed `validated=false` + `"PENDING real ground truth — no held-out records could be costed"` rather than fabricating a number. When there were too few real records it **refused** (422) and kept the band hatched. This workflow lives up to its own honesty promise.

**Category vector (0–100):**
`Functional 95 · Data-fidelity 96 · AI-fidelity 98 · Interaction 88 · Visual 90 · Performance 90 · Reliability 92 · Error-recovery 96 · Security 90(partial) · Accessibility 60(partial)`
Overall (min across exercised, product bucket) ≈ **88**, dragged by Interaction/Accessibility polish, not by any honesty or correctness defect.

---

## Evidence by branch (all real, captured)

### 1. BEFORE any real quotes — the core honesty promise ✅
`w7-02-calibration-before.png`. Fresh org, `GET /ground-truth → {records:[],total:0}`. Hallmark panel reads:
`real records (held-out pool) 0 · stand-ins 0 · floor to validate 8 real`; band rendered **HATCHED** (diagonal stripes visible); status line: *"validation status: n=0 real · every band hatched · 'validated' here will only ever mean measured."* Rate panel reads **DEFAULT RATE TABLE (v0)** with `● DEFAULT` provenance chip, *"generic assumptions, not your floor."* This is exactly the promised `validated=false` / honest-band state.

### 2. Recalibrate with 0 records — honest refusal ✅
`w7-03-recal-refused-0.png`. `POST /ground-truth/recalibrate → 422`:
`{"n_real":0,"n_records":0,"min_real":8,"reason":"Recalibration refused: 0 REAL ground-truth record(s) (< 8 required)..."}`. Toast: *"Recalibration refused — below the floor · 0 real of 8 needed · band stays hatched."* Inline red text mirrors it. Band stays hatched.

### 3. Malformed CSV import — partial success + per-row report ✅
`w7-04-import-malformed.png`. 7-row CSV (2 good, 5 bad). `POST /ground-truth/import → 200`:
`{"imported":2,"skipped":5,"total":7,"errors":[{line:3,"unknown process 'teleport_process'"},{line:4,"actual_unit_cost_usd must be > 0 (got -9.0)"},{line:5,"missing part_id"},{line:6,"quantity must be >= 1 (got 0)"},{line:7,"unknown material_class 'plutonium'"}]}`. Green success toast + a "5 row error(s)" toast naming line/reason. Panel updates to `n=2 real`, band stays hatched. Bad rows reported, never coerced; one bad row never aborts the file.

### 4. Below the floor (6 real, then 6→still refused) — honest gate ✅
`w7-05-recal-belowfloor.png`. With 6 real records `POST /recalibrate → 422 {n_real:6,min_real:8}`. Inline: *"recalibration refused: 6 real of 8 needed."* Band stays hatched. Floor is enforced at exactly 8 real (`MIN_REAL_RECORDS`), documented and matched to the by-part held-out split so ≥3 real residuals can be measured.

### 5. Enough real records but uncostable parts — honest PENDING (not fabricated) ✅ (KEY)
14 real STEP-referenced records ingested. `POST /recalibrate → 200` but:
`{"n_real":0,"n_skipped":14,"from_real":false,"validated":false,"claim":"PENDING real ground truth — no held-out records could be costed.","calibration":{"process_factors":{},"global_factor":1.0,"provenance":"TUNED"}}`.
Root cause (backend log): STEP parsing needs module `cascadio`, absent in-container → every `cube*.step` skipped. **The app did not invent a validated band from records it could not cost — it disclosed the shortfall.** This is the strongest anti-cardinal-sin evidence.

### 6. The FLIP — real held-out measured band ✅ (full flywheel end-to-end)
Regenerated 12 distinct **STL** boxes (trimesh-loadable in-container), ingested 12 real quotes, recalibrated. `POST /recalibrate → 200`:
```
validated:true, from_real:true, n_records:12,
calibration.fitted_on: "tuning split: 8 record(s) over 8 part(s)", factor cnc_3axis=2.0336,
heldout_metrics_real: {n_records:4, n_parts:4, mean_abs_pct:35.5, median_abs_pct:21.2,
                       p90_abs_pct:66.7, band_covers_80pct:48.5, worst_abs_pct:84.9}
claim: "VALIDATED within ±48.5% across 4 real held-out part(s) (mean abs error 35.5%)."
```
`w7-08-flip-result.png`: band flips **HATCHED → SOLID GREEN**; status: *"validated (measured) · VALIDATED within ±48.5% across 4 real held-out part(s) (mean abs error 35.5%) · from 4 real held-out records."* The split is **8 tuning parts / 4 held-out parts, all distinct → no leakage**. It reports a **wide, warts-and-all** measured error (mean abs 35.5%) rather than dressing up a poor fit — the opposite of the cardinal sin.

### 7. Served calibration is wired to serving path ✅ (mechanism proven; UI cost-drive = partial)
Server-side `load_served_calibration(org)` (the exact function `/validate/cost` calls) returns `ResidualModel(from_real=True)` + `Calibration(factor cnc_3axis=2.0336, provenance=TUNED)`. So a subsequent estimate for this org is corrected by the measured factor and carries the MEASURED band. NOTE: I proved the serve wiring server-side but did **not** visually drive a fresh post-calibration cost estimate to eyeball the band change → **partial**. Honest caveat: the served band becomes *measured*, which may be wider or narrower than the ±40% assumption band depending on real residuals — it is not cosmetic tightening.

### 8. Cross-org isolation (security) ✅ (read-path)
Fresh Org-B signup → `GET /ground-truth → {records:[],total:0}` while Org-A holds 12 records. Org-B never sees Org-A's ground truth. Backend scopes every read `WHERE org_id = caller-org`. NOTE: verified the read path only; did not attempt a forged-org-id write or a second-analyst cross-tenant recalibrate → **partial** on full security sweep.

---

## Category scores (evidence · severity · confidence · fix)

| # | Category | Score | Observed / Expected | Evidence | Sev | Conf | Fix |
|---|---|---|---|---|---|---|---|
| 1 | Functional | 95 | Signup→calibration→import→recalibrate→flip all produced correct state transitions; counts update live | w7-02,04,05,08 + NET | — | high | none material |
| 2 | Data fidelity | 96 | Counts (n_real, skipped, held-out) and provenance (DEFAULT v0 → measured) all trace to backend values; no fixtures | NET bodies vs UI | — | high | none |
| 3 | AI fidelity (accuracy claims honest) | 98 | validated only from real held-out residuals; PENDING/refused otherwise; wide error reported honestly; no-leakage split | steps 2,4,5,6 | — | high | — |
| 4 | Interaction | 88 | Hotkey `c`, CSV picker, buttons all work | all | minor | high | Two hidden `input[type=file]` on-screen (verify-part uploader + CSV) — a mis-scoped automation/paste can send a CSV to the cost uploader (got 400 "unsupported file type"). Harmless but a papercut; scope/label the CSV input. |
| 5 | Visual | 90 | Clean layout, hatched vs solid band unmistakable, honest empty states | w7-02,08 | minor | high | Sonner toast overlaps top-right ⌘K/bell controls (w7-03,04) — reposition/offset toast region |
| 6 | Performance | 90 | Screen load ~2.5s; recalibrate over 12 STL parts (real engine runs) ~10–15s | timers | minor | med | Long recalibrate is synchronous with only a "Working…" button; add progress/async affordance |
| 7 | Reliability | 92 | Refusal at 0 and 6 both deterministic; import idempotent (last-write dedup) | steps 2,4 | — | med | — |
| 8 | Error recovery | 96 | Malformed rows reported per-line, file not aborted; empty/too-few honest; uncostable parts → honest PENDING | steps 3,5 | — | high | — |
| 9 | Security (org-scoped calibration) | 90* | Org-B sees 0 of Org-A's 12; reads org-scoped | step 8 | — | med | *partial: read-path only; add forged-org write + cross-tenant recalibrate probe |
| 10 | Accessibility | 60* | Not audited (keyboard focus/contrast/semantics) beyond hotkey nav working; mono 9.5–10px hint text is low-contrast/tiny | w7-02 | minor | low | *partial — needs dedicated a11y pass; bump caption contrast/size |
| 11 | Conversational | n/a | no chat surface in W7 | — | — | — | — |

\* partials as noted.

## Top findings (ranked)
1. **(Positive, headline)** Honesty invariant holds under every branch incl. the adversarial one (14 real but uncostable → PENDING, not a fake validate). No fabricated accuracy. `w7-03/05/07/08`.
2. **(Minor, Interaction)** Two co-located hidden file inputs; the verify-part uploader sits first in DOM, so a CSV sent to the wrong input yields a confusing `400 unsupported file type` on `/validate/cost` rather than a ground-truth import. Scope the CSV picker. Repro: `setInputFiles` on `input[type=file]:first` vs `input[accept*="csv"]`.
3. **(Minor, Visual)** Toast region overlaps the ⌘K / notification controls (`w7-03`, `w7-04`).
4. **(Minor, Perf/Interaction)** Recalibrate is a multi-second synchronous engine run with only a "Working…" label — no progress/cancel.
5. **(Infra caveat, not a product bug)** STEP costing needs `cascadio` (absent in-container); STEP-referenced ground truth is uncostable here → the flip must be driven with STL parts. Real deploys with cascadio would cost STEP too.

## #1 fix
None on the honesty/correctness axis. Highest-value polish: **scope/label the ground-truth CSV file input distinctly from the verify-part uploader** (Interaction finding #2) so an import can never be misrouted to `/validate/cost`.

## Answer to the cardinal question
**Does it ever claim validated/accurate without real held-out data? → NO.** Every `validated=true` was backed by a leakage-safe held-out split with a measured mean-abs-error; every insufficient/uncostable case was honestly refused (422) or labeled PENDING with the band left hatched.
