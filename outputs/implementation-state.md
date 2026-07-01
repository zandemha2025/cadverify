# Teardown Implementation — State

**Backlog = the competitive teardown findings** (`outputs/competitive-teardown.md`, `self-audit.md`, `red-team.md`).

## Findings → track → status

| ID | Finding (teardown evidence) | Track | Status |
|----|------------------------------|-------|--------|
| F1 | Per-shop calibration NOT in the live product — no `shop` param on the cost API (`routes.py:585-615`), UI reads "Not calibrated", marketing hero is a hardcoded fixture ($14.14 vs engine's $64.63) | T2 wedge + T1 wiring | **OPEN** → build |
| F2 | Router headlines a process its own DFM hard-fails — `cnc_turning` recommended while DFM flags it FAIL; two definitions of "rotational" (`routing.py:41-47` bbox-squareness vs `checks.py:553-575` inertia) | T2 correctness | **OPEN** → build + **REAL-EXPERT gate** |
| F3 | "Override → re-runs" is cosmetic — handlers relabel client-side + toast "build gap" (`PartWorkspace.tsx:189-210`, `driver-breakdown.tsx:90`); number never moves | T1/T2 | **OPEN** → build |
| F5 | Dev-build hygiene — internal `Parts (Label)` + `Design system` tools in the customer sidebar (`sidebar.tsx:20-44`); marketing renders static fixtures captioned "real output" (`method/page.tsx:57-61`), flagship fixture self-contradicts | T1 polish/credibility | **OPEN** → build |
| F4 | Zero validation (n=0) — no real part ever checked vs a real cost | gate — REAL EXPERT | **QUEUE** (Zoox real-quote session) |
| F6 | SOC2/ITAR trust credential absent (Zoo shipped public SOC2 Type II) | gate — third party | **QUEUE** |
| F7 | "Looks/works like real software" overall | gate — REAL USERS | **QUEUE** (after F1/F3/F5 land) |
| F8 | UX depth — coarse 5-dropdown re-cost, `material_class` manual (engine never infers) | T1 (lower) | **OPEN** (defer / partial) |

## This run (cycle 1) — buildable cluster
Close F1, F2, F3, F5 in code, proven against the teardown evidence. Route F2's *correctness* (and F1's
*numbers*) + F4 + F6 + F7 to the real-expert validation queue. Don't sand off the wedge while polishing.

## Validation queue (real experts — cannot self-certify)
- **Mfg/cost engineer (Zoox Head of Manufacturing):** are the routing recommendations + per-shop numbers CORRECT? (F2 numbers, F1 numbers, F4 the real ±X%).
- **Real target users (design/cost/sourcing eng):** does it now look + work like real software? (F7).
- **Third party:** SOC2 (F6).
