# Verify E2E -- human-sim walk (main-loop Playwright drive)

Run 2026-07-05T01:17:27.192Z -- FE 3000 flag ON -- BE 8000 dev HEAD

- [PASS] 0. API signup for session -- http 200
- [FAIL] 0. session cookie -- no dash_session cookie returned
- [PASS] 0b. login form submit -> off /login -- http://localhost:3000/analyze
- [PASS] 0. unauth /verify redirects to login -- http://localhost:3000/login
- [PASS] 1. authed /verify renders (no redirect) -- http://localhost:3000/verify
- [PASS] 1. app shell present --  @keyframes vspin { to { transform: rotate(360deg); } } @keyframes vsc
- [OBSERVED] 1D. honest stub convention present somewhere -- searched shell text
- [OBSERVED] 3. Machines nav (hotkey m) -- http://localhost:3000/verify
- [OBSERVED] 4. Records nav (hotkey r) -- http://localhost:3000/verify
- [OBSERVED] 1. Home nav (hotkey h) -- http://localhost:3000/verify
- [PASS] X. console errors during walk -- none

Screenshots in this dir. FIRST reachable-nodes pass; full flow-tree (part drop, verdict walk, env door, edge cases) per outputs/testing/verify-flow-tree.md is the next agent job.

## Visual confirmation + first findings (orchestrator, live drive)
- **PASS** `/verify` renders live authed on a fresh org — light-instrument register, on-thesis. Screenshot 01-verify-home.png.
- **PASS honesty states** rendered live: `0 RECORDS`, `0 MACHINES DECLARED`, `— VALIDATED BANDS · NO DATA YET` (honest, not faked 0), designed empty states ("your first verdict is one drop away"), machines-first ("declare your floor — everything starts from the denominator"), hatched flywheel band. No fabricated numbers on screen.
- **PASS** zero console errors during the walk.
- **FINDING [nav]** rail hotkeys m/r/h did NOT change the screen (03/04/05 byte-identical to home) — nav is via rail-icon CLICKS, not the H/V/P/R/G/M/T/C hotkeys the design README claims. Either hotkeys are unwired or need focus. Drive rail clicks in the fuller pass; decide whether hotkeys should work.
- **NOT YET DRIVEN (next agent, full flow-tree):** part drop → verdict walk, environment door + NACE re-verify, Phase C machine verdict, negative/unknown/geometry-invalid branches, provenance disclosure, units + STEP edge cases, network/auth-failure states. Harness: scratchpad/verify-e2e.mjs (extend it; drive rail clicks + a real file drop).


## Deep walk 2 (rail clicks + part drop) 2026-07-05T01:39:44.509Z
- [PASS] signup
- [PASS] authed /verify -- http://localhost:3000/verify
- [PASS] rail buttons found -- 9 buttons
- [OBSERVED] rail click [0] Home -> screen -- Good morning.
- [OBSERVED] rail click [1] Verify -> screen -- No part yet
- [OBSERVED] rail click [2] Parts -> screen -- Parts catalog
- [OBSERVED] rail click [3] Records -> screen -- Records
- [OBSERVED] rail click [4] Programs -> screen -- Programs
- [OBSERVED] rail click [5] Your machines -> screen -- Your machines
- [OBSERVED] rail click [6] Triage -> screen -- Triage at scale
- [OBSERVED] rail click [7] Calibration & truth -> screen -- Calibration & truth
- [PASS] file input present -- 1 inputs
- [PASS] part uploaded (test_cube.stl)
- [PASS] verdict/DFM rendered --  @keyframes vspin { to { transform: rotate(360deg); } } @keyframes vscreenIn { from { opac
- [PASS] honesty on verdict screen -- searched
- [OBSERVED] console errors -- Failed to load resource: the server responded with a status of 400 (Bad Request)

## Money-path bug — found, fixed, status (human-sim E2E, main-loop)
- **PASS** rail-CLICK nav works across all 8 surfaces (Home, Verify, Parts, Records, Programs, Your Machines, Triage, Calibration & truth). Screenshots rail-0..7.
- **FINDING [nav]** rail HOTKEYS (m/r/h) do nothing; nav is click-only. Decide whether hotkeys should work (design README claims H/V/P/R/G/M/T/C).
- **PASS** part drop → verdict walk renders live: real 3D geometry on the stage (test_cube.stl), environment door, and the HONEST UNKNOWN verdict ("should-cost unavailable / makeability not evaluated — declare your floor or a world, never assumed"). No fabricated verdict. Screenshot 10-verdict-walk.png.
- **BUG FOUND (money path) → FIXED:** `POST /validate/cost -> 400 "At most 6 quantities allowed"` on EVERY drop — UI sent a 10-point QTY_LADDER; backend caps at `_MAX_QTYS=6` (routes.py:233). Cost degraded to "should-cost unavailable". Missed by unit tests AND the backend curl-proof (both sent ≤6 qty). Fix: clamp QTY_LADDER to 6 log-spaced points (run.ts) — merged to dev (ee10a85), tsc+181 tests+build green. **Live visual re-confirm PENDING** (signup rate-limited 429 this session after many test accounts) — reset agent: clean re-drive to confirm the should-cost + crossover render.
- **FINDING [chrome]** the login/auth page is dark and still tagged "should-cost, made of glass" (old thesis) — auth chrome not re-thesised to "verification, made of glass". Minor.
