# RESUME — Autonomous Orchestration Loop (live)

**Updated 2026-07-04 ~20:35 ET by Fable.** Directive: loop until CadVerify is a **production-working platform** (pilot bar first, then GA). Fable orchestrates (research+plan+gate); lesser models execute. **PAUSED on account session limit — resets 9pm ET. Do not spawn sub-agents until reset (they die instantly).**

## North star + the map
Goal doc: `outputs/production-readiness.md` (ranked blockers, pilot vs GA, shortest pilot path). Gaps: `outputs/product-gaps.md` (48 items + queue). Thesis: `PLATFORM-DNA.md`. Deploy: `outputs/deploy-runbook.md`.
**Strategic key:** B1 (validated accuracy) gates GA but can ONLY be closed by running a pilot — the pilot manufactures the evidence GA needs. So: get to the pilot bar cheaply, let the pilot generate ground truth.

## FOUNDER DECISION (2026-07-04)
First partner = **Aramco-scale: millions of parts, EVERY file + part type.** → **B4 STEP ingestion is now the #1 HARD PILOT blocker** (needs OpenCascade/OCP on the deploy target — known-hard; STL-only = empty pilot). "Millions of parts" = the pilot IS triage-at-scale (Phase D done; scale/perf now matters). "Every type" → weldments/multi-body/sheet-metal + GD&T matter, but the honest move is triage BUCKETS what it can't yet verify rather than needing 100% day one.
**Still-open founder scope calls:** §38 execution bridge (make-outside/acquire → RFQ?), §43 which verticals the environment door learns next, §44 weldments/sheet-metal in pilot or GA.

## Current prod/dev
- `dev == prod == 7b330d8` (+ the gaps/resume commit about to land). prod promoted this session; keep pushing prod after each gate.
- Suite: **1227 passed / 24 env-only (CADVERIFY_PARTS_DIR) / 44 skipped.** GitHub current.
- **A FRESH backend is running on :8000 at dev HEAD** (PID ~44399, version:"dev") — left up by the B2 proof; the app is actually usable. The old stale PID 31026 was killed.

## Landed this session (all gated, adversarially verified)
Cloud verification-thesis branch (308b919) · **Phase C** makeability→live cost path (c600b09) · **Phase D** triage-at-scale + capability-investment ranking (4d39fec) · **Verify product UI** wired to real engine, behind NEXT_PUBLIC_VERIFY_UI (a6ce85b) · production-readiness assessment + deploy runbook + gaps register.

## ✅ B2 PROVEN LIVE (highest-leverage pilot item)
Backend core loop demonstrated on a fresh backend at dev HEAD: signup→validate→validate/cost→Phase C verification block (makeable_in_house on a real declared Haas VF-2)→sour-service env round-trip (NACE MR0175 exclusions, verdict→makeable_outsource_only)→persist→list. **ALL asserts PASS, 0 FAIL.** Transcript: `outputs/pilot-proof/backend-loop.md`.
**Still open from B2:** (a) frontend browser screenshot of /verify (agent died before it), (b) run-path patch — add NEXT_PUBLIC_VERIFY_UI=1 + start the arq worker in `scripts/run-local-app.sh` (no feat/pilot-run-path branch was created).

## WIP PRESERVED on branches (unverified — died on session limit)
- **feat/org-membership @3a9575d** — org lifecycle/invites/deactivation/audit-events source (WIP 4742b49) + test_org_membership.py (UNRUN). NOT merged. Needs: run tests, finish gaps, then the 3-lens security verify (invite-abuse / cross-tenant / auth-regression). This is pilot blocker **B3**.
- **feat/cost-unit-safety @8bfe484** — units.py + estimate.py changes, INCOMPLETE (no tests). Pilot blocker **B5** (inch STL mis-costs ~16,000×). Needs: finish the fix (explicit units param + out-of-range warning), byte-identity for mm default, tests, verify.

## RESUME PLAN (at 9pm ET reset — do in order)
1. **B4 STEP ingestion** — NEW top priority per founder. Research: get OCP/cadquery buildable on the deploy target (Docker image work; `step_parser.py:56` raises without cadquery). This is the pilot-enabling engine task. Opus builder, likely a spike first (can the image even carry OCP?).
2. **Finish B3 org-membership** — resume the finish+verify workflow (branch has source+tests; run + gate). Security-weighted verify.
3. **Finish B5 units safety** — complete + verify.
4. **Finish B2** — frontend /verify screenshot + the run-path patch (flag + worker); commit feat/pilot-run-path.
5. Then GA: wire the ALREADY-BUILT backends into the stubbed UI surfaces (catalog/compare/triage/portfolio/capability — they exist, just not called; cheap, §B8) → programs-as-object (§36) → verdict process-specs (§33/B10) + shop certs (§34/B11) → the rest by impact.
6. Deploy fixes (§45 broken standalone frontend image, §46 dev never green in CI).

## Gating protocol (unchanged)
Feature branch off dev → opus builder (worktree under `<scratchpad>/wt/`) → 3+ adversarial verifiers (distinct lenses) → any FAIL routes back with the exact defect → merge --no-ff → full suite (accept ONLY the 24 env fails) → push origin dev + prod. No fabricated numbers; validated only from measured residuals.

## Recurring gotchas
Sub-agents died twice on transient API drop + once on session limit — commit WIP frequently, salvage worktrees before relaunch. Frontend package.json "test" line conflicts on merge → UNION the --test list, validate JSON. Local venv py3.9 vs deploy 3.12 → keep `from __future__ import annotations`. Turbopack panics on symlinked node_modules in worktrees → build --webpack there, real Turbopack in main tree.
