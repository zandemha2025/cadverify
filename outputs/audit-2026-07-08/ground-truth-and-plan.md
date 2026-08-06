# CadVerify — Ground Truth + Orchestration Plan (2026-07-08, Fable)

Baseline: `origin/codex/worktree-cleanup-20260708` (migrations→`0035`, Verify UI, SCIM/connectors). Two grounding efforts (live truth-audit E2E + connector research) landed; this is the synthesis + the prioritized build queue Fable is driving with Opus 4.8 builders.

---

## A. Ground-truth audit verdict (live stack, real browser, in this container)
**Substantially real, not a stub farm.** Stack runs fully here (Postgres, FastAPI, redis+arq worker, Next 16 frontend, Playwright). Core flow works end-to-end on real engine output. Honesty discipline is real and consistent: withheld verdicts when no machines/world declared, NACE-cited material strikes on sour service, `validated:false` everywhere, n=0 bands, `/health` honest, 152/152 routes authenticated. Backend suite: **1411 passed / 6 failed / 35 skipped** (see defects).

Fidelity (founder's explicit asks):
- **STL → REAL geometry** in the viewer. **STEP → honest bounding-box envelope** (backend tessellates 185K faces via gmsh but discards the mesh; client gets only the bbox). Labeled honestly ("mesh discarded after measurement"), but a STEP part does **not look like itself** — a real trust gap.
- **Service environment REACTS** — sour service strikes non-compliant materials with cited standards; part re-seats in context.
- **Verdict reacts to real inventory** — added 2 machines via CRUD, per-route makeability changed correctly (aluminum→makeable on owned Haas; steel+sour→outsource-only because engine routes to a 5-axis not owned). Real discrimination.
- **Cost/crossover REAL**, `validated:false` honest.

## B. Connector strategy (research, cited) — answers "be the connector?"
No single third-party pipe to the manufacturing core. **Identity is the one place the dream is true** (SSO/SCIM = standards; customer configures in their IdP; already built — SAML SP + SCIM 2.0). Unified-API vendors (Merge/Nango/Paragon) cover common SaaS, **not** SAP/PLM/procurement. Architecture = thin internal Connector SPI + per-adapter, with an honest sellable-claim ladder:
- A **SSO/SCIM** — finish + certify vs free Okta/Entra sandboxes.
- B **Autodesk APS** — free dev tier, best demo value (CAD/BOM).
- C **SAP S/4HANA** — build vs api.sap.com mock sandbox ("sandbox-validated", not "live SAP").
- D **Coupa/Ariba/cXML** — open spec + fixtures ("PunchOut-ready", not "certified").
- E **Windchill/Teamcenter PLM** — draft adapter + fixture-replay only until a real tenant (don't overclaim — the rung most likely to get caught in an Exxon review).

## C. Repo divergence (flag for founder — real, not silently merged)
`codex/worktree-cleanup-20260708` (07-08, mig 0035) is the truth I build on. But `prod`/`dev` (07-04) carry 176 commits codex lacks yet sit at mig 0023 — a separate (verify-UI/site) line. **These two lines need a real reconciliation/merge decision.** Not doing it silently.

---

## D. Prioritized build queue (Fable directs, Opus executes, human-sim E2E gates)

### Wave 1 — grounded defects that hit the founder's explicit bars (IN FLIGHT)
1. **[correctness] `/validate` 500 on degenerate/non-watertight meshes.** NaN `center_of_mass` → invalid JSON → JSONB insert throws; a server-error toast leaks to the user (the cost path already refuses cleanly with 400). Fix: sanitize non-finite floats / guard before persist. + fold in the 2 stale `test_frontend_api_config` assertions and the missing `aiosqlite` test dep so the suite is fully green. → **no errors, clean repo.**
2. **[fidelity] STEP renders as its real shape, not a box.** Stream the gmsh tessellation (decimated) to the viewer; wire `stage-canvas.tsx` to render the real shell. → **the part displays correctly**, the founder's recurring ask.

### Wave 2 — enterprise workstreams (buildable here, honest-labeled)
- **Identity cert path** (Rung A): finish OIDC RP, harden SCIM PATCH, cert vs free Okta/Entra.
- **Autodesk APS** (Rung B) real sandbox integration.
- **Ops truth gate**: object-store abstraction, strict worker health, OTel/k6 starters, backup/restore + soak proof.
- **Security-audit readiness**: ASVS matrix, tenant-isolation adversarial suite, SAST/DAST/dep/container scans.
- **SAP mock (C) · cXML (D) · PLM draft (E)** per the ladder.

### External-gated (prepared, never faked)
Real customer pilot data (accuracy validation), SOC2/pen-test, live supplier sends, a real customer SAP/Windchill tenant.

**Discipline every slice:** Opus build → adversarial verify (distinct lenses) → Fable gates + re-verifies crux → **human-sim E2E screenshot proof** → integrate. Nothing merges as "true" without a real run behind it.
