# Verify — Phase 0-A: Kill the Replicate image→mesh egress (honesty / zero-egress blocker)

**Verdict: CLOSED + PRODUCTION-WORTHY → merge to prod (after full-suite gate confirms).**
Branch `feat/p0-kill-egress` (commit 8ec1e0e). Closes arch audit F-ARCH-4 + the Aramco-research data-residency landmine; makes the vision's "zero-egress / CAD-as-IP" badge truthful (the #1 no-lying-stub rule).

## The finding (closed)
Image→mesh reconstruction DEFAULTED to `remote` → `RemoteTripoSR` → Replicate's hosted API, silently egressing customer imagery to a third-party cloud (local backend can't run — torch/tsr absent). ITAR/data-residency landmine + a lie against any zero-egress claim.

## Evidence (verified by orchestrator)
- **Default is local:** `DEFAULT_RECONSTRUCTION_BACKEND = "local"` with the comment "Never default-on to third-party egress." No customer data leaves the deployment without explicit opt-in.
- **Remote requires explicit, warned opt-in:** `RECONSTRUCTION_BACKEND=remote` or `RECONSTRUCTION_ALLOW_REMOTE_EGRESS=1`; `get_reconstruction_engine()` logs a loud `DATA EGRESS ACKNOWLEDGED …` warning on any effective-remote path. Never default-on.
- **Announced-unavailable (announces the stub — #1 rule):** no local model + no opt-in → `ReconstructionUnavailableError` (`code = "RECONSTRUCTION_UNAVAILABLE"`); `POST /api/v1/reconstruct` gates on `check_reconstruction_availability()` → **HTTP 501** structured, **no job created, nothing egressed** (test asserts `create_reconstruction_job` never called). Not a silent egress, not a confusing 500.
- **Honest `/health`:** adds a non-gating `reconstruction: {available, backend, egress}` block sourced from `check_reconstruction_availability()`; the except-fallback is honest (`available: False`). (Unavailable in a zero-egress deployment is a valid, intended state — correctly not a health gate.)
- **Tests:** targeted `test_reconstruction.py` + `test_reconstruct_api.py` → **41 passed** (incl. default-local, unavailable-not-egress, explicit-remote opt-in, egress-ack logging, `none` disabled). Full-suite gate: 603 passed / 0 failed (builder) — orchestrator re-run pending.

## Notes
- Reconstruction feature code (validation, blob storage, scoring, job, auto-feed) left intact — this was the default + honesty, not a feature deletion.
- The redis-lie in `/health` (arch F-ARCH-2) is a SEPARATE async-tier item — not in scope here; this only added the honest reconstruction block.

Pairs with P0-B: the frontend "zero-egress / LOCAL" badge is now truthful for the cost/DFM path (and reconstruction honestly announces unavailability).
