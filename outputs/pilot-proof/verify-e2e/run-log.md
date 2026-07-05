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
