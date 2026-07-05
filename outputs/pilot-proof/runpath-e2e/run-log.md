# B2(b) re-drive — should-cost render (qty-ladder 400 fix ee10a85)

Run 2026-07-05T02:14:39.770Z -- FE 3000 (NEXT_PUBLIC_VERIFY_UI=1) -- BE 8000 -- fresh signup e2e_runpath_1783217671166@pilot.test

**VERDICT: CONFIRMED** — cost HTTP 200, SHOULD-COST COMPUTED=true

- [PASS] 0. fresh API signup -- http 200
- [PASS] 1. login form -> off /login -- http://localhost:3000/analyze
- [PASS] 2. authed /verify renders (no 404/redirect) -- http://localhost:3000/verify
- [SAVED] shot 20-verify-home
- [PASS] 3. file input present
- [PASS] 3. dropped demo part -- test_cube.stl
- [SAVED] shot 21-should-cost
- [SAVED] shot 22-cost-drivers
- [PASS] 5. POST /validate/cost status -- 200
- [PASS]    cost call -- 200 http://localhost:3000/api/proxy/validate/cost
- [PASS] 6. SHOULD-COST COMPUTED in DOM -- present
- [PASS] 6b. should-cost $/unit figure -- Should-cost $21.98/unit on DLP Resin at qty 10,000
- [PASS] X. console errors -- none

Note: a 22-cost-drivers shot was captured but came out byte-identical to
21-should-cost (the verify verdict panel is an inner scroll container, so the
page-level scroll was a no-op); it was removed as a duplicate. 21-should-cost.png
already shows the full should-cost block incl. the cost-driver ladder.
Committed screenshots: 20-verify-home.png, 21-should-cost.png.
