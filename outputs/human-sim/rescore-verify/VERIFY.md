# Rescore verification — R09 + R10 on-screen (live stack)

Date: 2026-07-10 · Persona: human-sim QA · Model driver: Playwright + Chromium
HEAD: `f5478f0` (fix commit `ffbff76` in history) · branch `claude/resume-review-oxqw0l`
Stack: backend uvicorn @127.0.0.1:8098 · frontend Next @localhost:3098 · Postgres 5433 (fresh UTF8 db `cadverify_rsv`, `alembic upgrade head`)
Smoke: `/health` → `{"status":"ok","postgres":true}` · `/auth/signup` → 200 + session.

Part driven: `backend/tests/assets/cube.step`, material **Steel** declared via the DECLARED MATERIAL CLASS selector (so `/validate/cost` runs material-aware).

---

## FIX 1 — R09: steel part must NOT show a resin ROUTE PICK — **PASS**

- In the "Process physics — geometry against each route" panel (Step 3), the **ROUTE PICK** badge sits on **CNC 3-Axis** (a metal route), NOT on DLP Resin. DLP Resin still appears as the top geometry row but carries only an "issues" badge, no pick.
- Actual pick label seen: **"CNC 3-Axis  ROUTE PICK"** (blue material-aware label — not "GEOMETRY PICK", because steel was applied to the cost route).
- Footer basis line reads: *"15 priority fixes across routes · overall issues · DFM scores from POST /validate · **pick reconciled to the material-aware route (CNC 3-Axis)**"*.
- Agreement confirmed on the same screen:
  - Should-cost header: **"Should-cost $10.68/unit on CNC 3-Axis at qty 10,000"**.
  - Step 4 "What it really takes": **"on CNC 3-Axis · Mild Steel"**.
  - Step 5 make-now card: **"CNC 3-Axis — MAKE NOW"** · engine note "Make by cnc_3axis (Mild Steel)".
- Steel WAS applied to the cost route (material-aware path exercised) — so this is a true "ROUTE PICK", not the GEOMETRY-PICK fallback.

Screenshots:
- `r09-process-physics.png` — full right panel: Steel declared, should-cost CNC 3-Axis, Process physics ROUTE PICK on CNC 3-Axis + footer basis line.
- `r09-cost-makenow.png` / `r10-top.png` — Step 4/5 showing "on CNC 3-Axis · Mild Steel" + CNC 3-Axis MAKE NOW (agree with the pick).
- `r09-routepick-crop.png` — close crop of the CNC 3-Axis ROUTE PICK badge.
- `r09-fullpage.png` — full-page context.

## FIX 2 — R10: small accent labels meet contrast — **PASS**

- Provenance chips render in a clearly saturated darker blue: **"watertight true · ● MEASURED"** and **"● real shell · 41k-tri preview"** — legible, not washed-out.
- The amber route badges read **"issues"** in a saturated dark amber; **"pass"** in dark green; **"ROUTE PICK"** in saturated blue — all clearly readable at their small mono size.
- Matches the darkened tokens shipped in `ffbff76`: measured-blue `#3772ab` (4.68:1), amber "issues" `#966614` (4.62:1, was 3.79:1 sub-AA), pass `#1d7f54` (4.61:1) — all now clear WCAG-AA 4.5:1. No visual regression.

Screenshots:
- `r10-measured-chip.png` — close crop of the ● MEASURED / ● real shell provenance chips.
- `r10-issues-badges.png` — close crop of the amber "issues" + green "pass" + blue "ROUTE PICK" accents.

---

Verdict: **R09 PASS · R10 PASS** — both fixes verified on screen against the live stack with a steel-declared part. No fabricated evidence; all reads captured from the running app.
