# CadVerify — Platform Gap-Map Implementation State

**Backlog:** `outputs/audit/platform-gap-map.md` (5-lens expert audit, 2026-07-01).
**Discipline:** feature branch off `dev` → tests pass → WIP behind a flag → adversarial Verifier → merge to `prod`. `prod` stays demo-ready.

## Branch topology
- `main` — history + checkpoint `95ad0c4` (versioned the previously-uncommitted running demo state incl. the whole cost engine; closes audit F-ARCH-8).
- `prod` — demo-ready line. Only verified + production-worthy work merges here.
- `dev` — WIP integration. Feature branches cut from here.
- Feature branches: `feat/<item>` per gap-map item.

## Items (audit priority order)

| # | Phase | Item (gap-map finding) | Area | Status |
|---|-------|------------------------|------|--------|
| 1 | 1 | Scope DFM flags to the RECOMMENDED process (kill "78 flags/15 critical" summed across 21 processes) — DFM audit FRAGILE-1 | frontend + api presentation | ✅ MERGED to prod (6bdf3ff). 3 adversarial verifiers PASS; process-name identity proven end-to-end. Flag NEXT_PUBLIC_DFM_SCOPED_FLAGS (default ON). |
| 2 | 1 | CNC real volume/learning curve so cost drops 100→10k and make-vs-buy crossover behaves (currently flat) — cost audit S1 | backend/src/costing | ✅ MERGED to prod (2511e92). Wright learning curve ~49% drop 100→10k; numerical crossover proven monotone; validated stays False. Flag CADVERIFY_CNC_LEARNING (default ON). Zoox-gated: curve magnitude. |
| 3 | 1 | Cap engine memory (fix ~19 GB OOM on ordinary 37k-face part) — arch audit P0 | backend/src/analysis | TODO |
| 4 | 2 | Persist + export/share/compare the should-cost decision (flagship artifact; currently ephemeral) — product gap #3 | db + api + pdf + frontend | TODO |
| 5 | 3 | `/health` honest + async tier fails loud (serves #1 global no-lying-stub rule) — arch F-ARCH-1/2 | backend | TODO (if cap allows) |

## Human-gate queue (cannot self-certify — prepared, never faked)
- **Cost/DFM number correctness** → Zoox Head of Manufacturing on real parts + real quotes (load into groundtruth.py held-out eval).
- **SAML vs real IdP + pen test** → security engineer / accredited firm.
- **SOC2 readiness** → qualified auditor. **ITAR/export** → legal.
- **Load/soak test** on real Postgres+Redis+worker → SRE.

## Notes
- No central settings module; feature-flag convention is `os.getenv("FLAG", default)` per-module.
- Backend test baseline: 564 tests collected; `.venv` present (py3.9). Frontend: Next.js.
- Phase-3 deeper-cost-correctness items are GATED by Zoox validation → prepare packet + queue, do not self-certify.
