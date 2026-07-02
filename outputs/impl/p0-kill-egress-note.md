# P0 — Kill silent egress in image→mesh reconstruction (HONESTY blocker)

**Branch:** `feat/p0-kill-egress` (off `dev`)
**Finding closed:** F-ARCH-4 — reconstruction DEFAULTED to the `remote` backend →
`RemoteTripoSR` → Replicate's hosted API, which egresses customer CAD-derived
imagery to a third-party cloud. With torch/tsr absent (as in this deployment), a
reconstruction request either **silently egressed customer imagery** or 500'd —
an ITAR / data-residency landmine and a lie against any "zero-egress" claim.

**Goal:** make it HONEST — announce, never silently egress. No customer data
leaves the deployment without explicit, informed operator opt-in.

---

## The new default (zero-egress by default)

`RECONSTRUCTION_BACKEND` now defaults to **`local`** (was `remote`).
Constant: `DEFAULT_RECONSTRUCTION_BACKEND = "local"` in
`backend/src/services/reconstruction_service.py`.

Effective-backend resolution (`resolve_reconstruction_backend()`):

| Config | Local model installed? | Effective backend | Egress off-box? |
|---|---|---|---|
| default (`local`) | yes (torch+tsr) | `local` | **no** |
| default (`local`) | no | **unavailable** → `ReconstructionUnavailableError` | **no** |
| default (`local`) + `RECONSTRUCTION_ALLOW_REMOTE_EGRESS=1` | no | `remote` (opt-in) | yes (warned) |
| `RECONSTRUCTION_BACKEND=remote` | n/a | `remote` (explicit opt-in) | yes (warned) |
| `RECONSTRUCTION_BACKEND=none` | n/a | disabled → unavailable | **no** |

So **no path egresses customer data unless the operator explicitly opted in.**

## The opt-in flag + its warning

Remote (Replicate) egress requires an explicit, informed choice — one of:
- `RECONSTRUCTION_BACKEND=remote`, or
- `RECONSTRUCTION_ALLOW_REMOTE_EGRESS=1` (truthy: `1/true/yes/on`), which permits
  remote **only as a fallback** when the default `local` backend has no model.

Never default-on. Every effective-remote path logs a loud acknowledgment from
`get_reconstruction_engine()`:

```
WARNING DATA EGRESS ACKNOWLEDGED: reconstruction backend=remote sends
customer-derived imagery to a third-party cloud (Replicate). This is an explicit,
opted-in configuration (RECONSTRUCTION_BACKEND=remote or
RECONSTRUCTION_ALLOW_REMOTE_EGRESS). Verify data-residency / ITAR compliance.
```

## Announced-unavailable behavior (honest, not a silent 500)

When no local model is installed AND remote egress is not opted in:

- Service layer raises `ReconstructionUnavailableError` (has stable
  `.code = "RECONSTRUCTION_UNAVAILABLE"`).
- `POST /api/v1/reconstruct` checks `check_reconstruction_availability()` up front
  (after the cheap 1–4 image-count validation) and returns **HTTP 501** with the
  stable structured body:
  ```json
  {"code": "RECONSTRUCTION_UNAVAILABLE",
   "message": "Reconstruction is not available in this deployment: no local model
   (torch/tsr not installed) and remote egress is not enabled. To enable remote
   reconstruction via Replicate ... set RECONSTRUCTION_ALLOW_REMOTE_EGRESS=1 ...",
   "doc_url": "https://docs.cadverify.com/errors/RECONSTRUCTION_UNAVAILABLE"}
  ```
  No job is created and nothing is egressed — the request is refused before any
  work. (`501 NOT_IMPLEMENTED` / `503` codes already exist in
  `src/api/errors.py`; the stable `RECONSTRUCTION_UNAVAILABLE` code is surfaced via
  the existing dict-detail passthrough in `structured_http_error_handler`.)
- The arq job runner (`run_reconstruction_job`) defensively annotates a failed
  job's `result_json` with `code: "RECONSTRUCTION_UNAVAILABLE"` if the factory
  raises (should not happen given the endpoint gate, but honest either way).

## Honest capability in `/health`

`GET /health` now includes an honest, non-gating reconstruction block (an
unavailable reconstructor in a zero-egress deployment is a valid, intended state,
not a health failure):

```json
"reconstruction": {"available": false, "backend": "none", "egress": false}
```

The arq worker startup (`src/jobs/worker.py`) now preloads the TripoSR model
**only** when the effective backend is a locally-installed `local` model — it no
longer tries to load a missing model (which would crash startup) and never
preloads/egresses via remote at boot.

---

## Files changed

- `backend/src/services/reconstruction_service.py` — new default `local`;
  `ReconstructionUnavailableError`; helpers `configured_backend()`,
  `remote_egress_allowed()`, `local_backend_available()`,
  `resolve_reconstruction_backend()`, `check_reconstruction_availability()`;
  `get_reconstruction_engine()` enforces zero-egress + logs egress warning.
- `backend/src/api/reconstruct_router.py` — availability gate → 501
  `RECONSTRUCTION_UNAVAILABLE` before creating a job.
- `backend/src/api/health.py` — honest `reconstruction` capability block.
- `backend/src/jobs/worker.py` — preload local model only when actually available.
- `backend/src/jobs/reconstruction_tasks.py` — defensive stable-code annotation
  on failure.

## Tests changed / added (all reflect the honest default)

- `backend/tests/test_reconstruct_api.py`
  - updated `test_reconstruct_endpoint_202` — happy path now patches availability.
  - **new** `test_reconstruct_announces_unavailable_no_local_no_optin` — no local
    + no opt-in → **501 `RECONSTRUCTION_UNAVAILABLE`**, and asserts
    `create_reconstruction_job` was **never called** (no egress, no job).
  - **new** `test_reconstruct_remote_opt_in_wired` — `RECONSTRUCTION_BACKEND=remote`
    → 202 path still wired.
- `backend/tests/test_reconstruction.py` — **new** `TestZeroEgressBackendResolution`
  (7 tests): default is local; no-local+no-optin → unavailable, egress=False,
  factory refuses (never returns a remote engine); local-available → local/no-egress;
  explicit `remote` → egress opt-in; `ALLOW_REMOTE_EGRESS=1` fallback; `none` disabled;
  egress factory logs the acknowledgment.

## Test result

Full backend suite: **603 passed, 7 skipped, 0 failed** in ~268s
(baseline 594 passed / 0 failed / 7 skipped; +9 new tests = 603). Green.

## Confirmation

By default (no `RECONSTRUCTION_BACKEND`, no `RECONSTRUCTION_ALLOW_REMOTE_EGRESS`)
and with no local model installed, **no customer data egresses**: the endpoint
returns an honest announced-unavailable 501 and the engine factory refuses rather
than handing back a Replicate-egressing engine. Remote egress is reachable only
via explicit, warned operator opt-in. The reconstruction feature code (validation,
blob storage, scoring, job, auto-feed) is intact.
