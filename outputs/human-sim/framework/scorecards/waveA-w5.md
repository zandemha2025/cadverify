# Scorecard — Wave A · W5 (machine inventory → per-machine makeability + gap analysis)

- **Persona:** P3 — Shop owner / in-house manufacturing manager
- **Flow:** W5 — Configure machines → makeability, driven through the REAL app (Playwright + vision)
- **Date:** 2026-07-10
- **Stack:** worktree `waveA-w5` @ ea1be29 · backend :8044 (db `cadverify_w5`) · frontend :3044 (main-tree served — identical code @ ea1be29 because Turbopack rejects an out-of-root `node_modules` symlink; see Setup note)
- **Smoke gate:** `/health` → `postgres:true`; signup → 200 + session. PASS.
- Screenshots: `scorecards/waveA-shots/w5-*.png`

## Setup note (not a product bug)
The prescribed `ln -s <main>/node_modules` inside the worktree frontend makes Turbopack abort:
`Symlink [project]/node_modules is invalid, it points out of the filesystem root`. Since the main
tree is at the SAME commit (`git diff ea1be29 HEAD -- frontend/src` = 0 files), I ran `next dev` from
`/home/user/cadverify/frontend` (real node_modules) pointed at backend :8044 — byte-identical W5 code.
Worth surfacing in the runbook: the symlink recipe does not work under Next 16 / Turbopack in a worktree.

---

## Category vector (Bucket A)

| # | Category | Score | Confidence |
|---|---|---|---|
| 1 | Functional correctness | 90 | high |
| 2 | Data fidelity | 80 | high |
| 3 | AI fidelity (routing / gap reasoning) | 96 | high |
| 4 | Interaction fidelity | 82 | high |
| 5 | Visual fidelity | 93 | high |
| 6 | Performance | 78 | high |
| 7 | Reliability | 90 | med (N-run partial) |
| 8 | Conversational | N/A (not exercised — "Ask the engine" not driven) | — |
| 9 | Error recovery | 84 | high |
| 10 | Security | 85 (partial — full cross-tenant 2-org not driven) | med |
| 11 | Accessibility | 65 | high |
| 12 | Regression | N/A (registry replay out of scope for this run) | — |

**W5 product minimum = 65 (Accessibility)** — reported as the honest weakest gate, not an average.
The makeability *engine itself* is the strongest thing in this flow (96).

---

## What was driven (branches, all real clicks)

1. **No machines** → verify cube (Aluminum). `verification: NULL` → honest "not evaluated" banner. ✓
2. **Configure inventory** → declared `Haas VF-2 big`, CNC 3-Axis, envelope 2000×1000×800mm, materials aluminum/steel/stainless, $95/hr, 500kg. Detail card fully provenance-tagged ●USER (`w5-05-detail.png`).
3. **Own the right machine** → verify cube (Aluminum): `makeable_in_house`, best machine **Haas VF-2 big**, marginal should-cost **$10.48/unit on CNC 3-Axis**, per-route lattice ✓cnc_3axis / ✗ all others "outsource only" (`w5-06-own-cnc-alu.png`).
4. **Near-miss (edit envelope → 5×5×5)** → re-verify: `makeable_not_on_owned` with concrete gap **"envelope: need 20, have 5"** (`w5-08-nearmiss-gap.png`). Edit re-derived the verdict.
5. **Steel + sour service** → `makeable_outsource_only`; routing flips to **cnc_5axis (unowned) → outsource**; env_exclusions cite **NACE MR0175** ("Mild Steel excluded: sour service requires NACE MR0175 qualification") (`w5-09-steel-sour.png` walk overlay).
6. **Delete machine** → re-verify: verdict `unknown`, `inventory_declared:false` → "makeability not evaluated — declare your floor" (`w5-10`, `w5-11`). Delete re-derived.

---

## Findings (structured)

### F1 — Materials field placeholder suggests tokens the backend rejects (Data fidelity / Interaction / Error recovery)
- **observed:** Add-machine form materials placeholder is literally `6061, 316L, PP`. Typing `6061, 316L, ss304` → **HTTP 400** `unknown material '6061' (not a known material or class); unknown material '316L'; unknown material 'ss304'`. Machine is NOT created. Evidence: `w5-04-list.png` (toast + open 400), backend log `POST /api/v1/machine-inventory 400`.
- **expected:** A shop owner's most natural alloy shorthand ("6061", "316L", "304") should be accepted (or normalized), OR the placeholder/hint must show the ACTUAL accepted vocabulary. The form should not advertise example values its own backend rejects.
- **root cause:** `machine_inventory_service._validate_materials` accepts only the 5 classes {aluminum, polymer, stainless, steel, titanium} or exact registry names (`6061-T6 Aluminum`, `SS316L`, `304 Stainless`, `Mild Steel`, …). The frontend placeholder (`machines-screen.tsx:641`, `placeholder="6061, 316L, PP"`) lists none of those exact forms — `PP` also fails.
- **severity:** major (blocks the first natural attempt for every new shop; P3-hostile). **confidence:** high.
- **recommended_fix:** Either (a) alias common alloy shorthands in `_validate_materials` (6061→6061-T6 Aluminum, 316L→SS316L, 304→304 Stainless, PP→PP (Molded)), or (b) replace the placeholder with a real picker / valid-token hint and echo the accepted list on error. #1 fix.
- **status:** open.

### F2 — Machine-form text inputs have no visible keyboard focus indicator (Accessibility, WCAG 2.4.7)
- **observed:** Focused NAME input computed style = `outlineStyle:none, outlineWidth:0px, boxShadow:none` (empirical, `a11y.mjs`). No focus ring on any machine-form text input.
- **expected:** A visible focus indicator on every keyboard-focusable field.
- **root cause:** `inputStyle` sets inline `outline:"none"` (`machines-screen.tsx:473`). The shell's `.cv-verify-shell input:focus-visible { outline: 2px solid #17181a }` (`verify-app.tsx:449-451`) uses the `outline` property, which an **inline** `outline:none` overrides (inline beats stylesheet). Buttons (no inline outline) DO get the ring — only these inputs are affected.
- **severity:** major (a11y). **confidence:** high.
- **recommended_fix:** Drop inline `outline:"none"`, or give the focus-visible rule a property inline can't pre-empt (e.g. `box-shadow: 0 0 0 2px #17181a`) with `!important`, or move the base style to a class.
- **status:** open.

### F3 — Verify latency high for a trivial part (Performance)
- **observed:** Full verify walk (parse + cost + makeability) measured **7.9s–11.2s** for a 20×15×10mm cube (185k-face STEP). Signup 3.5s; screen nav ~1s. Real ms in `w5drive2` TIMINGS.
- **expected:** Sub-second-to-few-seconds for a tiny prismatic block; ~10s reads as slow to a shop owner iterating machine configs.
- **severity:** minor. **confidence:** high. **recommended_fix:** profile the STEP tessellation / cost path for small parts; the makeability re-derive itself is cheap — the cost/parse dominates.
- **status:** open.

### Positive confirmations (AI / Data fidelity — no fabrication found)
- **Owning a machine flips the verdict in-house and NAMES the machine** (Haas VF-2 big); other process families honestly `makeable_outsource_only` (0 machines). No fabricated pass.
- **Gap analysis is concrete**, not vague: `need 20, have 5` measured-geometry × user-capability, tagged as "what you'd acquire."
- **Marginal cost on owned capital** surfaces ($10.48/unit on CNC 3-Axis, machine_rate_usd=95 in the per-route block).
- **Environment gate is coherent:** steel+sour → NACE MR0175 exclusion cited per material, routing pushed to unowned 5-axis → outsource.
- **Edit and delete both re-derive** the verdict live (in-house → not-on-owned on envelope edit; → unknown on delete).
- **Honest empty/unknown states:** no inventory → `verification: NULL` / "declare your floor"; deterministic toast "same input, same verdict, every time."
- **Provenance discipline:** every declared cap tagged ●USER; rate history states "no governed rate card in effect — this rate is your ●USER declaration."

### Security (probes)
- Unauthenticated `GET /api/v1/machine-inventory` → **401**; unauthenticated `POST` → **401**. Routes are session/org-scoped in code.
- **Partial / honest gate:** full cross-tenant isolation (org A cannot see org B's machines) was NOT driven with two live orgs this run — code path is org-scoped but not exercised end-to-end here.

---

## Top findings ranked
1. **F1 — materials placeholder rejects its own suggested tokens (400, machine not created).** Major. `w5-04-list.png` + backend log.
2. **F2 — no visible focus ring on machine-form inputs (WCAG 2.4.7).** Major. `a11y.mjs` computed-style evidence.
3. **F3 — 8–11s verify latency for a trivial cube.** Minor. TIMINGS.

## #1 fix
Alias common alloy shorthands (6061, 316L, 304, PP, …) in `machine_inventory_service._validate_materials`
AND make the materials field advertise real accepted tokens — so a shop owner's first, natural inventory
entry succeeds instead of 400-ing on the exact values the form itself suggests.
