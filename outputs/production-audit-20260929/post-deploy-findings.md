# Additional findings during the approved Render rollout

Observed 2026-09-29. These supplement issues 001–015 in the original inventory.

## 016 — Render automatic deployment did not start

- Severity: medium operational issue; manual releases work.
- Reproduction: all three service settings show `On Commit` on `zandemha2025/cadverify:main`. Merge #106 as `09555c1`. No automatic build appeared; manually deploying latest commit started and completed all three builds.
- Expected: committing to the configured branch starts a deployment.
- Actual: manual intervention was needed. Each build warned that Render lacked repository access, then successfully cloned the public repository.
- Suspected cause: the existing GitHub integration no longer has the repository access needed for webhook-based deployment. The exact integration state has not been inspected or changed.
- Status: this rollout completed using existing manual deploy controls. Permanent automatic-deploy repair remains open.
- Proposed fix: reconnect the existing Render GitHub integration to the intended CadVerify repository, review its requested access, then verify one subsequent approved release triggers automatically. No new account or access grant was created during this rollout.

## 017 — Main-only backend image scan reports five HIGH findings

- Severity: high according to Trivy; exploitability in this deployment is not established.
- Evidence: [main container job](https://github.com/zandemha2025/cadverify/actions/runs/36622136184/job/109594762580), local `main-container-failure.log`, scan at 20:08 UTC. Frontend image scan passed. Backend image scan failed; subsequent SBOM generation was skipped.
- Reproduction: build the backend image from merge `09555c1`, then run the existing HIGH/CRITICAL Trivy gate with the current database. It reports five package findings, three distinct CVEs, zero CRITICAL findings.
- Expected: the image gate passes before the release is described as fully green.
- Actual: the PR pipeline skipped image scans by design; all nine PR jobs passed, but the push-to-main image scan detected the findings after deployment.

| CVE | Affected packages in the scanned image | Installed version | Current upstream/distribution evidence |
| --- | --- | --- | --- |
| CVE-2026-93990 | libexpat1 | 2.8.3-1~deb13u1 | Debian trixie still lists this version as vulnerable. A fix exists upstream in Expat 2.8.5 and in Debian testing/unstable; it is not listed as a stable trixie package fix. [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-93990). |
| CVE-2026-88806 | libx11-6, libx11-data, libx11-xcb1 | 2:1.8.12-1 | Requires a malicious X server. Debian lists trixie and unstable as unfixed, with an upstream merge request. [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-88806). |
| CVE-2026-88807 | libxrender1 | 1:0.9.12-1 | Requires a malicious X server. Debian lists trixie and unstable as unfixed, with an upstream merge request. [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-88807). |

- Scope: #106 did not change `backend/Dockerfile`, `backend/requirements-prod.lock`, or `.trivyignore`; their diff from the previous deployed source is empty. This establishes that the audit fixes did not introduce a new dependency configuration. The previous running image has not been rescanned, so its precise finding count is not claimed.
- Runtime context: these X libraries are required by the packaged gmsh wheel for real STEP ingestion. Application gmsh calls are headless; no `gmsh.fltk` use was found. This is supporting context, not proof of non-exploitability. Removing the libraries would break required STEP support.
- Status: **open; security gate remains failing**. No CVE waiver, scanner bypass, package removal, speculative runtime patch, or distribution switch was applied.
- Proposed fix: use supported patched stable packages when available, or prepare and verify an explicit upstream backport in the actual production image. Any temporary risk acceptance must be a separate reviewed decision. Re-run the image scan and real CAD regression suite before marking this finding resolved.

The functional production canary passed on the deployed release. That result does not make this security gate green. Legacy Fly recovery/account migration and Vercel retirement remain separate unresolved items in `release-handoff.md`.


## 018 — Live connector choices route through the offline CSV parser

- Severity: high correctness issue.
- first divergence: step 2, expected selecting SAP S/4HANA or Windchill to show the vendor connection flow, state was an unchanged CSV-only form.
- Reproduced for both choices in the Render browser. Screenshot: `018-live-connector-csv.png`.
- The shared backend CSV service accepts these vendor connector IDs without checking their mode, and writes a successful run tagged `sandbox_api` / `sandbox` for an ordinary local CSV. Four regression cases (both providers, dry-run and import) fail before the fix.
- The adapter credential probe only checks configuration presence; it does not contact a vendor. There is no vendor HTTP read/run path behind these visible choices. Prior fixture replay and green CI do not prove a live vendor integration.
- Required work: prevent false vendor evidence; implement and exercise actual authenticated read-only vendor runs against user-authorized test tenants. Do not mark integrations complete on the strength of a guard or a disabled button.
- Status: false API evidence is blocked by backend guard `ef72c98`; the UI separates unavailable vendor runs in `958442c`. Actual vendor transport and tenant proof remain open. Provider test tenant details requested; no credentials or permissions changed.

## 019 — CSV validation hides the reason and gives success feedback for partial runs

- Severity: medium usability/correctness issue.
- first divergence: step 3, expected the dry-run result to identify the invalid CSV row, state was `partial`, `1/2 valid`, `1 flagged` with no reason or row details.
- Live reproduction: SAP manifest CSV, Dry-run, `integration-audit.csv` containing one valid part and one blank part identifier. Screenshot: `019-csv-error-hidden.png`.
- Source confirms every HTTP-success run emits a success toast regardless of its failed/partial status. The response already contains line/reason details and import/update/skipped counts, but the UI never renders them. The native file input also retains the old filename after file state is cleared.
- Required fix: show row errors and import counts, distinguish partial/failed results, make retry/file selection consistent, and provide the existing CSV template.
- Status: fixed locally in `958442c`. Browser regression passes for row errors, corrected-file retry, template URL and persistence; frontend typecheck/lint/build pass. Not deployed.


## 020 — Tessellation density changes manufacturing resolution warnings

- Severity: high result-accuracy issue.
- first divergence: step 3, expected a 20 × 15 × 10 mm STEP block with a 6 mm through-hole to have no sub-0.4 mm features, state was `277962 edges (100.0%) below 0.4mm resolution` with a smallest feature of 0.087 mm.
- Reproduced by a fresh native browser upload on Render, merge 09555c1. Dimensions/volume and the 3 mm hole radius agree with the source solid; the alleged tiny features are export-triangle edges. Evidence: `live-step-accuracy.txt`, `020-mesh-accuracy-live.png`.
- Independent regression: refining the triangles of the SAME rotated 10 mm cube changes the old result from pass to SMALL_FEATURES; both 64- and 256-segment 6 mm bores also falsely trigger. Four cases failed before the fix, four controls passed.
- Fix `6959429`: shared measurement of geometric boundary spans/rim widths, reused by both current and legacy analyzers, rather than raw triangle edges. Keep real 0.39 mm failures and 0.41 mm passes at coarse/refined resolutions.
- Status: fixed locally. Eight tessellation/threshold regressions, full backend suite (2,322 passed, three documented skips), trap gate and real STEP browser result pass. Exact volume error is 0.002581%; boundary measurement gives a 5.9995 mm bore. Not deployed. Two trap expectations were corrected using independently known 0.70 mm neck / 2 mm bore dimensions, replacing false-positive expectations with required absence of SMALL_FEATURES. The existing unit-inference known gap remains; freeform feature coverage is not claimed.

## 021 — Smooth cylindrical walls counted as sharp casting corners

- Severity: high result-accuracy issue.
- first divergence: step 3, expected the smooth through-hole to have no sharp internal corners, state was 24,510 sharp internal corners requiring fillets.
- The shared casting check treats normal-to-normal angles below 120° as sharp. Trimesh defines zero as coplanar/smooth; the check therefore includes finely tessellated curved walls. A five-edge floor also misses a real coarse-mesh L-shaped corner.
- Fix: convert the intended interior-angle threshold to a >60° normal turn, report any actual sharp concave edge, and describe counts as mesh edges. Commit `550f15c`.
- Verification: smooth bores at 64/256 segments no longer trigger; a real L-shaped reentrant corner is caught at both coarse/refined tessellations. 16 corner/feature tests pass. Production verification still required.

## 022 — STEP preview missing in the Analyze DFM / cost workspace

- Severity: medium functional issue.
- Fresh live STEP upload completes DFM/cost but the 3D panel says `STEP preview requires backend conversion` instead of rendering the model.
- The Verify workspace preview was previously tested separately. This is a different visible workflow, not covered by that proof.
- Evidence: `live-step-accuracy.txt`. Local fix reuses the authenticated GLB converter in the shared CadViewer, adds retry/error recovery, and requests the same bounded analysis mesh for inspection. An exact triangle fingerprint prevents a cached analysis from painting a different tessellation. Tests prove face order before/after decimation and inch scaling; real STEP rendering is browser-proven. Final fingerprint-aware real STEP upload and finding-selection browser checks pass (`step-preview-regression.json`). Geometry/face-order fingerprint tests reject reordered triangles. All 18 directly affected preview/analysis-service tests pass after the fingerprint addition; the final full backend run and exact-head CI are tracked separately. Not deployed.

## Deployment capability gaps confirmed during the full feature audit

- Organization settings explicitly report SAML and OIDC `Not enabled in this deployment`, HTTP 404. Real company sign-in is not currently available on Render.
- Password login has no email-link option visible. A test inbox and authorized identity-provider / SAP / Windchill sandbox details have been requested.
- External vendor transport is absent behind the current adapter contracts, not merely untested. Live integration completion remains required.


## 023 — Old persisted analyses survive corrected engine semantics

- Severity: high accuracy/release issue.
- The analysis cache keys by package version, which was still `0.3.0` despite changed geometry checks. The same upload could reuse the original false warnings after deployment.
- Fix: bump the analysis version (`9eafd45`, followed by the preview fingerprint contract version), preserving historical records while recomputing new uploads. Eleven analysis-service tests pass, including cache-version behavior.
- Status: fixed locally, not deployed.

## 024 — Different unit interpretations link to the same saved cost decision

- Severity: high result-integrity issue.
- first divergence: a second request costs identical file bytes as inches after millimetres; live geometry/pricing changes but the saved record identifier stays the same.
- The shared cost parameter fingerprint omitted source units and engine version.
- Fix `ee052bd`: include both in the common fingerprint used by synchronous and batch cost persistence; pass declared units from the cost route.
- Verification: API regression failed before the fix and passes after it. Different units and engine revisions produce distinct saved pointers; identical repeated requests reuse the correct pointer. 45 cost-persistence/preview tests pass. Not deployed.

## 025 — Visible CAD-retention claims contradict authenticated storage

- Severity: high trust/copy accuracy issue.
- Analyze upload and the app header say CAD is parsed and discarded. Verify says the engine keeps the decision, never CAD; the cost view says it never leaves this machine.
- Authenticated analysis explicitly persists exact source CAD and a canonical STL derivative through `source_artifact_service`; authenticated source retrieval was already proven during the release audit. Render processing is server-side.
- Fix `61dbeea`: correct Analyze, PartDoor, Verify, cost results, the Inspector, app header and Method copy. The route-based LOCAL badge no longer implies browser-local execution or deletion. The Security page already distinguishes cloud retention from local deployments. Source storage and access controls are unchanged. Local browser notice, 484 frontend tests, typecheck, changed-file lint and production build pass. Not deployed; broader public-claim audit remains open.
- Follow-up sweep: the native workspace Home still said “parsed in-process · discarded”; the shared pipeline and public homepage made similar claims. These now state that source CAD is retained with saved records. The unconditional “local preview first” promise is corrected because STEP/IGES previews use server conversion. Security's local-deployment card also incorrectly implied that self-hosting deleted CAD; it now explains that authenticated self-hosted API deployments retain source files too. No storage behavior changed. The targeted source-copy sweep now finds no remaining discard/never-store claims, and all 484 frontend tests, typecheck, changed-file lint and production build pass again.

## 026 — Tiny tessellated patches reported as additional flat features

- Severity: medium accuracy issue, separate from the corrected small-feature warning.
- The known STEP block has six planar exterior faces and one cylindrical bore. Its fresh local analysis reports eleven flat features; five are only 0.2–0.3 mm² patches on the tessellated bore. The live run also showed extra flat patches.
- Fix `ac9eaa3`: the shared feature orchestrator excludes recognized cylindrical faces from the flat-feature output. Coarse/fine annuli previously reported 130/514 flats; both now report only two planar caps, while a real hexagonal prism retains all eight planes. Thirty-three affected tests and the trap gate pass. The actual STEP source and native browser upload now report exactly six planes and one cylindrical hole (`flat-feature-step-proof.json`, `026-flat-features-fixed-local.png`). Engine version 0.3.3 invalidates older cached classifications. Not deployed.

## 027 — Saved credentials were mistaken for a tested vendor connection

first divergence: step 1, expected the credential probe to perform an authenticated vendor read, state was a synchronous configuration-presence check with no HTTP request.

- Severity: high evidence-integrity gap. Neither vendor choice had user-facing credential controls, and the API probe could report `configured=true` for an unreachable placeholder endpoint.
- Fix: distinguish `configured` from `connected`; perform a bounded authenticated product read and return only its count, capability and check time. SAP uses the documented [Product Master OData API](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/2628c891a3a04f05a293c7ca5d23e4b6/1e60f14bdc224c2c975c8fa8bcfd7f3f.html); Windchill uses [ProdMgmt/Parts](https://support.ptc.com/help/windchill_rest_services/r2.7/en/windchill_rest_services/examples_WCCG_RESTAPIsSupportedQueryOptions.html). The public URL is resolved once and its vetted IP is pinned for the connection with the original Host/SNI and certificate verification. Redirects are refused. The response limit is 1 MB and the whole probe deadline is 25 seconds. OAuth client-credential token requests use the same egress guard. No vendor records are returned or persisted.
- Organization admins can save encrypted credentials, test access and revoke profiles in Integrations. The four supported forms are bearer, Basic, OAuth `client_secret_basic` and an API-key header. Revoked profiles do not decrypt or make requests. Failed reads surface recovery instructions; saving alone never claims a successful connection. API imports and BOM reads remain explicitly unavailable.
- Regression: the new transport test first failed 17 cases against the old synchronous probe. Updated focused tests pass, covering vendor OData shapes, authentication, public-IP pinning, private/mixed DNS, redirects, failed auth, oversized/invalid responses and redaction. Browser checks pass for both vendor choices: save, cleared secret, blocked private endpoint, failure/retry, reload, revoke and persisted revocation. See `connector-probe-regression.json` and `027-connector-probe-fixed-local.png`.
- Boundary: these are local HTTP-contract and native-browser proofs, not a successful real SAP or PTC tenant connection. Authorized tenant access, BOM transport, imports/reconciliation and production deployment remain open.

## 028 — Missing encryption configuration returned a generic save error

first divergence: step 1, expected a saved credential or actionable storage-configuration error, state was HTTP 500 after `CONNECTOR_SECRET_KEY` was absent in the production-like local environment.

- Severity: medium usability/configuration issue. The encryption boundary correctly refused to use the development key, but its internal error became a generic browser failure.
- Fix: return HTTP 503 with a clear operator-configuration message while preserving fail-closed encryption. The behavior-level test failed against the old RuntimeError and passes after the shared encryption helper fix. A generated key was stored only in the ignored, mode-0600 local test environment; no production secrets or settings were changed.
- Local browser save/test/revoke succeeds with encrypted storage configured. Production key provisioning must be verified before this capability is released.

## Follow-up CI checkpoint

The exact-head run for `bf4e509` completed with eight passing jobs and one browser failure. All 54 human-journey steps passed; its copy sweep found the old “CadVerify” product name in the newly corrected Verify retention notice. The notice now uses neutral “Source CAD is retained…” wording without changing its truthful retention meaning or weakening the copy gate. This correction and findings 027/028 require a fresh exact-head CI run before release.

Local validation after the connector changes: **2,349 backend tests passed, three documented environment/corpus skips**, using the disposable Postgres/Redis and an isolated temporary directory. Frontend: **484 tests passed**, typecheck, changed-file lint and production build passed. Changed backend files have zero pyright errors; the full backend baseline check passes (220 errors against the existing 228 baseline). Bandit reports zero findings in changed services. The nine native-browser credential checks above passed; every dummy profile created during this check was revoked. No production deployment or real vendor-tenant success is included in these results.

## 029 — Cost PDF mislabels the cost split and loses continuation headings

first divergence: step 2, expected the downloaded real-STEP report to explain its cost columns accurately, state was “Unit cost = fixed (amortized) + variable” beside $3.80 unit / $0 fixed / $3.48 variable for MJF at quantity 50.

- Severity: medium report accuracy/readability issue. The stored split is one-time tooling/NRE plus a long-run per-unit cost with full-lot setup allocation; batch rounding and minimums can make the actual quantity-specific price differ. Continuation pages also lacked table headings.
- Fix: label the existing columns “One-time $” and “Long-run $/unit”, explain their meaning, and use native HTML table headers throughout the shared cost report. Correct the stale dataclass comments too. No calculation or historical result is changed.
- Verification: a rendered-PDF regression first failed against the misleading copy and now verifies repeated estimate and line-item headings on multiple pages. Native browser downloads of the real STEP decision produced JSON, CSV and PDF; all 16 estimate rows match, line items reconcile within half a cent, and approved governance plus multiline Unicode notes survive all formats. Rendered PDF pages were visually inspected. See `export-regression.json` and `029-cost-pdf-fixed-local.png`. Local only.

## 030 — RFQ re-download mixes historical JSON with a live decision PDF

first divergence: step 5, expected re-downloading an existing approved RFQ after editing its source to retain the original evidence throughout, state was approved snapshot JSON/CSV beside an unreviewed PDF containing the later note.

- Severity: high evidence-integrity issue. Package items are snapshots, but `build_zip` rendered its PDF from the current database decision. Its content-addressed cache correctly regenerated the wrong inputs; the cache was not the cause.
- Fix: adapt saved package metadata/results into the existing PDF renderer for both cache warming and ZIP download. New snapshots also retain the source hash. A source row is no longer required to render historical evidence; raw-CAD retrieval keeps its same-org boundary. Old snapshots without a source hash leave it absent instead of borrowing current data.
- Verification: the existing ZIP service test first failed because the PDF received the live unreviewed decision. It now checks saved approval, note, timestamp, results, no live-row mutation, and export after source removal. Native Chrome reproduced the mismatch, then re-downloaded the same RFQ after the fix: its PDF again carries the original approval/note and excludes the later edit. No supplier was contacted. See `export-regression.json` and `030-rfq-snapshot-fixed-local.png`.
- Validation for 029/030: 54 related API/service/PDF tests passed; full backend type baseline remains 220 against 228 allowed; changed-service Bandit medium/high gate passed (two preexisting low-level assert findings remain in PDF cache guards). New code is not deployed; exact-head CI must run after push.
