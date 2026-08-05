# CadVerify — Session Handoff (2026-07-08, Fable orchestration)

**Branch with all work:** `claude/resume-review-oxqw0l` (pushed) — tip `bc93f41`.
**Baseline it builds on:** `codex/worktree-cleanup-20260708` (the canonical line — see §3).

This session, Fable (claude-fable-5) orchestrated Opus 4.8 builders in isolated
git worktrees. Every slice: builder → adversarial review → **Fable re-verified the
crux on the correct baseline** → integrated. Nothing merged on a builder's word.

---

## 1. What landed & is pushed (all verified, 0 test failures)

| Commit | Slice | Substance |
|---|---|---|
| `9b24db1` | Wave 1a | `/validate` no longer 500s on degenerate/non-watertight meshes (NaN `center_of_mass` sanitized before JSONB persist). Suite greened. |
| `7a3d7f8` | Wave 1b | STEP/IGES render as their **real tessellated shell** in the Verify stage (zero-egress decimated GLB stream), not a bounding box. `cube.step` 185k→41k faces. Screenshots in `outputs/step-render-proof/`. |
| `0e7a7d9` | Wave 2a | **OIDC Relying Party** (Auth Code + PKCE, RS256-pinned sig verify against fetched JWKS, iss/aud/exp/iat/nonce, userinfo fallback) alongside existing SAML SP. **SCIM 2.0 PATCH** to real RFC 7644 §3.5.2 conformance (op verbs, `members[value eq "x"]` filtered paths, malformed→SCIM-400). Proven vs local mock IdP, zero egress, no bypass. |
| `e48222b` | Wave 2b | **Object-store abstraction** (local-fs default + opt-in S3/boto3 adapter, shared contract tests, S3-via-moto). **Honest `/health/deep`** (real DB/redis/worker-heartbeat/queue-depth, structured 503 on degrade, never fake-green). Worker heartbeat. **Backup/restore drill executed** (`outputs/ops-proof/restore-drill-*.txt`). |
| `0c47a49` | Wave 2c | **ASVS L2 self-assessment** (`outputs/security-asvs-*.md`). **Adversarial tenant-isolation** for newer surfaces (machine inventory, manifest, catalog, groundtruth, governance, libraries, RFQ) — **0 leaks found**, incl. IDOR probes. **bandit + pip-audit CI gates** — fixed 3 real bandit findings (jinja2 autoescape XSS, SHA1), bumped `authlib 1.3.2→1.7.2` clearing 8 CVEs. |
| `a159bb8` | Hardening | Per-IP **brute-force throttle on `POST /auth/login`** (was the one unthrottled auth route). |
| `bc93f41` | Wave 2d | **OpenTelemetry tracing** (opt-in, real OTel SDK, manual spans on the costed path, OTLP export wired, zero-overhead-when-off proven). Real 10-span trace captured (`outputs/ops-proof/otel-trace-*.txt`). **Load smoke** run in-container with real p50/p95/p99 (`outputs/ops-proof/load-smoke-*.txt`). |

Full combined verification on the integrated tree at each step: backend suite
**1439–1497 passed / 0 failed** (count grows as tests were added), Postgres-gated
sets green, route-auth invariant holds (154 routes), frontend tsc clean + 216 FE tests.

---

## 2. Two decisions waiting on you (I did NOT act on these)

### A. Promote `codex`→`prod`? (deploy-affecting — your trigger)
The prod/dev↔codex divergence is **resolved with data**: codex is canonical.
Content diff codex→prod is **+3,177 / −50,837** — going to prod would *delete* the
entire `frontend/src/lib/verify/*` library, connectors, SCIM, and migrations
0024–0035. The only prod-only content is an **older marketing/landing page set
codex deliberately redesigned**; nothing real is stranded. `prod`/`dev` are stale
07-04 snapshots (mig 0023) vs codex 07-08 (mig 0035).
**Recommendation:** open a reviewable PR codex→a prod-candidate branch (no
auto-deploy). I held off because (a) it's deploy-affecting and (b) house rule is
no PR without your explicit ask. Say the word and I'll prepare it.

### B. Which connector rung next? (your product call)
Each is buildable here as adapter + fixture-replay (honestly labeled; live-tenant
is the external gate). Priority depends on your target customer's systems:
- **Autodesk APS** (Rung B) — best demo value, free dev tier, CAD/BOM. *My default pick.*
- **SAP S/4HANA mock** (Rung C) — vs api.sap.com sandbox; best for Aramco/Exxon SAP shops.
- **Coupa/Ariba cXML** (Rung D) — PunchOut/procurement entry point.
- **Pause connectors** — harden core instead (OIDC/SCIM FE surfaces, cost-path perf).

---

## 3. Why codex is canonical (evidence)
`git merge-base(prod, codex)` = 95ad0c4 (07-01). Raw counts (176 prod-only vs 17
codex-only commits) are misleading — they're different SHAs for largely the same
work (codex is a rebased continuation). The **content** diff and **migration
superset** (codex has every prod migration 0001–0023 *plus* 0024–0035) prove codex
is the more-complete, newer line. All Wave 1–2 work sits on it.

---

## 4. Honest external gates (prepared, never faked)
Live OIDC/SCIM cert vs a real Okta/Entra/Ping **tenant**; live S3/MinIO + live
redis+arq worker health reading; a live OTel/APM collector (Honeycomb/Datadog);
production-scale k6 at real concurrency; live SAP/Windchill tenant; real customer
pilot data (accuracy validation); SOC 2 / independent pen-test. The in-container
standards-conformance and proofs are real; the live sign-offs are the gates.

## 5. Known infra note for future builders
`isolation: worktree` here seeds worktrees from a **stale ancestor** (`17acf61`,
pre-SCIM) instead of the intended tip. Every builder must verify its base first
and `git reset --hard <intended-sha>` if wrong. One builder this session reported
"all green" against that stale base (missing ~150 tests) — caught in review. The
Step-0 base-check instruction was added to later builder prompts and worked.

## 6. Throwaway test databases (port 5433, data dir /var/lib/postgresql/w1)
`cadverify`, `cadverify_identity`, `cadverify_ops`, `cadverify_security` — all UTF8
(required; SQL_ASCII breaks JSONB with H₂S/±/° unicode). Recreated per builder to
avoid collisions. Ephemeral — nothing here is production data.
