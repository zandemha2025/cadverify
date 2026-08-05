# Wave A — W4: Bulk manifest → portfolio triage (Persona P2, Sourcing/Procurement lead)

- **Run date:** 2026-07-10
- **Persona:** P2 — Sourcing / Procurement lead
- **Workflow:** W4 — Bulk manifest → triage at scale
- **Stack:** worktree `waveA-w4` @ HEAD `ea1be29`; backend `:8043` (postgres cluster `16/fix` on `:5433`, db `cadverify_w4`), frontend `:3043` (Next 16 / Turbopack). RUNBOOK recipe verified: `/health` postgres:true, signup → 200 + session.
- **Driver:** real browser (Playwright chromium-1194, headless, 1440×900), real clicks/file-uploads via the triage CSV `<input>`. No internal-API calls a human couldn't make (latency probes done in-page through the authed Next proxy).
- **Entry:** signup (password, role=analyst) → `/verify` → hotkey **T** → "Triage at scale".

---

## Category vector (Bucket-A; 0–100)

| # | Category | Score | Confidence | Notes |
|---|---|---|---|---|
| 1 | Functional correctness | **35** | high | Import persists, but the W4 headline (manifest → portfolio triage) does NOT happen: imported parts never appear in triage or anywhere in the UI. |
| 2 | Data fidelity | **50** | high | Import parse/counts/upsert are exactly correct, but the declared data has **zero read surface** — not one imported value is viewable in-product. |
| 3 | AI fidelity | N/A | — | No AI/NL surface in the W4 manifest→triage path. Not exercised (crossover/AI live in W1 verify). |
| 4 | Interaction fidelity | **62** | high | File picker, button, toasts all work; but the flow dead-ends and the import control lives only in the empty state. |
| 5 | Visual fidelity | **80** | high | Clean layout, no clipping/overlap in main content. Minor: success/error toast overlaps the top-right header controls. |
| 6 | Performance | **95** | high | makeability 56 ms, capability-investment 24 ms, POST /manifest/import 34 ms (through proxy). Excellent. |
| 7 | Reliability | **90** | high | Re-import same CSV → `updated:8` idempotent; makeability=0 reproduced 3× identically. Deterministic. |
| 9 | Error recovery | **88** | high | empty→400 handled, malformed→per-line errors, missing-header→header error. No crash, honest partial-success. |
| 10 | Security | **partial / honest-gate** | med | Backend is org-scoped in code (`_require_org`/`resolve_org`, analyst-role write). Not UI-verifiable here: single tenant driven, and there is **no read surface** to probe cross-tenant leak. |
| 11 | Accessibility | **55 (partial)** | med | Import is a real keyboard-reachable `<button>`; hotkey nav works. But triage table/buckets never render (empty), so table focus/keyboard/contrast unexercised. Empty-state mono hint (`C.ink40`) is very low-contrast gray. |

**Make-vs-buy crossover (P2 core ask):** NOT exercisable from a manifest-only import. The capability-investment "one-acquisition unlock" ranking and the acquisition-modal capex-vs-crossover both read **stored gap/cost data** that only exists after geometry is costed (W1). A manifest of declared part numbers produces no crossover, no provenance chips, no numbers. Honest empty state (`ranking:[]`, `total_blocked:0`) — but the W4 promise of "one-acquisition unlock ranking" is unreachable via this workflow. Honest gate, reported.

**Overall W4 Product score = MIN = 35** (gated by the manifest → triage black hole).

---

## Findings (structured schema)

### F1 — BLOCKER: imported manifest parts never reach triage or any UI (data black hole)
```
persona: P2 sourcing lead
flow: W4 bulk manifest → triage
branch: happy path
category: Functional correctness / Data fidelity
observed:  POST /manifest/import returns {"imported":8,...} and a success toast "8 imported · 0 updated · 0 skipped".
           Triage immediately re-reads GET /catalog/makeability → summary.total = 0. Screen STILL shows
           "No parts to triage yet." Reproduced with 3 more parts (total stays 0). The imported parts appear
           in NO screen: triage reads makeability (geometry/cost projection), and the frontend calls
           GET /manifest / /manifest/coverage NOWHERE (grep: /manifest/import is the ONLY manifest call in src/).
expected:  A sourcing lead uploads their SAP/Excel BOM and sees the portfolio populate — buckets/counts, or at
           minimum a "declared, awaiting geometry" cohort and the coverage headline. The empty-state copy directly
           above the button literally promises "import a whole BOM — and the catalog collapses into honest
           makeability buckets." The flow does not keep that promise.
evidence:  w4-05-triage-after-import.png (8 parts imported, "No parts to triage yet" persists);
           w4-04-good-import-toast.png; network log: POST /manifest/import 200 {"imported":8} followed by
           GET /catalog/makeability 200 {"total":0}; perf.mjs: import 3 parts → makeability.total still 0.
failure_reason: Two disjoint identities. Makeability/triage is a GROUP BY over the geometry-derived
           `part_summaries` projection (analyses). Manifest import writes `ManifestPart` (declared part_ids,
           no geometry). Nothing joins them, and no UI reads the manifest list or /manifest/coverage. Also
           `onManifest` (triage-screen.tsx:273) never refetches makeability/coverage after a successful import.
severity: blocker
confidence: high
recommended_fix: (1) Refetch makeability + a new coverage headline inside onManifest so the screen updates
           without a manual reload; (2) surface the declared manifest — render GET /manifest list + GET
           /manifest/coverage (with_geometry/without_geometry, by_program) on the triage screen; and/or fold
           declared-but-uncosted ManifestPart rows into the rollup as a distinct honest cohort
           (e.g. "declared · awaiting geometry") so the sum reflects what the user just uploaded.
status: open
```

### F2 — MAJOR: W4 workflow promise ("portfolio triage" / "one-acquisition unlock") unreachable from a manifest
```
category: Functional correctness / AI-fidelity(crossover)
observed: capability-investment returns ranking:[], total_blocked:0; no make-vs-buy crossover, no provenance
          chips, no $ from a manifest-only import. These require costed geometry (W1), which a declared BOM lacks.
expected: SPEC §W4 lists "one-acquisition unlock ranking" as the workflow outcome; P2's make-vs-buy is the
          headline deliverable. From the documented W4 entry (manifest import) none of it is reachable.
evidence: perf.mjs / driver2.mjs network: GET /catalog/capability-investment 200 {"ranking":[],"summary":{...total_blocked:0}}.
failure_reason: W4 as specced conflates "declared inventory onboarding" with "triage at scale", but triage
          is geometry-derived. The manifest is a dead-end input unless matching geometry is also uploaded/costed.
severity: major
confidence: high
recommended_fix: Either wire manifest coverage into triage (F1) so the manifest at least shows geometry-coverage
          and declared cohorts, or make the empty-state copy honest that a BOM alone does not produce buckets/crossover.
status: open
```

### F3 — POLISH: toast overlaps header controls
```
category: Visual fidelity
observed: The import success/error toast (top-right) overlaps the "Verify a part" button and ⌘K/bell in the header.
expected: Toast should not occlude interactive header controls.
evidence: w4-06-mixed-import-errors.png (toast covers header buttons).
severity: polish
confidence: high
recommended_fix: Offset the sonner toaster below the header, or reserve header z-space.
status: open
```

### F4 — MINOR: empty-state hint contrast
```
category: Accessibility
observed: The mono helper line "bulk BOM ingest posts to /manifest/import..." renders at C.ink40 (very light gray)
          on the light panel — likely below WCAG AA for small text.
expected: >=4.5:1 for body text.
evidence: w4-03-triage-empty.png / w4-05-triage-after-import.png.
severity: minor
confidence: med
recommended_fix: Darken the hint token or increase weight/size.
status: open
```

---

## What WORKS well (evidence, credit where due)

- **Import parsing is exactly right and honest.** Good CSV → `imported:8`; re-import → `updated:8` (idempotent upsert, last-write-wins); mixed CSV → `imported:2, skipped:2` with per-line reasons surfaced verbatim in a toast: *"line 4: unknown material_class 'unobtainium' · line 5: annual_volume not an integer ('heaps')"*; blank line silently skipped (correct, not an error). Evidence: `w4-06-mixed-import-errors.png`, network responses in driver3.
- **Error recovery is graceful.** Empty CSV → HTTP 400 "Empty CSV upload" → "Empty" error toast, no crash. Missing-required-column → `imported:0, skipped:1` with the full expected-header echoed. Evidence: `w4-07-empty-import.png`, `w4-08-noheader-import.png`.
- **Performance is excellent** (24–56 ms API, 34 ms import through the proxy).
- **Reliability deterministic** (makeability=0 reproduced 3×; re-import updated:8 stable).
- **Provenance honesty in triage itself is exemplary** — buckets carry "unknown / never assumed makeable", cold-projection and stale notes are surfaced verbatim, no fabricated verdicts. (The problem is not dishonesty; it's that the imported data never arrives.)

---

## Evidence / screenshots (all under `waveA-shots/`, prefix `w4-`)

| file | shows |
|---|---|
| w4-01-signup.png | signup form |
| w4-02-verify-landing.png | post-signup /verify landing |
| w4-03-triage-empty.png | Triage empty state + "Import manifest CSV" button |
| w4-04-good-import-toast.png | good import success toast ("8 imported") |
| w4-05-triage-after-import.png | **KEY: 8 parts imported, "No parts to triage yet." persists** |
| w4-06-mixed-import-errors.png | per-line error toast (unknown material, bad integer) + "2 imported · 0 updated · 2 skipped" |
| w4-07-empty-import.png | empty CSV → "Empty" error toast |
| w4-08-noheader-import.png | missing-header → header error toast |

## Test assets used
`scratchpad/manifest_good.csv` (8 valid rows), `manifest_mixed.csv` (2 good + unknown-material + bad-integer + blank line), `manifest_empty.csv` (0 bytes), `manifest_noheader.csv` (missing part_id). CSV contract from `manifest_service.py`: required `part_id`; optional description, material_class (∈ {aluminum, polymer, stainless, steel, titanium}), program, parent_assembly, units_per_parent, annual_volume, quantity, region, source, notes.
