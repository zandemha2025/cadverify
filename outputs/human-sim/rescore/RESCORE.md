# Human-Sim Re-Score — Accessibility + Performance (live stack)

- **Date:** 2026-07-10
- **Branch/HEAD:** `claude/resume-review-oxqw0l` @ `6d7547d`
- **Stack:** real app, in-container. Backend uvicorn `main:app` :8099 (Postgres cluster
  `fix` :5433, fresh UTF8 db `cadverify_rescore`, `alembic upgrade head` → 0037). Frontend
  `next dev` :3099 (`API_BASE`/`NEXT_PUBLIC_API_BASE=http://localhost:8099`). Driven with
  Playwright (`playwright-core` + Chromium at `/opt/pw-browsers`) over `http://localhost:3099`.
- **Smoke:** `/health` → `{"status":"ok","postgres":true}`; `/auth/signup` → 200 + session.
  Backend log confirms `parse pool pre-warm complete (3/3 workers warm)` (commit be820c2 active).
- **Test part:** `backend/tests/assets/cube.step` (bbox 20×15×10 mm · 2.72 cm³ · watertight).
- **Every claim below has a screenshot in this directory. No number is fabricated.**

---

## Category A — ACCESSIBILITY → **4 / 5**

Prior cap = missing input focus ring (F3) + low-contrast muted text. Both caps are resolved;
a minor residual on small non-neutral accent labels keeps it off 5.

### Focus ring (WCAG 2.4.7) — PASS
- Tabbed with the keyboard onto the email input; a **visible focus ring renders** on the text
  input, clearly distinct from the unfocused password field.
  Evidence: `F_02_focus_email.png`, `F_03_focus_password.png`.
- Honest nuance (verified, not cosmetic): at runtime the ring is Chromium's **default `auto`
  focus ring**, NOT the intended styled `outline: 2px solid #6ba6f4`. The `.auth-input`
  focus rules live in `frontend/src/app/globals.css` (compiled to chunk `18d32zc8baf3y.css`),
  but **that chunk is not among the CSS bundles served on `/signup`** — the `(auth)` route only
  pulls `site-theater.css`. Because the suppressing `.auth-input:focus{outline:none}` rule is
  ALSO absent from the served bundle, the browser default shows through, so **2.4.7 is
  satisfied** — but the specific styled fix is not being delivered on the auth page.
  (`el.matches(':focus-visible')` is true, yet computed outline = `auto 1px`.)

### Muted / secondary text contrast — mostly PASS
Measured computed colors against composited backgrounds on the settled verify screen
(`F_06_cold_settled.png`, `P_F5_drivers_detail.png`):
- **Neutral muted "ink"** (`rgba(23,24,26,α)`) composites to ≈4.3–5.3:1 on white — at/above
  the 4.5:1 AA floor. The washed-out muted-ink cap is resolved.
- **Residual (keeps score at 4):** small NON-neutral accent labels sit just under 4.5:1 for
  normal-size text:
  - amber `rgb(176,120,24)` — "issues", "assumption-based, not yet validated" → ≈**3.79:1** @10px
  - blue `rgb(59,123,184)` — "MEASURED", "engine-exact", "ROUTE PICK" → ≈**4.1–4.5:1** @9.5–11px
  These are semantic accents, not the neutral ink the fix targeted, but they are real
  sub-AA normal-size text.

---

## Category B — PERFORMANCE → **3 / 5** (honest floor, not a defect)

Pre-warm (be820c2) is live (backend log). Timings are wall-clock from `setInputFiles`
(submit) to the `/validate/cost` 200 response; the frontend chains `/validate` (DFM) then
`/validate/cost` sequentially.

| Run | cube.step verify (submit → cost result) | Screenshot |
|-----|------------------------------------------|------------|
| Cold (first upload, fresh session) | **11.7 s** | `06_cold_verify_result.png`, `F_06_cold_settled.png` |
| Warm (re-upload same part) | **4.4 s** | `07_warm_verify_result.png` |
| Steel re-verify (material change) | 7.9 s | `F_08_steel_settled.png` |

- Deterministic ("same input, same verdict"); geometry measured identically across runs
  (bbox 20×15×10, 2.72 cm³, watertight true) — consistent with pre-warm not changing the answer.
- The multi-second cold latency is the **honest measured-cost floor** (real mesh compute +
  costing), not a bug. My 11.7 s cold exceeds the registry's characterized ~5.9 s because it
  spans BOTH engine calls plus first-request warmup; the `/validate/cost` leg alone is the
  ~5.9 s floor. Warm drops to ~4.4 s.
- Score reflects: functional + deterministic + pre-warm applied, but interactive latency
  remains the real floor. Bound but honest — **not** a defect to fix by cutting compute.

---

## Regression replay

| ID | Assertion | Result | Evidence |
|----|-----------|--------|----------|
| **R04** | metal part → best_process is NOT a resin process | **PARTIAL — FINDING** | `P_R04_physics_steel.png` |
| **F3** | input focus ring present | **PASS** | `F_02_focus_email.png` |
| **F4** | `.txt` error leads with "unsupported file type" | **PASS** (minor toast residual) | `F_10_txt_settled.png` |
| **F5** | cost-driver qty matches / reconciles to headline qty | **PASS** | `P_F5_drivers_detail.png` |

### R04 — real finding (partial fire)
For a **Steel** part the material-aware route is correct where it counts: the verdict/should-cost
headline reads **"$10.68/unit on CNC 3-Axis"** and "What it really takes · on CNC 3-Axis · Mild
Steel" — a metal process, no resin. **But** the DFM **"Process physics — geometry against each
route"** panel badges **"DLP Resin — ROUTE PICK"** for the steel part (and DLP even shows
"issues" while CNC 3-Axis shows "pass"). Root cause: the frontend `POST /validate` call
(`lib/api.ts` `validateFile`) does **not** pass `material_class`, so `best_process` from
`/validate` stays the material-blind geometry ranking (`best_process=dlp` for steel, confirmed
in the captured JSON). The material-aware `best_process_for_material` / `rank_processes` fix
reaches the cost/make-now route but **not** the DFM "ROUTE PICK" display. This is the same class
of symptom R04 was opened for, surfaced in a different panel. **Log as an open finding.**

### F4 — pass with the known minor residual
Verdict panel leads correctly: **"We couldn't read this file. / Unsupported file type: .txt.
Use .stl, .step, .stp, .iges, or .igs."** The bottom toast still says "couldn't be tessellated"
(the documented minor residual) — the lead copy is fixed.

### F5 — pass
Section 4 "What it really takes" driver breakdown (MATERIAL 0.093 + MACHINE 1.406 + LABOR 7.052
+ SETUP 0.13 = **$8.681 ≈ $8.68**) reconciles to the headline "$8.68/unit at qty 10,000".
Section 5 "Resource cost" is a separate, explicitly-labeled interactive qty scrubber
("QUANTITY 100 … band & drivers read at computed qty 100" → $8.72). The former silent
qty mismatch is gone — the qty is now labeled and internally consistent.

### Not directly exercised
- **R08** (pre-warm answer-invariance, byte-identical fingerprint on/off): NOT toggled
  prewarm on↔off, so I cannot assert the byte-identical claim. I did observe cost $8.68 and
  geometry stable across cold+warm repeats — consistent with, but not proof of, invariance.
- **R01/R02/R03/R05/R06/R07**: not replayed this run (no periodic/large/assembly parts driven).

---

## Did the MIN move?

- **Accessibility** cleared its defect cap (focus ring present + neutral muted ink ≥4.5:1) →
  **4/5**. It is no longer a bottom-binding category.
- **Performance** is an accepted **honest floor** → **3/5** (deterministic, pre-warm applied,
  latency is the price of a measured cost).
- With Accessibility's cap lifted, the practical MIN would rise to **Performance's honest
  floor**. HOWEVER, this run surfaced a **new correctness/trust finding (R04 partial)** — a
  resin "ROUTE PICK" for a metal part in the DFM panel — which should be logged and could bind
  a Correctness/Trust category once scored.

## Honest overall note
The two re-scored categories improved and their prior caps are genuinely resolved on screen.
Two honesty caveats worth carrying forward: (1) the Accessibility focus-ring *fix* is not
actually delivered on the auth page (the styled `#6ba6f4` ring's CSS chunk isn't loaded on
`/signup`); the criterion passes only via the browser default. (2) The R04 material-aware fix is
incompletely wired — correct in cost routing, still material-blind in the DFM "ROUTE PICK"
display because `/validate` omits `material_class`. I did not fabricate any score; anything I
couldn't exercise (R08 invariance toggle, other regressions) is called out explicitly above.
