# Impl Harness — Event Log

Format: `<UTC-ish date> | EVENT | detail`

- 2026-07-01 | RUN-START | Backlog = platform-gap-map.md. Cap=6. Phase order enforced.
- 2026-07-01 | SETUP | Checkpointed running demo state (cost engine + working tree) as `main@95ad0c4` — closes audit F-ARCH-8 (core IP was unversioned). Gitignored 23MB sample zip + `*.zip`.
- 2026-07-01 | SETUP | Created `prod` (demo-ready) and `dev` (WIP) branches at checkpoint. Feature branches cut from `dev`.
- 2026-07-01 | BASELINE | Backend suite 564 tests collected; establishing green baseline before item 1.
- 2026-07-01 | BASELINE-GREEN | Full backend suite: 558 passed, 6 skipped, 0 failed (455s). This is the pre-change baseline for attribution.
- 2026-07-01 | CYCLE-1-START | Item 1 (DFM scope) builder on feat/dfm-scope-flags (shared tree, frontend). Items 2 (CNC volume, feat/cnc-volume) + 3 (engine memory, feat/engine-memory) building in parallel isolated worktrees (disjoint backend files). Verify+merge sequential in phase order.
- 2026-07-01 | VERIFIED+MERGED item-1 dfm-scope-flags | 3 adversarial verifiers (identity/hidden/gate) high-confidence PASS. Process-name identity PROVEN end-to-end (same ProcessType enum .value across DFM + cost). npm test 7/7, tsc clean. Merged feat/dfm-scope-flags → dev → prod (6bdf3ff). prod==dev, demo-ready. Non-blocking nits logged in outputs/verify/dfm-scope-flags.md.
- 2026-07-01 | CYCLE-2-VERIFY item-2 cnc-volume | Builder cc9de08 on feat/cnc-volume: Wright learning curve on attended conversion cost (~47-48% drop 100→10k), numerical crossover, DEFAULT/assumption-tagged, validated stays False. ENV NOTE: builder reported 3 test_cost_api shop-profile failures — root-caused as WORKTREE artifact (gitignored `backend/data/shop_profiles/` absent in fresh worktrees; the 3 tests PASS in main tree & with a symlink). Symlinked backend/data into both worktrees. Running full-suite gate + 3 adversarial verifiers (finding/honesty/crossover).
- 2026-07-01 | VERIFIED+MERGED item-2 cnc-volume | finding+honesty high-conf PASS; crossover proven (synthetic 1000/2000 monotone; wiring confirmed); full-suite gate 561 passed / 0 failed (backend/data symlinked). Merged feat/cnc-volume → dev → prod. Emergent Wright curve, validated stays False. Zoox-gated: curve MAGNITUDE (not direction). See outputs/verify/cnc-volume.md.
