# Additional findings during the approved Render rollout

Observed 2026-09-29. These supplement issues 001–015 in the original inventory.

## 016 — Render automatic deployment did not start

- Severity: medium operational issue; manual releases work.
- Reproduction: all three service settings show `On Commit` on `zandemha2025/cadverify:main`. Merge #106 as `09555c1`. No automatic build appeared; manually deploying latest commit started and completed all three builds.
- Expected: committing to the configured branch starts a deployment.
- Actual: manual intervention was needed. Each build warned that Render lacked repository access, then successfully cloned the public repository.
- Provider inspection on 2026-09-30: the authenticated Render account's Git Deployment Credentials list is empty. The API service still targets this repository's `main` branch with Auto-Deploy set to `On Commit`. This confirms a missing deployment credential; successful webhook delivery remains to be tested after reconnection.
- Status: this rollout completed using existing manual deploy controls. Permanent automatic-deploy repair remains open.
- Proposed fix: connect Render's GitHub deployment integration to only `zandemha2025/cadverify`, then verify one subsequent approved release triggers automatically. The browser confirmation policy requires approval for this new persistent repository-access grant; that specific approval is pending. No provider was selected, access granted or deployment triggered. PR #107 requires separate deployment approval. The account-settings screenshot is retained privately, outside Git.

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

## 031 — DFM PDF does not explain why a passing part lists process errors

first divergence: step 2, expected the downloaded DFM report to distinguish its recommended-route verdict from other candidates, state was overall PASS followed immediately by six errors under a generic Issue Summary.

- Severity: low clarity issue. The findings were individually process-tagged and accurate to the saved record, but the summary's scope was unstated. The browser already separates recommended-route issues from alternative-process issues.
- Fix: explicitly state that the report includes universal checks and every evaluated process, and that each process-specific finding applies to its named route. Bump the PDF layout cache version to v3 so old PDFs refresh. No findings or verdicts are changed or hidden.
- Verification: PDF text regression failed before the clarification and passes after it. A fresh native download of the saved real STEP contains the explanation, PASS/FDM verdict, 22 candidate findings (6 errors / 11 warnings / 5 notes), 20×15×10 mm dimensions and 2717.3 mm³ volume. All seven rendered pages were inspected. Nine cost/DFM PDF tests pass after this follow-up. See `export-regression.json` and `031-dfm-pdf-scope-fixed-local.png`. Local only; the independent correctness of every manufacturing heuristic and citation remains open.

## 032 — Batch form permits concurrency values the API rejects

first divergence: step 2, expected the advertised concurrency range to start a real ZIP batch, state was a retained upload with “concurrency_limit must be between 1 and 12” after the form allowed 13 (its maximum was 100).

- Severity: medium usability issue. API/service/database boundaries already correctly enforce 1–12; the browser input and clamp advertised up to 100.
- Fix: use 12 for the existing input maximum and clamp, and show the supported range in the existing field hint. No backend limit is changed.
- Regression: the runnable CUA boundary check failed against max=100, then passed after the production rebuild; values 13/-1 clamp to 12/1 and valid 2 remains. All 484 frontend tests, typecheck, changed-file lint and production build pass.
- Real native-browser/worker proof: a mixed ZIP completed two valid CAD files, failed the malformed STL with a useful message, and explicitly skipped an unsupported-extension sentinel. Its downloaded CSV matches all four rows. A corrected ZIP plus CSV manifest completed all three files with the requested priorities/processes; saved cube/block dimensions and 1 cm³ volumes match independent input geometry. Cancelling a 20-file STEP batch retained three completed results and skipped 17 queued files; the terminal state survived reload and the worker queue drained. See `batch-regression.json` and `032-batch-corrected-result-local.png`.
- Boundary: local actual CAD/worker proof, not production. The `.sldprt` sentinel proves extension rejection only, not parsing or conversion of a real SolidWorks file. Real storage/webhook and production checks remain open.

## 033 — The STL unit selector double-scales STEP/IGES geometry

first divergence: step 2, expected a real 20×15×10 mm STEP to retain its embedded units with the source selector set to inches, state was 508×381×254 mm and 44,529 cm³, with false machine-envelope failures and changed process routing.

- Severity: high measurement/cost accuracy issue. STEP/IGES parsing already normalizes embedded units into mm; analysis, should-cost and preview then applied the STL-only ×25.4 conversion a second time.
- Fix: one shared file-aware unit policy feeds all three entry points and their cache/persistence identity. Only STL uses the explicit declaration. Correct the form hint/API descriptions and bump engine version to 0.3.4 so new uploads cannot reuse old scaled results. Historical evidence remains intact.
- Regression: real uppercase STP requests failed across analysis, cost and decoded GLB preview before the fix, then returned 20×15×10 mm. A real gmsh-generated IGES cube uploaded as `.IGS` with inches selected retains its embedded 20×20×20 mm dimensions. Existing STL mm/inch scaling and persistence checks still pass. All 88 related backend checks pass, as do 484 frontend tests, typecheck, changed-file lint and build. Pyright stays 220 against 228 allowed; Bandit has no medium/high findings (two preexisting low findings).
- Native Chrome repeated the exact source/selector combination: corrected 20×15×10 mm, 2.7 cm³, successful rendered preview and restored small-part routing. See `unit-aware-regression.json` and `033-step-units-fixed-local.png`. Not deployed; unitless-STL inference and calibrated price accuracy remain separate open gates.

## 034 — Design Studio mobile CI checks before preview readiness

first divergence: step 15, expected to assess the generated design after its asynchronous preview loaded, state was an immediate canvas/fallback count assertion while the actual preview request was still loading.

- Severity: test reliability issue. Run 36644799499 passed eight jobs, all 54 human steps, 14 Design Studio steps and all 12 structured design evidence contracts; the final mobile assertion failed before waiting for a terminal preview state.
- Fix: wait up to 30 seconds for either the existing rendered-preview-ready state or the explicit unavailable-WebGL message. This is stronger than merely counting a canvas element; the full gate remains enabled.
- Verification: native Chrome generated an 80×50×6 mm plate with four 6 mm corner holes, then reloaded and selected it at 390×844. The rendered-preview-ready state appeared and document width stayed within the viewport. The three harness contract tests pass; a fresh full CI run is required. See `034-design-mobile-preview-local.png`.
- Separate open observation: this local Chrome session blocked the direct STEP download with ERR_BLOCKED_BY_CLIENT after the backend served HTTP 200. No browser protection was bypassed and no local downloaded-file success is claimed. The CI revision-download evidence passed; the local browser-specific failure still needs diagnosis.


## 035 — Calibration reuses geometry from a different STL unit interpretation

first divergence: step 2, expected the same STL bytes interpreted as inches to materialize a 25.4 mm cube, state was the first-written 1 mm canonical derivative.

- Severity: high calibration accuracy issue. Canonical derivative storage and recalibration materialization used only the source digest, and historical-cost records did not preserve source units. Separately saved decisions did not prevent this collision.
- Fix: preserve `source_units` through CSV/API/database/engine records and cache keys. Use versioned, unit-qualified canonical artifacts; rebuild old unqualified derivatives from retained source using the existing bounded parser. STEP/IGES retain embedded units. Materialized canonical STL is marked mm to avoid double conversion. Migration 0047 defaults older records to the prior mm interpretation; it cannot infer the units of historical STL actuals.
- Red-to-green: a wrong legacy derivative is ignored; repeated mm/inch/mm reads return 1/25.4/1 mm. Two records sharing a source digest materialize separately and stay normalized exactly once. The engine report cache separates 10 mm from 10 inch cubes (1 versus 16,387.064 cm³). CSV rejects invalid units, defaults omitted units to mm, and preserves units in PostgreSQL readback. The downloadable template still parses all its columns correctly.
- Native Chrome imported explicitly demo-tagged mm/inch records. Direct local database readback confirms both units and stand-in flags; recalibration refuses all three demo records with 0 real of 8 needed. This proves mechanics, not real-world calibrated price accuracy.
- Validation: full backend suite 2,357 passed / 3 documented corpus/OCP-XDE skips; 22 focused checks repeated after final template/guard edits; pyright 217 against the existing 228 baseline; no medium/high Bandit findings (two preexisting lows). Local database migration applied successfully. Frontend 484 tests, typecheck, lint and production build pass. See `calibration-regression.json` and `035-calibration-demo-refused-local.png`. Not deployed.

## 036 — Calibration CSV failures vanish after their toast expires

first divergence: step 2, expected rejected rows to remain available for correction, state was a changed record count with no persistent import summary or row errors.

- Severity: medium usability issue. The calibration import only used transient toasts, including at most three row errors.
- Fix: retain the import counts and all returned row errors beside the upload control, with retry instructions. A new import clears prior results/errors; request failures also remain visible. Reuse the existing machines-screen presentation pattern and import-summary type.
- Verification: the native-browser check first failed because no persistent summary existed, then passed for 2 imported / 1 skipped / 3 total with the exact line-4 invalid-unit error. Retrying a corrected row reports 1 imported / 0 skipped and removes old errors. Re-importing the same records retains the deduplicated count. Runnable check: `scripts/e2e/calibration-import-feedback.mjs`. See `036-calibration-import-fixed-local.png`. Local only.

## 037 — Calibration controls overflow the phone viewport

first divergence: step 1, expected calibration panels to fit a 390 px viewport, state was a 375 px content area with 780 px of horizontal content and clipped controls.

- Severity: medium responsive usability issue. Both panel groups forced two columns at every width, while audit rows forced unwrappable columns.
- Fix: native responsive grid classes stack panels and audit rows on narrow screens; fluid padding and long-text wrapping preserve the existing desktop layout.
- Verification: after a fresh production build, the same page has 375 px content inside 375 px available width. Native phone-width CSV import and Recalibrate both work; demo records remain refused. All 484 frontend tests, TypeScript, changed-file lint and build pass. Viewport reset after the check. See `037-calibration-mobile-before.png`, `037-calibration-mobile-fixed-local.png` and the runnable width check in `scripts/e2e/calibration-import-feedback.mjs`. Not deployed.

## 038 — Invalid cost rates produce plausible-looking recommendations

first divergence: step 4, expected a negative labor rate to be refused without changing the valid estimate, state was accepted -$35/hour, negative labor/setup charges and a new FDM recommendation at $0.60/unit.

- Severity: high cost accuracy issue. Both visible editors accepted negative values and partially parsed strings, while the shared rate-card builder lacked physical bounds. This also affected SHOP overrides and governed rate tables.
- Fix: validate the final rate card once for all three sources, retaining legitimate zero rates and optional process fields. Enforce utilization, stock-size and daily-capacity bounds. Both editors reject malformed/invalid values with persistent accessible errors. Oversized JSON integers return 400 instead of overflowing. The existing uncertainty sampler now respects the stock-size lower bound; engine version 0.3.5 prevents reusing old results.
- Red-to-green: initial backend checks failed on accepted invalid rates; native Chrome reproduced the negative-price behavior. After the fix, negative labor/machine rates and `35oops` remain in the editor with an error while the valid result stays intact. Correcting labor to $70/hour doubles labor/setup exactly, leaves machine/material unchanged and produces MJF $6.98/unit. A 25% markup multiplies all 16 prices by 1.25 within rounding; all line items reconcile. Saved decision JSON is exactly equal to the live export.
- Validation: full backend suite 2,377 passed / three documented skips; 56 focused checks passed after final guards and the huge-integer API case. Frontend 485 tests, typecheck, changed-file lint and production build pass. Pyright remains 217 against 228 allowed; changed backend Bandit has no medium/high findings. See `cost-override-regression.json` and the `038-*.png` browser evidence. Local only; independent arithmetic is not real quote calibration.

## 039 — Saving a scenario pairs old results with unsaved draft inputs

first divergence: step 3, expected recalling the saved “qty 50 / $3.80” scenario to restore those inputs and price, state was quantity 123 at $3.59 because the unsubmitted draft had been saved with the older report.

- Severity: high decision-integrity issue. The scenario callback read editable form state instead of the inputs submitted for the displayed result.
- Fix: retain the options when their successful report arrives and use those same options for the scenario label and recall. Both workspace layouts share this callback; no new scenario system or dependency is added.
- Verification: the runnable native CUA check first failed with `QTY 123`. After the fix and production rebuild, the identical draft edit/save/recall restores 50 and 5,000, with MJF $3.80 at 50. Frontend 485 tests, typecheck, changed-file lint and production build pass. See `scripts/e2e/cost-scenario-snapshot.mjs`, `cost-scenario-regression.json` and `039-*.png`. Local only.

## 040 — Rate explanations misstate markup and user provenance

first divergence: step 1, expected an edited daily-capacity assumption to be marked USER, state was 4 hr/day marked DEFAULT. The margin tooltip also said “target margin” despite the actual cost-plus calculation.

- Severity: medium explanation accuracy issue. The daily-hours tag was hardcoded, and its description omitted that process-specific capacity takes precedence. The margin API key is retained for compatibility, but its formula is markup on cost.
- Fix: derive daily-hours provenance through the existing rate-card method, state its fallback role and explain `price = cost × (1 + margin)`, including the 0.25 example. Shared report metadata carries the correction to browser and exports; stored historical evidence remains unchanged.
- Verification: a focused regression failed on the old descriptions and now checks DEFAULT/SHOP/USER provenance. Native Chrome and its downloaded JSON show a fresh 5 hr/day edit as USER, the explicit fallback explanation and accurate markup description. All 70 related costing/rate/API/ensemble checks pass. See `cost-scenario-regression.json` and `040-*.png`. Local only.

## 041 — Quantity slider contradicts calculated prices and lead times

first divergence: step 2, expected the quantity-50 slider reading to match the same real-STEP report's $3.80, state was $4.90 beside a confidence band centered on $3.80. At 10,000 it reused the 50-unit 5.6–10.4-day lead time instead of the calculated 7–13 days.

- Severity: high decision accuracy issue. The curve fit used only the first and last prices, disregarding intermediate calculated quantities with different minimum/batch effects. Lead times always came from the first estimate, and confidence could come from a different quantity.
- Fix: preserve every calculated price; interpolate between neighboring points in inverse quantity and include every actual quantity in chart samples. Both decision layouts use the quantity-specific estimate for lead time, explicitly label its quantity and show confidence only at that estimate's actual quantity. Uncosted prices and curve limitations are clearly labeled; the existing re-cost controls remain available for a fresh calculation.
- Red-to-green: real STEP recalculated at 1, 50, 123, 5,000 and 10,000 produced 40 process/quantity prices. The new arithmetic regression and native CUA check both failed at $4.90 versus $3.80 before the fix; all 40 points now match exactly. Chrome confirms $3.80 at 50, $3.48 and 7–13 days at 10,000, and explicit approximation/lead-quantity labels at 9,908. All 486 frontend tests, typecheck, changed-file lint and production build pass.
- Evidence: `quantity-slider-regression.json`, `scripts/e2e/cost-slider-reconciliation.mjs` and `041-*.png`. Local only. Intermediate/extrapolated prices remain approximations; this does not independently validate the engine's multi-process crossover advice or real quote accuracy.

## 042 — Tooling crossover ignores cheaper make routes at higher quantities

first divergence: step 1, expected crossover advice to account for the same report's cheaper MJF option, state was “FDM stays cheapest up to 923” even though quantity 50 recommended MJF. At 923, molding merely matched FDM near $8.68 while MJF cost $3.49.

- Severity: high sourcing-decision accuracy issue. The crossover compared tooling only with the lowest-quantity winner. Three duplicated browser summaries and the comparison view then overstated that winner's scope; the no-crossover branch also falsely claimed one process won at every quantity.
- Fix: compare the selected tooling candidate against the cheapest eligible no-tooling route at each evaluated quantity, preserving DFM/environment exclusions. The constant-variable fallback must likewise beat every eligible route. List the actual per-quantity picks in report notes and share one accurate summary across live, staged, saved and comparison views. State redesign requirements and remove the unsupported claim that crossover direction is robust to cost uncertainty. Engine version 0.3.6 prevents reuse of old calculations.
- Red-to-green: an analytic three-route control formerly crossed at 223 instead of 950; both numerical and constant-variable paths now return 950. Excluded/DFM-failed make routes are omitted, and a route that tooling never beats prevents a false crossover. No-tooling cases retain changing per-quantity winners.
- Real native STEP proof: crossover changes from 923 to approximately 4,592. Separate recalculations at 923, 4,591, 4,592 and 5,000 confirm the cost comparison, including line-item sums on opposite sides of the boundary. Live, saved and comparison summaries agree; native saved and live JSON are exactly equal. See `crossover-routes-regression.json` and `042-*.png`.
- Validation: 2,382 backend tests passed / three documented skips, plus the final focused test extension; 487 frontend tests, typecheck, changed-file lint and production build pass. Pyright remains 217 against 228 allowed; changed-backend Bandit has no medium/high findings. The first full test attempt hit a shared rate-limit bucket due to an incorrect test environment variable; the corrected run used the repository's CI settings without changing product throttles.
- Boundary: not deployed. Numerical bracketing assumes a sustained transition; batch effects can cause local recrossings, so the result remains explicitly approximate. The tooling candidate remains the lowest-cost tooling route at the highest requested quantity. Real quote accuracy still requires actual authorized quote data.

## 043 — Public cost summary contradicts its shared recommendation table

first divergence: step 2, expected the shared six-quantity report to retain the corrected conditional advice, state was “Make below ~4,592 units with FDM” above rows recommending MJF at 923 and 4,591. Its $18–$42 confidence band did not name its quantity.

- Severity: high shared decision accuracy issue. The public page had another independent crossover summary and picked the first estimate for a process without explicitly binding its quantity.
- Fix: reuse the same `crossoverSummary` as the private views. Select the lowest costed recommendation and its exact process/quantity estimate; label the headline and confidence band with that quantity. Link-preview text now describes quantity-specific options instead of suggesting one universal winner.
- Native real-STEP regression fails before rebuilding and passes afterward. All six recommendation rows reconcile with the saved report; the molding crossover is conditional on redesign, and FDM's $18–$42 band explicitly belongs to quantity 1. The sanitized API content matches the native saved export, with no forbidden nested owner/hash identifiers. Copy-link is verified by native paste into an unsaved field, then cleared.
- Revocation: both cookie-free backend and same-origin proxy return 404; the native page becomes unavailable. Re-sharing creates a different link with identical content, and the original remains 404. Both disposable cost links are revoked at the end. See `public-share-regression.json`, `scripts/e2e/public-cost-reconciliation.mjs` and `043-*.png`.
- Validation: 487 frontend tests, typecheck, changed-file lint and production build pass. Local only; signed-in Chrome rendering and separate unauthenticated HTTP checks are recorded distinctly.

## 044 — Shared DFM report omits every process-specific failure reason

first divergence: step 1, expected the injection-molding failure to expose its draft warning and fix, state was a “Required” row without any way to read the findings. The real STEP had 22 process findings in the shared payload and zero on the page.

- Severity: medium report completeness and explanation issue. The public renderer displayed only universal issues, despite receiving the per-process findings.
- Fix: expose each process's existing findings through native details controls, reusing `IssueList` for severities, measurements and fixes. Identify the recommended route, distinguish part-level findings from candidate-process findings, and reuse the same process names/percentage suitability as the private report. Unavailable-share metadata also keeps noindex.
- Native regression fails before rebuild and passes afterward. All 21 process rows and all 22 underlying findings are readable, including four injection-molding findings. Geometry and all process scores/issues match the stored analysis. At 390 px the document stays 375 px wide; the table scrolls within its 341 px container. The viewport is reset after testing.
- Revocation: native public page becomes “Analysis not available”; unauthenticated backend/proxy reads return 404 and PostgreSQL confirms private/null share state. See `public-share-regression.json`, `scripts/e2e/public-analysis-reconciliation.mjs` and `044-*.png`.
- Validation: final 487 frontend tests, typecheck, changed-file lint and production build pass. Backend unchanged from the preceding 2,382-test run. Local only; this verifies faithful presentation, not independent certification of every DFM rule.

## 045 — Draft and recalled units separate the preview, cost and DFM geometry

first divergence: step 2, expected an unsubmitted inch edit to leave the displayed 10 mm result intact, state was a new inch-scale preview with the old millimetre DFM hash, disabling exact face highlighting. Recalling a saved millimetre scenario after an inch re-cost then showed 10 × 10 × 10 mm costs beside 254 × 254 × 254 mm DFM.

- Severity: high geometry and decision consistency issue. The viewers consumed editable units immediately, while scenario/override/shop callbacks submitted only costing and retained the previous DFM analysis.
- Fix: retain the submitted options separately from the editable draft. Route upload, re-cost, scenario recall and automatic overrides/shop changes through the same paired cost/DFM submission, and give both viewer layouts those submitted units. Advance the existing attempt guard and clear terminal failure state per submission; stale responses cannot replace the newer pair. DFM retry uses the submitted options.
- Native regression: real `cube-10mm.stl` first fails with one 10 mm readout and one 254 mm readout. After rebuilding, a draft inch change preserves both 10 mm readouts and the exact mesh alignment. Explicit inch submission produces two 254 mm readouts; recalling the $3.44/qty-50 millimetre scenario restores both to 10 mm and 1 cm³. Selecting draft findings restores visible colored faces with no converted-mesh refusal.
- Validation: 487 frontend tests, typecheck, changed-file lint and production build pass. Existing submission-order assertions were updated to follow the shared entry point; STL validation still precedes submission. Native CUA check is `scripts/e2e/source-unit-consistency.mjs`; evidence is `source-unit-consistency.json` and `045-*.png`. The selection assertion was strengthened after the initial red/green run and passed again. Backend unchanged.
- Boundary: local only. Both layouts compile with the same source-unit contract; this native replay used the tabbed workspace. A separate rapid-response race was not reproduced and is not claimed as verified.

## 046 — DFM matrix hides required fixes and misstates priced routes

first divergence: step 1, expected the cube's required CNC turning/casting/forging fixes to have explanations, state was five blank blocker cells. The table also claimed all 21 processes were costed when only eight had estimates, and said the cost and geometry recommendations differed when both were MJF.

- Severity: high decision/explanation accuracy issue. Blocker extraction depended on cost estimates, losing findings for excluded processes. The costed flag meant a process was supported in principle, and the difference note tested only whether a cost pick existed. On a 390 px phone viewport, the 476 px table clipped its entire blocker column inside a 306 px container.
- Fix: preserve error messages for every process in the shared report and derive costed flags from actual estimates, including no estimates for invalid geometry. Retain estimate-only compatibility for older reports. Compare the actual routing picks, identify the cost pick's quantity, display suitability percentages consistently, and label the column as the first blocker. Use native horizontal overflow for narrow tables. Engine version 0.3.7 prevents reusing old calculations.
- Red-to-green: the backend regression first failed with 21 costed processes versus eight actual routes. Native real 10 mm STL and 20×15×10 mm STEP checks now reconcile all 21 rows, eight priced routes and six required blocker rows with their downloaded JSON. The MJF/MJF case has no difference note; the STEP quantity-1 FDM/MJF case names both correctly. Previously unpriced die-casting draft findings can be selected and highlight the model. Injection-molding suitability reads 5%, matching the detailed audit, rather than a rounded 0.1.
- Mobile regression first failed on hidden overflow; after rebuilding, the same table scrolls, its blocker text is reachable at horizontal offset 160.5 px, and the document stays within the 390 px viewport. Viewport restored afterward.
- Validation: 2,383 backend tests passed, three documented real-corpus/OCP-XDE skips; 487 frontend tests, typecheck, changed-source lint and final production build pass. Pyright remains 217 against 228 allowed; changed backend Bandit has no medium/high findings. Runnable native check: `scripts/e2e/dfm-matrix-reconciliation.mjs`; evidence: `dfm-matrix-regression.json` and `046-*.png`.
- Boundary: local only. This verifies report fidelity and the observed controls, not independent certification of all DFM rules or real quote accuracy. Historical saved reports keep their original evidence; older reports without per-process blockers retain the estimate fallback.

## 047 — Manually declared machine rates are presented as calibrated marginal rates

first divergence: step 3, expected a synthetic $10/hour inventory declaration to remain USER evidence, state was a SHOP “calibrated rate” driver, a bound-shop indicator and a $10/hour “marginal rate” label despite the source calculating $6.50/hour after its default capital adjustment.

- Severity: high provenance/explanation accuracy issue. Persistence was incorrectly treated as calibration in the shared machine override; the Verify badge inferred a bound shop card from any machine rate. Its resource-cost prose hardcoded SHOP and mislabeled the pre-adjustment hourly input.
- Fix: declared machine overrides retain USER provenance in the engine and saved reports. The compact governed-card indicator reads the existing effective-rate endpoint and makes no affirmative claim while unconfirmed. Verify identifies the declared hourly rate and points to the separate capital derivation; driver copy follows the actual source. The shared routing panel likewise labels the input as a declared rate. Engine version 0.3.8 separates new evidence from historical reports.
- Native proof: machine setup refuses count 0, rate -10 and a zero envelope, preserving the form. A valid, explicitly synthetic FDM declaration (two machines, 200 mm envelope, 10 kg, $10/hour) survives reload. A real 10 mm STL cube is makeable on that named machine. Both backend provenance checks and the native browser regression fail before the fix and pass afterward; the machine driver and rate caption now say USER, and no governed card is claimed.
- Saved report reconciliation: all 48 process/quantity prices and line-item totals are exactly unchanged when matched by process and quantity. FDM machine drivers at all six quantities now carry USER. The before and after native exports belong to engine 0.3.7 and 0.3.8 respectively; old records are not rewritten. The $6.50/hour capital-adjusted calculation remains in the detailed source.
- Validation: full backend 2,383 passed / three documented real-corpus/OCP-XDE skips; 487 frontend tests, typecheck, changed-source lint and build pass. Pyright 217/228; no medium/high changed-backend Bandit findings. The existing organization-boundary source test now follows the guarded rate-card read. See `scripts/e2e/machine-rate-provenance.mjs`, `machine-rate-provenance-regression.json` and `047-*.png`.
- Boundary: local only. No real shop calibration or physical machine certification is claimed. Governed-card activation and network-read failure were not separately replayed in the native browser.

## 048 — Editing machine inventory leaves the live verdict on old capabilities

first divergence: step 3, expected a saved 5 mm machine limit to invalidate a 10 mm cube's in-house verdict, state was the old 200 mm envelope and “Makeable on your machines.” Re-uploading the same bytes correctly reported “envelope: need 10, have 5,” proving the underlying fit calculation was not the failure.

- Severity: high decision freshness issue. Machine mutations refreshed only the inventory screen; Verify retained its previous machine snapshot, cost and fit verdict.
- Fix: successful create/edit/delete and nonempty CSV imports notify the workspace through one callback. Invalidate the displayed result and pending attempt, retain the source file, and rerun verification when returning to Verify. A new upload consumes the pending refresh so it does not trigger a duplicate run. Existing persisted historical records remain unchanged.
- Native red-to-green: restoring 200 mm after a fresh 5 mm rejection also left the old negative verdict before the fix. After rebuilding, editing to 5 mm automatically produces the named envelope gap; restoring 200 mm automatically restores the in-house verdict. Neither transition re-uploads the file. The synthetic machine is restored to its original capacity.
- Validation: 487 frontend tests, typecheck, changed-source lint and production build pass. Backend unchanged from the preceding 2,383-test run with three documented skips. Runnable CUA check: `scripts/e2e/machine-inventory-refresh.mjs`; evidence: `machine-inventory-refresh-regression.json` and `048-*.png`.
- Boundary: local only. Native replay covered same-workspace edits. Create/import/delete share the invalidation callback but their re-verification transitions were not separately replayed. Edits from another tab or an external API still require a fresh verification.

## 049 — Saved-record actions lose the record identity and receipts hide quantity

first divergence: step 2, expected “Open the record” to open the cube verification just saved, state was the entire Records list, including other files and duplicate filenames. Opening a row then showed $7.53/unit without identifying quantity 10,000, while the live verdict had shown $30 at quantity 1.

- Severity: medium navigation and cost-context issue. Both Verify actions discarded the saved ID, and the Records popup selected the largest-quantity estimate without labeling that selection.
- Fix: both actions use ordinary Next links to the existing authenticated decision-detail route with the actual saved ID. The popup identifies the exact process, material and quantity for its drivers and confidence. Prices and selection behavior are unchanged.
- Native red-to-green: both link checks initially found zero record-specific links; the receipt check found no quantity context. After rebuilding, both links target `01M3R3SCMPTWKBDBKX0FXNXD1E`, and clicking the verdict link opens that exact saved cube decision. The popup explicitly shows FDM / FFF, PLA and quantity 10,000, retaining $7.53 and its $4.52–$10.55 assumption band.
- Validation: 487 frontend tests, typecheck, changed-source lint and production build passed; both native regression checks passed. See `scripts/e2e/saved-record-reconciliation.mjs`, `saved-record-regression.json` and `049-*.png`. Backend unchanged. This is local proof, not a production rollout.

## 050 — Newer metal processes are omitted from the make-versus-tooling decision

first divergence: step 2, expected the real NIST FTC-07 decision to choose the cheapest eligible no-tooling estimate, state was CNC 5-axis at $1,627.63 for quantity 50 despite a DFM-ready WAAM estimate of $909.74. The slider chose WAAM while the backend note and saved recommendation chose CNC; the selected die-casting crossover was incorrectly 57 units.

- Severity: high recommendation/crossover accuracy issue. The shared decision whitelist predated the separate EDM, metal powder-bed, binder-jet and DED/WAAM cost families. Investment/sand casting and forging were likewise missing from tooling selection and its explanatory caveats.
- Fix: include every existing no-tooling family in make ranking and every existing die/pattern family in tooling ranking, crossover comparison and conditional explanations. Preserve DFM and service-environment exclusions. Engine version 0.3.9 separates new calculations from historical reports. No underlying rate or price formulas changed.
- Red-to-green: seven metal-process controls initially chose CNC instead of the cheaper eligible process. All now pass, including environment exclusions, DFM failures and casting/forging tooling. The real AS1 assembly oracle now checks minimum eligible cost instead of forcing CNC. Environment-flip fixtures use quantity 100, where Mild Steel wins before exclusion, retaining the existing positive exclusion/changed-pick assertions; quantity 10 now correctly prefers already-qualified EDM.
- Native proof: the exact public NIST STEP now reports WAAM consistently in live and saved recommendations. All 20 original prices and line items are unchanged. Explicit quantities 50/57/101/102/5000 independently reconcile each make pick against all eligible no-tooling estimates. At the old threshold 57, WAAM is $909.93 versus die casting $1,605.53. At 101, $910.06 is below $917.67; at 102, die casting $908.93 is below WAAM $910.02. The redesign warning remains.
- Saved/live JSON is exactly equal for all 50 boundary-run estimates, record `01M3R5PQHVPT6BE584E0R6J1J8`. Evidence: `metal-route-regression.json` and `050-*.png`; runnable backend regression: `tests/test_costing_crossover_routes.py`.
- Validation: 38 focused assembly/machine/decision checks pass; the final full backend suite passes 2,391 tests with three documented real-corpus/OCP-XDE skips (167.69 seconds). Pyright remains 217 against 228 allowed; changed production backend Bandit has no medium/high findings. The wider scan also reported the existing B310 URL-open warning in the unchanged NIST fixture downloader; the diagnostic change did not add network access. Frontend is unchanged from the clean-install, zero-audit-finding, 487-test/full-lint/build pass.
- Boundary: local only; this proves consistent model selection, not measured manufacturing prices or physical certification. Crossover still compares the tooling candidate selected at the highest requested quantity against all eligible make routes; it does not optimize a sequence of different tooling investments. Batch recrossings remain approximate and are labeled.


## 051 — Program volume edits alter invalid input and can erase existing demand

first divergence: step 2, expected the program assignment draft to retain `1.5` and reject it, state was `15` with assignment enabled. The same digit-stripping affected existing assignments; zero normalized to null instead of an error. After removing a cube whose saved annual demand was 1,000, the reassignment draft was blank and would clear that demand.

- Severity: high declared-data/annual-cost integrity issue. The program clients also performed a best-effort GET and resent unrelated fields; a failed read turned existing lineage/demand into nulls. The backend already supports partial-field updates, making that merge unnecessary.
- Fix: share a strict whole-count parser across assignment/edit inputs; distinguish blank (explicit clear) from invalid; preserve raw drafts and provide accessible errors. Reassignment starts with existing demand. Send only edited fields through both program clients. The API refuses coerced booleans/strings/floats and counts beyond the existing PostgreSQL integer column's capacity, before any write.
- Red-to-green: native `1.5` became `15` before the fix; request tests observed a failed GET followed by a PUT with unrelated null fields; the API schema accepted `true` as a count. The saved-demand reassignment check observed blank instead of 1,000. The corresponding regressions now cover strict parsing, partial requests, DB preservation and browser controls.
- Native local proof: real NIST FTC-07 at 50 units contributes $45,487 (= $909.74 × 50), and the 10 mm STL cube at 1,000 contributes $3,110 (= $3.11 × 1,000). Both prices reconcile against their actual downloaded engine reports. Program detail/list/reload show $48,597. Five invalid values in each input path are refused without altering saved exposure. Quantity 51 persists but correctly withholds a price because no exact engine point exists; clearing, recovery, Enter-save, removal and reassignment are exercised separately.
- Validation: 489 frontend tests, typecheck, changed-source lint and production builds pass. 41 backend part-context/BOM/portfolio/environment checks pass, including real PostgreSQL API write/read/isolation and invalid-request preservation. Pyright remains 217 vs 228 allowed; changed backend Bandit has no medium/high findings. The preceding full backend run for finding 050 was 2,391 passed with three documented skips; no new full-suite result is inferred from the focused checks.
- Evidence: `program-volume-regression.json`, `051-*.png`, and runnable native checks in `scripts/e2e/program-volume-validation.mjs`. Local verification only; production rollout remains pending.

## 052 — Program exposure clips on phones and partial sums lack a clear label

first divergence: step 3, expected the cost panel to fit the 390 px program-detail screen, state was a 424 px inner panel with the yearly total clipped to the right. Separately, after clearing one of two parts' volumes, the program list displayed the remaining part's subtotal as ordinary yearly exposure without identifying its incomplete coverage.

- Severity: medium mobile usability and cost-summary clarity issue.
- Fix: use responsive native CSS grids for both program list and detail. Mark incomplete sums as “Partial total” with included/assigned part counts on both surfaces. Call model prices estimates in the introductory explanation.
- Native red-to-green: program detail now measures 390 px client/scroll width at the 390 px viewport. The entire exposure card is readable by normal vertical scrolling. Both list and detail identify “1 of 2 parts included”; restoring the second valid volume restores $48,597 and removes the partial label. No amounts or backend aggregation formulas changed.
- Evidence: `052-program-mobile-before.png`, `052-program-mobile-fixed.png`, and the shared native regression module/report. Typecheck, changed-source lint and production build pass. Viewport override reset after testing.


## 053 — Training CI still pins the superseded FDM-only crossover

first divergence: step 2, expected the training runner's pinned crossover of 923, state was the corrected 4,592 returned after finding 042. Its geometry, source, make-process, quantity and estimate-count assertions had already passed. The user-facing HTML guide contains no 923-unit claim; the stale value exists only in this test oracle.

- CI 36664250281 passed eight jobs and all 34 real-CAD corpus cases. FTC-07 completed in 38.766 seconds with the exact pinned source hash. Restore, load and readiness checks also passed before this later training failure. The previous intermittent timeout is not explained by a successful rerun; diagnostics remain enabled.
- Fix: update the single golden crossover value to 4,592, supported by the independent real-STEP price/boundary checks in `crossover-routes-regression.json`. At 923, injection molding still loses to MJF; at 4,591 its unrounded line-item sum remains higher, and at 4,592 it becomes lower. No acceptance tolerance, timeout, geometry/price checks or user-facing calculation changed.
- Validation: all three existing training-runner utility tests pass. Full current-head CI, including the complete training guide and subsequent deck journey, remains required. Evidence: `ci-36664250281-summary.json`.


## 054 — Library identity mappings crash or hide the reason for rejected rows

first divergence: step 2, expected a row-level validation message after importing the real STEP with a numeric JSON name, state was “onboard failed — Onboard failed (500)”. A CSV containing a duplicate filename and a missing filename instead said “2 mapping rows ignored (see reasons)” without rendering any reasons; the duplicate actually used its last row.

- Severity: medium import reliability, feedback and accessibility issue.
- Fix: validate the JSON collection and all declared string fields before trimming. Retain valid rows and return explicit reasons for invalid rows, with one-based JSON entry numbers. Display every mapping issue rather than falsely calling all of them ignored. Native buttons make both file pickers keyboard-accessible; pending uploads disable both pickers, and results/errors have status/alert semantics.
- Native proof: the same numeric-name JSON returns a successful geometry import with “Mapping row 1 — name must be text or null” and an accurate unnamed count. Correcting to CSV exposes the duplicate/last-row-wins and missing-filename messages. Enter operates both choosers and submits. A real STEP plus corrupt STL and unknown-material NIST STEP imports one and reports two separate skips. At a 390 px viewport the library panel measures 320/320 px and its result 280/280 px, with all reasons readable.
- Regression: the pure parser check covers invalid top-level shapes, all five field types, nulls and preservation of valid rows. Native check: `scripts/e2e/library-onboard-validation.mjs`. Evidence: `library-import-regression.json` and `054-*.png`. Local only.

## 055 — Library import runs CAD work on the API loop and miscounts duplicate identities

first divergence: step 1, expected CAD/hash/signature computation to leave the API event loop, state was a synchronous service call into the legacy route parser; the regression guard rejected the real STEP/STL imports. Code tracing also showed that duplicate hashes counted the first name while the database stored the last name.

- Severity: high availability issue, with a separate summary-count defect.
- Fix: reuse the existing async parser (including its native-process isolation, timeout and single-flight behavior) and offload hashing/signature computation through the standard thread helper. Track the final name per unique source hash, matching the existing last-write-wins storage contract. No new parser, executor or deduplication rules.
- Verification: the real PostgreSQL cold-start test now asserts computation leaves the event-loop thread while retaining real CAD parsing, manifest writes, similarity retrieval and tenant isolation. Duplicate named/unnamed imports in both orders verify the final summary against database readback. Native upload of two byte-identical real STEP files with the final named mapping reports exactly one onboarded part and no unnamed count.
- Evidence: extended `backend/tests/test_parts_master_onboard.py`, `library-import-regression.json`, and `055-library-duplicates-fixed-local.png`. Production retest remains required.

## 056 — Library upload limits act after unbounded reads and ZIPs bypass the memory budget

first divergence: step 2, expected the oversized identity mapping to be rejected before import, state was entry into the importer with an unbounded upload read. Direct files were likewise read in full before their aggregate-size check; ZIP contents were all loaded before the library file-count limit and did not share the direct-upload byte budget.

- Severity: high availability/input-boundary issue.
- Fix: bound each direct read by the remaining aggregate budget plus one byte; reject excess direct file counts before reading. Check extracted ZIP counts and expanded size before loading blobs, including any direct files in the same request, and retain request-local cleanup. Reuse the existing bounded manifest reader for identity mappings (2 MiB default). Malformed ZIPs now produce HTTP 400; size failures produce HTTP 413.
- Verification: request tests cover direct aggregate limits, oversized mapping, expanded ZIP size, combined direct/ZIP size, malformed ZIP errors, positive bounded read sizes, cleanup and no importer/commit calls on rejection. Native Chrome rejects a mapping above 2 MiB with an actionable message, retains the real STEP selection, and succeeds when only the mapping is corrected.
- Evidence: `test_onboard_rejects_oversized_inputs_before_import`, `library-import-regression.json`, and `056-library-size-error-local.png`. This is bounded local/API proof, not a production load certification.

Validation for 054–056: 56 focused backend tests pass, including live PostgreSQL and existing batch reader checks. Frontend library tests (5), typecheck, changed-source lint and production build pass. Backend type baseline remains 217 against 228 allowed; Bandit reports no medium/high findings in the changed backend files. The final full backend suite passes 2,394 tests with three documented real-corpus/OCP-XDE skips (170.12 seconds).


## 057 — A part's “open program” action discards its assigned program

first divergence: step 3, expected the NIST part's link to open “Audit volume 051”, state was the general Programs list, requiring another selection.

- Severity: medium navigation/context issue.
- Fix: keep the selected program in the existing workspace component and pass the part's saved program name to the existing detail view. Program-list selection uses that same state. Unassigned parts still go to the assignment/list entry point.
- Native red-to-green: the exact-heading regression failed before the fix and passes afterward. The direct link opens both assigned parts and their unchanged $48,597 annual estimate; back-to-list and normal list selection also pass.
- Validation: all 489 frontend tests, typecheck, changed-source lint and production build pass. Evidence: `program-link-regression.json`, `057-*.png`, and the assertion in `scripts/e2e/program-volume-validation.mjs`. Local only.


## 058 — Enterprise cost goldens still pinned the omitted metal-route winner (test defect)

CI 36667332535 passed eight jobs, then the enterprise journey stopped before declaring portfolio context: its $133.58 CNC headline oracle rejected the corrected $110 wire-EDM recommendation. The three later context/program failures were downstream of that first assertion. The run did not reach the CAD corpus or training guide/deck.

A separate real-STEP engine replay uses the identical SHA-pinned cube, four declared machines, owned-process flags, stainless class and severe-service environment. All 66 existing CI prices, line items and readiness flags match exactly. At quantity 1, eligible wire EDM totals $110 including the order minimum; at exactly 12,000 units, eligible binder jetting totals $2.463 before display rounding and $2.46 in the persisted recommendation. The portfolio contract therefore gives $2.46 × 12,000 = $29,520, not the stale $120,960 CNC value. No production formula changed for this repair.

Updated the fixed numbers in the enterprise runner, its source-contract tests, answer-fidelity gate, release-evidence gate/fixture and RFQ fixture. Quantity matching, missing-volume withholding, arithmetic reconciliation, procurement thresholds, confidence/provenance assertions and tolerances remain unchanged. Twelve pure Node checks pass. Reproducible geometry/cost assertions are in `enterprise-cost-oracle.py` with sanitized inputs and CI comparison values in `enterprise-cost-oracle.json`. Full exact-head CI and production proof remain required; controlled model agreement does not establish real quote accuracy.


## 059 — Part standing hid verdict/history controls outside phone width

Native Chrome at 390 px measured a 677 px standing panel, with the three history buttons at x=614–652, outside the visible viewport. The fixed 360 px identity column plus a second column forced the overflow; the document itself still reported 390 px, so a document-only check missed it.

Reused the existing program-page auto-fit/minmax grid pattern, allowed long part text to wrap and made history/driver rows wrap within their cards. No result data or navigation behavior changed. The CUA regression fails before the patch and passes afterward at 390 px, at 320 px with a real saved record expanded, and at the normal desktop size. Native opening and Enter-to-collapse work. Typecheck, changed-file lint and production build pass. See `part-mobile-regression.json`, screenshots `059-*`, and runnable `scripts/e2e/part-mobile-validation.mjs`. Production verification remains pending.


## 060 — Verify comparison ignored per-quantity winners and hid redesign conditions

Native saved-cube comparison at quantity 100 called FDM the make-now route and priced it at $7.57, although the same saved JSON recommends MJF at $3.27. The route chart always followed the quantity-1 process. Native NIST comparison also said die casting was cheaper at quantity 102 without showing its recorded redesign requirement.

The route panel now consumes the already-loaded saved decision and existing quantity helpers: each curve point, selected process, unit price and band belongs to that quantity's actual recommendation. Tooling points exclude environment-invalid estimates. The panel reuses the shared crossover explanation and explicitly labels conditional tooling, including when it is cheaper. No costs, backend calculations or historical records are rewritten. Removed the superseded static-process curve helper.

The native assertion fails before the fix, then passes for cube quantities 1 (FDM $30), 100 (MJF $3.27), and 10,000 (MJF $3.11 versus conditional molding $2.69); NIST quantity 102 retains WAAM $910.0 versus conditional die casting $908.9. Switching to side B shows its own NIST 5,000-unit prices, $909.7/$44.58. All 489 frontend tests, typecheck, changed-file lint and final production build pass. Evidence: `compare-route-regression.json`, `060-*.png`, runnable CUA assertion `scripts/e2e/compare-route-validation.mjs`. Full CI and production proof remain pending.


## 061 — Part Compare discarded the selected saved record

Clicking Compare from the real cube standing opened the two newest NIST records instead. The standing button only called `nav("compare")`; the comparison screen always initialized from the first two list entries.

The existing shell now carries the selected record ID through ordinary props, as it already does for the selected program. Side A uses that exact saved record; side B prefers another record with the same filename. Leaving comparison clears the handoff. If the requested record lies outside the recent list, the UI asks for an explicit selection instead of silently substituting another part. Manual selection and the normal unselected entry remain available.

Native regression: cube navigation fails with the NIST ID before the fix, then passes with cube ID `01M3R3SCMPTWKBDBKX0FXNXD1E` and its prior cube record. Opening NIST next correctly replaces the selected ID with `01M3R5PQHVPT6BE584E0R6J1J8`. All 489 frontend tests, typecheck, changed-file lint and production build pass. Evidence: `compare-selection-regression.json`, `061-*.png`, and `assertSelectedComparisonRecord` in the existing CUA comparison check. Production verification remains pending.


## 062 — Comparison cards and controls overflowed phone width

At a confirmed 390 px viewport, the comparison main scrolled to 479 px; the route panel extended from x=322 to x=479 and its controls were clipped. The fixed two-column layout did not stack.

Reused the program/standing auto-fit grid pattern, bounded native record selectors, and kept the per-process table legible in a labeled, keyboard-focusable horizontal scroll region. At 390 and 320 px the main now fits exactly and every record/quantity/side control is within the viewport. At 320 px, ArrowRight reaches scrollLeft 134 and brings the delta column to x=263; the table's 340 px content is intentionally scrollable. The route slider still yields the exact saved MJF $3.11 / conditional molding $2.69 at 10,000. Desktop layout also passes.

Typecheck, changed-file lint and production build pass. See `compare-mobile-regression.json`, `062-*.png` and `assertComparisonFits` in the existing CUA comparison check. The viewport assertion also guards against testing the wrong active tab. Production proof remains pending.


## 063 — Comparison price cells dropped saved readiness conditions

The real NIST comparison showed CNC 3-axis at $649.61 and die casting at $44.58 (quantity 5,000) without either cell's stored `dfm_ready=false` condition. WAAM is DFM-ready at $909.74. Even after the route chart was corrected, the separate per-process price table still omitted these conditions.

The existing process/quantity band index now retains readiness alongside confidence. Each price cell shows `requires redesign` for DFM-blocked estimates, or `environment excluded` when the saved estimate is excluded. No prices or deltas change. Replaced the fallback claim that differences were mostly quantity effects with the actual comparison threshold: no comparable driver difference above 5% was identified.

Native NIST regression fails before the change and passes after it: both CNC and die-casting cells are labeled, both feasible WAAM cells remain unmarked, and the unsupported quantity explanation is absent. All 489 frontend tests, typecheck, changed-file lint and production build pass. The environment-exclusion label is wired from the saved flag but has not been separately replayed through this native comparison screen. Evidence: `comparison-readiness-regression.json`, `063-*.png` and the CUA comparison assertion. Production verification remains pending.


## 064 — Verify and acquisition priced the prototype route at every quantity

**High; fixed locally, deployment pending.** CI 36670069143 passed all 17 enterprise steps and eight other jobs, but failed the VER-06 golden: the saved recommendation at 10,000 units was binder jetting at $2.46 while the Verify card showed wire EDM at $15.60. All other eight enterprise goldens passed; CAD corpus/training gates were not reached. Native Chrome reproduced this exact stainless STEP mismatch and the polymer equivalent (FDM $8.42 despite MJF winning).

The shared quantity selector now follows the saved recommendation's process and material at the exact computed quantity and returns no estimate for absent/excluded rows. Calls without a quantity preserve their explicitly documented prototype-process amortized summary. Verify's label, price, band, drivers and owned-machine rate now use that selected route. Acquisition uses the per-quantity recommendation curve and matching labels; Ask and comparison drivers inherit the shared fix. Interpolation reuses the environment-filtered selector. Removed unsupported ownership, no-acquisition and never-pays-back claims from the tooling alternative display.

Native real STEP checks pass for Wire EDM $110 at qty 1 and Binder Jetting $2.46 at qty 10,000, including acquisition and Ask. The saved report table supplies the independent UI oracle. An attempted native JSON export event timed out in the CUA bridge; this attempt is not counted as export proof. All 492 frontend tests, typecheck, changed-source lint and the production build pass. No engine prices or CI assertions were loosened. See `verify-quantity-regression.json`, `ci-36670069143-summary.json`, `064-*`, and `scripts/e2e/verify-quantity-reconciliation.mjs`.

## 065 — Recommended route inherited another process's in-house machine verdict

**High; fixed locally, deployment pending.** The same CI result paired the prototype Wire EDM price with an in-house banner and the passing Haas CNC machine, while the per-route block correctly marked Wire EDM outsource-only. The backend aggregate correctly describes whether any route can run in-house; it cannot establish machine ownership for the displayed process.

A shared route-fit selector now uses the displayed process's own verdict and machine. Missing per-route evidence stays unknown. Verify, record detail and part standing use the selected route's fit. Regression checks reproduce aggregate CNC pass versus Wire EDM outsource-only, reject inherited machine names, and preserve unknown for missing routes. Native controlled-inventory replay is recorded in `verify-route-fit-regression.json`.

## 066 — Verify always said program not set, even with saved annual demand

**Medium; fixed locally, deployment pending.** CI's declared 12,000-unit program was shown correctly in the context strip but Resource cost hard-coded “program not set.” The readout now uses the same loaded part context, distinguishes an unavailable read from an undeclared volume, and prints the saved program name.

Native assignment of the real STEP to local program “Audit quantity 064” with annual demand 12,000 first withheld exposure because the quantity was absent. Re-verification included qty 12,000 in its six-point ladder. Resource cost now shows “annual volume · 12,000 · Audit quantity 064”; the selected qty 10,000 still reconciles to Binder Jetting $2.46. See `066-verify-context-fixed.png` and `verify-quantity-regression.json`.


## 067 — Re-cost after inventory changes linked to an older saved result

**High; fixed locally, deployment pending.** Declaring “Audit CNC 065” and re-verifying the same stainless STEP produced live in-house CNC fit and a changed CNC cost curve, but the response still linked to saved record `01M3RCF856MX3SFCSZTMDABEMP`. Independent Postgres readback showed that record still had outsource-only aggregate/CNC fit and old prices ($10.50 versus the live $10.32 CNC at qty 12,000). The save key covered form parameters but omitted external inventory, governed rate and calibration effects.

The common `persist_cost_decision` funnel now fingerprints the canonical computed report together with its input hash and engine version. This covers both the interactive route and batch worker without separate patch logic. JSON quantity keys normalize before sorting; unchanged reruns deduplicate. Historical parameter-only records stay immutable; the first run under the new identity creates a new snapshot rather than rewriting an old record.

A real-Postgres regression failed before the fix (changed evidence reused the same row) and passes after it: changed machine fit and changed price/confidence create distinct rows, original evidence remains unchanged, and an identical JSONB-round-tripped result reuses its row. Native re-upload created `01M3RD0TQ9ZHKYN4VS147DMSY7`; database readback confirms new CNC fit/prices and unchanged historical JSON. Native repeated upload reuses that ID, and Part standing references its current record while correctly keeping the recommended EDM route outsource-only. Native JSON export `audit-cube-cost (13).json` matches every saved report field exactly (plus governance metadata). The CUA download-event wait timed out despite the browser successfully writing the file; HTTP 200 and the downloaded file confirm success.

Final validation: **2,395 backend tests passed**, three documented real-corpus/OCP-XDE skips; 76 focused persistence/batch/tenant checks passed. Pyright baseline 217/228 passes with no changed-service diagnostic; Bandit reports no issues in the changed service. The first full test attempt accidentally inherited production auth/storage settings (18 failures/3 setup errors); rerunning under the normal CI environment resolved all of them without changing product guards or tests. Frontend remains the validated 492-test/build result from 064–066. Evidence: `cost-snapshot-regression.json`, screenshots `067-*`, and the runnable real-PG test in `test_makeability_projection.py`.


## 068 — Verification notifications discard their source record

- Severity: medium navigation defect. Native Open on an existing NIST verification notification went to the full 33-record list without selecting its source. The notification service already stores and returns the exact cost-decision ID.
- Root cause: the shared frontend notification mapper drops `source_type`/`source_id`; the inbox builds only a screen-level link. The mapper now resolves a validated cost-record link, reused by the inbox and panel; other kinds and malformed source IDs retain the existing screen fallback.
- Verification: one exact-source/invalid-source regression fails before and passes after. Native link and opened detail both identify `01M3R5PQHVPT6BE584E0R6J1J8` and show the NIST filename. Dismiss survives reload, restore returns the item, and all 33 local audit notifications remain read after Mark all read/reload. Frontend 493 tests, types, changed-source lint, production build and notification runner contracts pass. The CI notification oracle now requires the exact source detail instead of accepting the generic Records page.
- Evidence: `notification-lifecycle-regression.json`, `068-notification-destination-before.png`, `068-notification-destination-fixed.png`, `068-notifications-read-persisted.png`. Native panel replay is not claimed; no panel caller is currently mounted. Not deployed.

017 recheck (2026-09-30): the three linked Debian trackers still report the production trixie package versions as vulnerable. No supported stable fix is listed; finding remains open. No package or scanner changes were made.


## 069 — Theme action leaves the button label and icon stale

- Severity: low accessibility/state defect. Native command-palette theme action switched the page to dark while the button still said `Switch to dark theme` and retained its light-mode icon.
- Fix: the shared theme button observes the existing root class, so either visible entry point updates its label/icon. Uses the platform MutationObserver with cleanup; no new theme provider or dependency.
- Verification: native assertion fails before, then passes for palette toggles in both directions, direct-button toggle and full reload. Original light preference restored. Types, changed-file lint and production build pass. Runnable check: `scripts/e2e/theme-state-validation.mjs`; evidence: `theme-state-regression.json` and 069 before/fixed screenshots. Not deployed.


## 070 — Closing the command palette loses keyboard focus

- Severity: medium accessibility defect. Opening the header search button and pressing Escape left `document.activeElement` on BODY. The controlled Radix dialog has no Dialog.Trigger to receive the default close focus.
- Fix: the shared palette retains the active element before its existing input-autofocus handler, then restores that connected element on close. Header, sidebar and keyboard-shortcut entry points use the same path.
- Verification: native focus assertion fails before and passes after for header click/Escape, sidebar Enter/Escape, and Meta+K from the theme button/Escape. Uppercase `COST HISTORY` + Enter opens `/cost-decisions` with heading `Cost history`; a missing command gives an explicit empty result. Frontend 493 tests, types, changed-source lint and build pass. Evidence: `command-focus-regression.json`, runnable `scripts/e2e/command-focus-validation.mjs`, 070 screenshots. Not deployed.


## 071 — Noncircular openings and tapers receive invented cylinder dimensions

- Severity: high result-accuracy issue. A real STEP block with a 12×6 mm elliptical opening displayed `cylinder_hole`, radius 4.39 mm, 100% confidence and sheet-metal advice based on a nonexistent 8.8 mm diameter. A circular taper from radius 10 to 8 over 20 mm was reported as a constant-radius cylinder. Native ellipse reproduction and independent STEP geometry controls agree.
- Root cause: normal-axis alignment establishes an extrusion direction, but cannot establish a constant circular cross-section. The detector averaged distances from triangle centroids without validating the shape.
- Fix: reuse the existing fillet Kasa circle fit in a shared cylinder-section helper, fitting actual vertices and validating radial residual. Noncircular candidates remain curved without an invented radius. A separately validated linear circular taper retains positive turning evidence, so correcting the label does not falsely reject a cone from turning. Analysis/cache version advances to 0.3.10. Historical evidence is retained.
- Native verification: the identical elliptical STEP bytes no longer produce the radius or 8.8 mm advice; dimensions remain 20×20×10 mm. The cone has two flats plus one curved surface and retains rotational routing/turning eligibility (Advisory 90%, no required blocker). The original round-bore STEP still has six flats, a 3.00 mm radius/10.00 mm depth and 20×15×10 mm dimensions.
- Independent controls: sphere, taper and elliptical STEP volumes differ from analytic truth by 0.01102%, 0.00458% and 0.00290%, respectively. Rotated coarse/fine circle/ellipse/taper checks fail before and pass after. Full backend: 2,397 pass, three documented skips; all 66 reference prices and line items unchanged; type baseline 217/228 with no new changed-file diagnostics; Bandit zero findings.
- Evidence: `circular-feature-regression.json`, `known-shape-accuracy.py`, the synthetic STEP files in `shape-controls/`, and 071 screenshots. Radius-fit tolerance is 2% RMS to accommodate tessellation; arbitrary opening-width coverage and spherical turning eligibility are not certified by this fix. Not deployed.


## 072 — A true sphere is rejected as nonrotational

- Severity: high result-accuracy issue. Native upload of the existing radius-10 spherical STEP showed `rotational: no`, CNC Turning Required/0%, and `NOT_ROTATIONALLY_SYMMETRIC` despite both inertia ratios being 1.00. A sphere is axially symmetric; lacking a cylindrical patch is not evidence against that geometry.
- Root cause: the shared positive-surface predicate only accepted circular cylinders and conical patches. Both DFM and cost routing inherited the same false rejection.
- Fix: the same shared predicate now accepts a valid closed spherical mesh when every vertex and triangle centroid lies within 2% radial tolerance about its mass center. Checking face interiors prevents a cube, whose vertices also lie on a sphere, from passing. No new dependency or feature enum; engine/cache version 0.3.11.
- Native verification: identical STEP bytes now show rotational routing and CNC Turning Pass/100%, with the false symmetry blocker absent. The model remains 20×20×20 mm, 4.2 cm³. The process score is the existing rule score, not proof of tooling, workholding or manufacturing yield.
- Validation: one parameterized regression fails before and passes after at two tessellation densities after rotation/translation; routing and DFM agree. Cube, triaxial ellipsoid, open-shell and inverted-mesh controls remain rejected. All 25 focused checks and 2,399 backend tests pass, with three documented local corpus/OCP-XDE skips. Three real STEP analytic controls pass; all 77 local reference estimates and line items are unchanged. Pyright 216/228 baseline, no new changed-file diagnostics; Bandit has no medium/high findings (two preexisting lows in checks.py).
- Evidence: `spherical-turning-regression.json`, the existing STEP fixture and extended `known-shape-accuracy.py`, plus 072 before/fixed screenshots. Scope is complete spheres within the explicit tessellation tolerance; general curved solids of revolution and empirical quote accuracy still need independent coverage. Not deployed.


## 073 — Worker hash randomization creates duplicate saved decisions

- Severity: high evidence-integrity regression introduced by complete-snapshot dedup (067). CI 36677043750 passed eight jobs but failed VER-08: unchanged repeated STEP verification created a third saved record instead of retaining the existing stainless decision. Later CAD/training suites were not reached.
- First divergence: independent real-STEP runs under Python hash seeds 1 and 2 produced different `estimates` array order. Every keyed estimate object and all other report fields were identical. `eligible_processes` iterated the `COSTED_PROCESSES` set, so separate workers produced different snapshot hashes despite identical evidence.
- Fix: sort the existing process set by its stable value where the shared shortlist is built. This makes every consumer's report order deterministic while retaining full-content snapshot identity and the separate record required for changed inputs/evidence. Engine/cache version 0.3.12; no dedup or CI assertion was weakened.
- Verification: a subprocess regression using two hash seeds fails before and passes after. Full real-STEP reports now match exactly across both seeds, and all 77 estimate objects are unchanged from both pre-fix runs. Native Chrome upload under API seed 1, Open in history, API restart under seed 2, identical re-upload and Open in history all select the same record `01M3RGVP9JGHDNP6RG30WH24NW`.
- Evidence: `snapshot-order-regression.json`, `ci-36677043750-summary.json` and 073 native receipts. Local full backend: 2,400 passed/three documented skips; focused persistence/cost checks: 55 passed; Pyright 216/228 baseline; changed-source Bandit zero findings. Full-suite/current-head CI and production status are recorded in the ledger. Not deployed.


## 074 — Existing users cannot change their password in Security

- Severity: high account-workflow defect. first divergence: step 1, expected Security's promised password-change flow to accept current-password verification, state was an initialization-only endpoint that always returned `password_already_set` for existing accounts. Native UI had no current-password field and labeled the operation Initial password. The real-PostgreSQL regression fails before and passes after.
- Fix: extend the existing endpoint with optional current-password proof. Existing credentials are verified with Argon2; the shared model helper compare-and-sets the exact verified hash and commits the new hash, session-version increment and audit entry together. Initial setup still requires an absent password, and stale concurrent updates are refused. Reuses existing rate limits, signed auth proxy, cookie rotation and password policy. Authenticated account state now exposes only `has_password`; the Security form shows the correct initial/change flow.
- Security evidence: wrong/missing current password and weak replacements cannot change state. Old password/session fail after a successful change; the returned session and new password work. Exactly one change audit event persists; a stale-hash write fails without disturbing the new session. Both password fields are scrubbed from telemetry. Frontend auth responses keep the rotated token in an HttpOnly/Secure/SameSite=Lax cookie and return only `ok` to browser JavaScript.
- Verification: 61 focused auth/session/scrub/frontend-contract checks; full backend 2,400 pass/three documented local corpus/OCP-XDE skips; frontend 494 tests, types, changed-source lint and production build pass. Pyright 216/228 baseline with no new changed-file diagnostics; Bandit no medium/high findings. An isolated HTTP fixture through running Next → API → PostgreSQL proves change/login/session lifecycle and is removed afterward.
- Native evidence: Chrome renders Change password with current/new/confirmation fields, password input types, correct autocomplete and 128-character limits; empty submit focuses required Current password. No credential was entered and the browser audit-account password was not changed. Native credential submission requires user handoff under browser-use policy, and production verification remains pending.
- Evidence: `password-change-regression.json`, `password-change-http-proof.json`, 074 before/fixed screenshots. Email delivery/recovery and real company IdP sign-in remain unverified separately. Not deployed.


## 075 — Valid Unicode passwords are rejected by signup and Security

- Severity: medium account-workflow defect. first divergence: step 1, expected a server-valid Unicode password to reach the auth endpoint, state was a client-only “missing letter/digit” or length error. Executing the original frontend helpers proves the rejection for accented letters, non-ASCII digits and a 128-code-point value containing an astral letter. The backend accepts these controls.
- Root cause: duplicated ASCII regexes and JavaScript/HTML UTF-16 length disagree with the backend's Unicode policy. Remove both duplicate policy helpers; keep required fields and confirmation matching. The server remains authoritative for the unchanged 8–128-code-point, letter-and-digit rule. Inputs allow at most 256 UTF-16 units so every valid 128-code-point value can be entered. Security reuses the existing auth error mapper, including FastAPI validation arrays.
- Verification: five existing backend policy checks and the auth error regression pass; all 494 frontend tests, types, changed-file lint and production build pass. Backend production code is unchanged from 074's 2,400-pass full suite. Running Next → API → PostgreSQL accepts a 128-code-point signup, verifies a change to a non-ASCII-digit password, rejects 129 code points and weak/missing/wrong-current inputs, rotates the cookie, rejects old credentials/session and accepts new ones. The isolated fixture is removed afterward.
- Native evidence: signup and Security render required password inputs with correct autocomplete and 256-unit bounds. Signup states the server's 8–128-character policy. No credential is entered or changed through the browser. Evidence: `password-unicode-regression.json`, `password-unicode-http-proof.json`, `075-unicode-password-signup.png`. Not deployed; native credential handoff and production verification remain pending.


## 076 — Success is sent before the database transaction commits

- Severity: high persistence-integrity defect. first divergence: step 18, expected the cost-decision ID returned by upload to be immediately readable, state was HTTP 404 in CI 36680024807's role/failure journey. The preceding enterprise suite passed all nine goldens, including VER-08, confirming 073. Later CAD/training suites were not reached.
- Confirmed shared defect: the request-scoped `get_db_session` yield dependency commits after HTTP response transmission. A deterministic ASGI regression observes `write → status:200 → stream → commit`; a failed commit also sends 200 before rollback. CI did not retain the database commit trace, so attribution of that specific 404 to this reproduced race remains inferred pending a fresh run.
- Fix: use FastAPI's function scope for the transaction and request scope for session cleanup. Commit/rollback finishes before headers; the same session remains open for batch CSV's streaming reads and always closes afterward. All existing callers use the shared corrected boundary. Minimum FastAPI input is 0.121; the already pinned 0.141.1 production lock recompiles unchanged. No polling/retry, weakened read assertion or timeout increase.
- Verification: the two failing response-order cases now pass, together with handler-error rollback and streaming-session lifetime. 64 focused checks and the full 2,403 backend tests pass with three documented corpus/OCP-XDE skips. Pyright remains 216/228 with no new changed-file diagnostics; Bandit zero findings. Frontend is unchanged from 075's 494 passing checks/types/lint/build.
- Running Next → API → PostgreSQL: four real STEP uploads are immediately readable with exact persisted estimate arrays; approve/read and reopen/read all agree. Isolated fixture user/org removed afterward. Native real STEP upload → Open in history opens `01M3RK0AGB5F4G386CMJM2AT29` with the exact source SHA and Unreviewed governance.
- Evidence: `db-response-transaction-regression.json`, `db-response-http-proof.json`, `ci-36680024807-summary.json`, `076-saved-step-ready.png`. Exact-head CI and production verification remain pending; not deployed. Framework lifecycle reference: [FastAPI yield dependency scopes](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope).


## 077 — Approval appears to cover an unsaved outcome note

- Severity: high evidence-integrity UI defect. first divergence: step 3, expected approval to apply to the displayed outcome note, state was an Approved badge/signoff beside unsaved revised text. Reload restored the older persisted note while retaining approval. Reproduced natively on real STEP record `01M3RK0AGB5F4G386CMJM2AT29`.
- Root cause: the detail page already tracks a dirty outcome note but neither guards nor disables Approve with it. The same panel gives no draft warning, making the displayed rationale appear signed off.
- Fix: reuse that existing dirty state to block approval until the note is saved. Announce unsaved text and explicitly distinguish an existing approval as applying to the saved note. No backend contract, audit history, estimate or role boundary changes.
- Verification: the shared native browser assertion fails before and passes after. Save enables approval; the exact revised note survives approval/reload. Editing an approved note shows the saved-note warning; saving it reopens approval. Reverting a draft to the persisted text also enables approval. The local QA outcome is withdrawn afterward, returning the record to its original unreviewed state. All 494 frontend tests, types, changed-file lint and production build pass.
- The existing P7 CI governance journey now exercises the same guard and checks persisted note equality before approval. Evidence: `approval-draft-regression.json`, runnable `scripts/e2e/cost-governance-draft-validation.mjs` and 077 screenshots. Local fix only; CI and production verification pending. Concurrent multi-user approval semantics remain outside this specific proof.


## 078 — Saved histories cannot be opened by keyboard and empty filters imply lost records

- Severity: medium accessibility and navigation defect. Native History had 28 saved analyses, but selecting Required showed “No analyses yet” and instructed another upload. Four Advisory rows had no focusable link/control; Tab after the last header skipped all records. The same click-only filename/ID cells occur in cost history and batch history. Catalog already has an accessible button and batch items already expose links.
- Fix: replace those three filename/ID spans with native Next links, retaining row-click shortcuts and normal copy/open-link behavior. The filter now has an accessible name; a filtered empty result says no analyses match and offers Clear filter. The genuinely empty unfiltered history retains its upload action.
- Verification: the shared browser assertion fails before and passes after. Native Tab then Enter opens the exact saved analysis, cost decision and batch. Required's empty state and keyboard Clear filter recover the records. Advisory returns four matching records; Load more expands 20 to 28 unique records without changing the first ID; numeric Faces sorting is correct. All 494 frontend tests, types, changed-file lint and production build pass.
- Evidence: `history-controls-regression.json`, 078 screenshots and runnable `scripts/e2e/history-link-validation.mjs`. The existing P7 governance journey now opens its saved fixture from cost history with the same keyboard check. Fresh CI and production verification remain pending; delayed-response filter races are not covered by this proof. Not deployed.


## 079 — Human CI misclassifies the expected weak-password HTTP rejection

- Severity: medium verification defect. CI36683496521 passed eight jobs and all 54 human UI steps, including weak-password rejection, valid signup and logout/login. Its final console gate nevertheless failed on one HTTP400 resource message at signup, stopping before Design Studio, enterprise, P7 and CAD suites. The intentional weak-password request now reaches the authoritative backend after075; the old client-only policy produced no network rejection.
- Fix: consolidate the duplicated negative test and require its exact HTTP400, `weak_password` code, policy message and matching visible feedback. Capture console resource URLs and classify at most one exact HTTP400 resource message from that request's observation window after those assertions pass. Retain it in `expectedConsoleErrors` evidence. Unrelated resource errors, other statuses, duplicate messages and runtime exceptions still fail the existing gate.
- Verification: running Next→API returns the exact400/code/message with no account created. Six release-evidence tests pass, including wrong status/code/body/endpoint and runtime-error controls; runner syntax and diff checks pass. No production source changes in079, no policy/status changes, no timeout increase and no local browser-runner execution.
- Evidence: `ci-36683496521-summary.json`. The original artifact lacks the resource URL/body, so the next CI must capture those and complete the later chain;076's P7 proof and077/078 also remain pending.


## 080 — Developer quickstart points to the wrong response and loops its reference link

- Severity: medium developer-workflow and disclosure defect. Native Full API reference navigated through `/docs` back to the same `/developers` page. The curl sample called DFM-only `/validate` while promising cost, and both displayed cost snippets placed per-estimate price/driver/confidence fields at the response root. The interactive cost operation additionally claimed that source CAD was never retained, contrary to its existing storage flow.
- Fix: link directly through the existing `/scalar` runtime redirect to the actual API console. The sample now uses `/validate/cost` and `qty=50,5000`, places cost fields in `estimates[]`, and labels example values as selected, part/quantity/rate-dependent fields. Describe `/validate` separately for the full DFM report. The published endpoint description now states source CAD and costable mesh retention in organization-scoped storage; its unit warning identifies25.4³ as a volume ratio rather than a guaranteed price ratio.
- Verification: native Enter on the fixed link opens `http://127.0.0.1:8017/docs`, and the expanded cost operation shows file/qty and corrected retention text. Native export of real STEP record `01M3RK0AGB5F4G386CMJM2AT29` contains report routing and16 estimates at50/5000; every price, confidence, driver and DFM field is nested correctly and every line-item sum reconciles. Frontend494 tests/types/lint/build and Python compile pass; running OpenAPI confirms the descriptions and parameter schema.
- Limits: a fresh isolated HTTP test account was rate-limited429 before creation, so no new complete curl execution is claimed. The recorded schema proof comes from the existing native real-STEP export, source and OpenAPI. Production and customer quote accuracy remain pending. Evidence: `developer-docs-regression.json` and080 screenshots. Not deployed; no engine or security behavior changes.


## 081 — Compressed API responses are truncated by the dashboard proxy

- Severity: high shared transport defect. A read-only local proxy returned the real API's valid gzip history response with its correct1214-byte Content-Length. Server fetch decoded the body while retaining that header. The dashboard relayed the compressed byte count without Content-Encoding, so native History failed JSON parsing at position1214 and displayed no records.
- Fix: omit upstream Content-Length only when Content-Encoding is present. Unencoded download lengths, content disposition, status, quota and evidence headers are retained; streaming is preserved. All dashboard API callers use this boundary. The public-share proxy already omits content length and needs no change.
- Verification: the existing runnable native history check fails before and passes after through the same real gzip response, returning20 rows. A native real-STEP JSON export through the corrected compressed path exactly matches the earlier direct report and all16 estimates. Frontend494 tests/types/lint/build pass. No new library or buffering is introduced.
- Evidence: `compressed-proxy-regression.json`, `history-delay-proxy.py` (local read-only reproduction fixture), shared `scripts/e2e/history-link-validation.mjs` and081 screenshots. Production/CDN replay and additional encodings/binary downloads remain pending. Not deployed; no assertion that this caused an earlier production outage.


## 082 — A late history response overwrites the newly selected verdict

- Severity: medium correctness defect. With the real Advisory response held for four seconds, selecting Advisory then Required leaves the Required control beside four Advisory records. The original loading/initialized gate never starts the new filter request; the old response writes data and marks the new selection initialized.
- Fix: fetch the first page whenever the filter callback changes, independent of the previous loading flag. A component-local request sequence invalidates old results, errors and completion flags at filter changes, newer requests and cleanup. Pagination and retry use the same path; no new library, server change or polling.
- Verification: `assertHistoryVerdict` fails before and passes after the same native delayed-response replay. Required stays correctly empty after the old Advisory response completes. Selecting Advisory still returns its four records; All verdicts and Load more retain20→28 unique records. All494 frontend tests, types, changed-file lint and production build pass. The temporary read-only delay proxy is stopped afterward and the original direct API connection restored.
- Evidence: `history-race-regression.json`,082 native screenshots and the shared runnable browser check in `scripts/e2e/history-link-validation.mjs`, with `history-delay-proxy.py` as the real-response delay fixture. Delayed failure responses, fresh CI and production remain pending. Not deployed.

## 083 — Triage part links discard the selected part

- Severity: medium. Native Triage → Makeable outside → NIST row opened the unfiltered seven-part catalog even though the drill-down promises each row opens its verdict. The exact-part regression failed.
- Root cause: the shared `PartRow` used only `nav("catalog")`, dropping its existing `part_key`. Both bucket and capability-unlock rows use this component.
- Fix: reuse the catalog's existing `setSelectedPart` handoff and navigate to the existing part standing. The control now says Open part standing. No new route, dependency or selection store.
- Verification: native keyboard opening shows the exact NIST STEP identity, saved WAAM verdict and history. Selecting a subsequent Evaluation required row opens `repaired-block.stl`, with its DFM-only/cost-required state intact. The same runnable check fails before and passes for both after. Frontend494 tests, types, changed-file lint, production build and syntax checks pass.
- Evidence: `triage-navigation-regression.json`,083 screenshots and `scripts/e2e/triage-navigation-validation.mjs`. Not deployed. Native capability-unlock and large-catalog selection remain unverified; the existing standing page reads only its first100 catalog rows and requires a separate follow-up.

## 084 — Part standing silently substitutes another CAD file beyond the first page

- Severity: high correctness. Part standing read only100 catalog rows; if its explicit selected key was absent, it silently chose the newest part. A read-only proxy requesting a real one-row catalog page reproduced NIST STEP → `audit-cube.STP`, including the wrong20×15×10mm dimensions and$3.80 price. No response payload or CAD record was fabricated.
- Root cause: selection was treated as an optional preference inside the first page, rather than a required identity.
- Fix: the existing catalog endpoint accepts a bounded exact `part_key`. The existing org-scoped fold filters both analysis/cost queries before limiting each to its latest record, bypassing the unrelated full-catalog scan cap. Existing callers remain unchanged. Part standing fetches this exact identity when absent from page one and shows a recoverable unavailable state instead of another part; a lookup failure no longer also claims the whole catalog is empty.
- Verification: real PostgreSQL regression fails before and passes after, including lookup with scan cap1, exact original rows, unknown/foreign-tenant empty results, bounded keys and conflicting keyset rejection.35 focused backend checks pass; full backend2403 pass/three documented local corpus/OCP-XDE skips, frontend494/types/lint/build pass, backend type baseline216/228 with no new changed-file diagnostics, Bandit no medium/high findings.
- Native same-control after: selected NIST identity,311.60×135.90×222.70mm dimensions and saved$909.7 WAAM cost match. Controlled missing lookup returns the explicit unavailable message, with no substituted standing or false empty-catalog claim; Return to Parts works. Original direct API connection restored.
- Evidence: `catalog-selection-regression.json`,084 screenshots, `catalog-first-page-proxy.py`, existing catalog API test and updated `triage-navigation-validation.mjs`. Local-only; fresh CI/deployment and large-scale concurrency remain pending. No cost-engine version change: stored/priced values are unchanged.

## 085 — Part history mixes different geometry with the same filename

- Severity: high correctness issue; unrelated cost decisions appeared in a part's evidence history.
- first divergence: step3, expected the 20×15×10mm block's standing to contain only that part's decisions, state was the newly uploaded 20mm sphere's saved decision at the top because both files were named `audit-cube.STP`.
- Native reproduction: copy the real `sphere-r10.step` control to that basename, cost it at63/5000, open the existing block's standing, then expand the newest history item. The block showed the sphere's4,660 crossover and$4.22 saved estimate. The current block verdict itself remained$3.80; the mixed history was the defect.
- Root cause: the screen fetched the first100 organization decisions and filtered by filename. This also excluded genuine renamed uploads, silently omitted older records, and treated read failures as empty history.
- Fix: the existing authenticated list route filters exact `mesh_hash` before cursor pagination and returns it in private summaries. The history card requests20 records per page, checks every returned identity, includes renamed uploads, exposes older pages, and distinguishes empty, loading and recoverable error states. The filename grouping helper and its incorrect-behavior test were removed. Public share payloads are unchanged; no migration or engine-version change.
- Native verification: all27 block decisions match PostgreSQL exactly across20+7 pages, including four historical filenames; all4 sphere decisions match across two filenames. No cross-part rows or duplicate IDs. An actual local API outage displays an error without a false empty state; Retry restores the exact4 sphere rows. A DFM-only STL shows an actual empty cost history.
- Checks: the real-PostgreSQL identity/pagination/tenant test failed before the fix and passes after it;47 focused backend tests,493 frontend tests, typecheck, changed-file lint and production build pass. Full backend:2403 passed,3 documented corpus/OCP-XDE skips; type baseline216/228 with no new changed-file diagnostics; Bandit reports no findings in changed sources. Evidence: `part-history-identity-regression.json`,085 screenshots and runnable `scripts/e2e/part-history-validation.mjs`. Not deployed.

## 086 — Compare mistakes filename matches for the same CAD input

- Severity: high interpretation error.
- first divergence: step2, expected Compare from the sphere standing to prefer its previous saved decision, state was the unrelated block selected as B because its filename matched. The screen claimed “Same part” and “Calibration vs calibration” while showing a geometry-driven17.5% price difference.
- Root cause: the initial comparison partner used filename equality; static copy claimed same-part calibration and dismissed every other driver as noise without measuring that claim.
- Fix: prefer the existing summary's stored CAD identity, use decision-comparison wording, explicitly identify differing CAD inputs, and describe the largest relative driver difference without dismissing other changes. Users can still deliberately compare different parts. No costs, bands, backend results or acceptance tolerances changed.
- Native RED→GREEN: sphere record `01M3RR348KARFPN58EASHH8ZVD` now defaults to its prior sphere record `01M3RGVP9JGHDNP6RG30WH24NW`, despite different filenames. Deliberately selecting block `01M3RK0AGB5F4G386CMJM2AT29` displays the differing-input notice. Both Injection Molding prices keep their “requires redesign” labels.
- Validation:493 frontend tests, typecheck, changed-file lint and production build pass; existing native comparison checks now cover the identity pair and differing-input message. Evidence: `comparison-identity-regression.json` and086 screenshots. Local only; production and comparison records outside the100-record picker remain open.

CI checkpoint: [36690028303](https://github.com/zandemha2025/cadverify/actions/runs/36690028303) completed successfully on `89ea94d` through083: all9 jobs,54 human steps,31 role/governance steps,34 real CAD cases and the full restore/load/readiness/training chain passed. This run excludes084–086. Sanitized receipt: `ci-36690028303-summary.json`; no new production deployment.

## 087 — Comparison pickers omit older saved decisions

- Severity: medium navigation/correctness defect. Both comparison screens discarded `next_cursor` after100 records. A selected NIST record outside the first page opened with blank A/B and instructed the user to choose another recent record.
- Fix: retain the existing cursor and provide Load older records on both screens. Verify retrieves the exact selected record through the existing owned-detail endpoint and finds a same-CAD partner through the existing identity filter. Deduplicate those pinned records when subsequent pages reach them. Read failures retain loaded choices; initial failures and missing selected records offer Retry. Timestamp and short record ID distinguish repeated filenames; constrained flex children keep the longer labels inside the viewport.
- Native RED→GREEN: a read-only loopback proxy reduces actual API pages to2 without fabricating bodies. Both screens reach all42 PostgreSQL decisions over20 additional pages; Verify retains exact NIST A/B and has no duplicate options. Missing selected-record404 gives an explicit recoverable error, then Retry restores the same pair. A real transport outage retains4 choices; Verify paging retry adds the next2. Standalone first-page404 Retry restores both real choices.
- Repeated pagination exhausted the local account's60/hour route limit; the UI accurately showed429. Remaining recovery checks used the existing local test switch with RELEASE unset. Production configuration was untouched. The temporary proxy is stopped and the frontend again calls the real local API directly.
- Validation:493 frontend tests, typecheck, changed-file lint and production build pass. Final native direct-API picker exposes42 distinct options; desktop1280 and mobile390/320 have no document/control overflow. Evidence: `comparison-pagination-selection-regression.json`,087 screenshots and shared runnable `scripts/e2e/compare-route-validation.mjs`. Not deployed; currentCI36694513963 runs priorc02604f.

## 088 — Changed comparison selections retain the previous pair's prices

- Severity: high result-integrity defect. Native standalone Compare A/B changed B from NIST recordR6J1J8 toX10PA4 while the old price table stayed visible under the new selector. The shared no-stale-result assertion failed.
- Fix: clear the stored comparison and its error whenever either selection changes. Disable both selectors during the existing comparison request, preventing a late response from appearing under a different pair. The existing Compare loading control already prevents duplicate requests; no new state abstraction or dependency.
- Native RED→GREEN: changing A and changing B each remove the previous table; Compare produces the newly selected sphere pair with$4.22/$4.22 and no change at5,000. A two-second real-request delay proves both pickers remain disabled while comparison runs.493 frontend tests, typecheck, lint and build pass.
- Evidence: `comparison-pagination-selection-regression.json`,088 before/after screenshots and shared runnable comparison checks. Not deployed; no change to backend cost calculations or accuracy tolerances.

## 089 — Authentication-service outage masquerades as a signed-out session

- Severity: medium availability/recovery defect; **fixed locally, not deployed**. first divergence: step2, expected an unavailable-verification state on protected-page reload, state was a redirect to ordinary login despite the existing valid session. Restoring the API reopened the page with the same session, without entering credentials.
- Root cause confirmed in `frontend/src/lib/dal.ts`: `getUser()` returns null for every non-OK response and every fetch failure; `verifySession()` treats every null as missing/invalid authentication. A backend outage is therefore indistinguishable from a real401.
- Fix: the shared gate returns null only for missing cookies or actual401/403 rejection. Other statuses, transport/timeout failures and malformed successful payloads throw to the existing Next retry boundary, withholding the protected shell and preserving the URL. Verification uses the existing auth routes'55-second deadline. The root error screen gives a temporary-unavailability explanation and Try again; it no longer claims a team notification was received. All callers were checked, including both authenticated layouts, Organization and Security.
- Native RED→GREEN: stopped real API previously redirected comparison to login; it now remains at `/cost-decisions/compare` with recovery controls and no protected shell. Restore API → Try again opens both real decision selectors without credentials. The same outage/retry cycle passes for the separate `/verify` layout, including loaded workspace data after recovery.
- Verification: the runnable DAL regression fails before on429→login and passes after for missing/401/403/429/404/5xx/network/timeout/malformed/valid responses. Six public HTTP checks confirm missing and invalid sessions still redirect safely with exact return paths on Compare, Verify and Security.494 frontend tests, types, changed-file lint and production build pass. Existing local QA rate-limit settings remain documented; no production configuration changes.
- Evidence: `session-recovery-regression.json`, `session-recovery-http-proof.json`,089 screenshots, `frontend/src/lib/dal.test.ts` and `scripts/e2e/session-recovery-validation.mjs`. Fresh CI and deployment remain required; real external authentication providers and email remain unverified.

CI checkpoint: [36694513963](https://github.com/zandemha2025/cadverify/actions/runs/36694513963) completed successfully on `c02604f` through086: all9 jobs,54 human steps,15 Design Studio steps/12 goldens,17 enterprise steps/9 goldens,31 role/governance steps with zero skips, all34 real CAD cases and the full restore/load/readiness/training chain passed. Sanitized receipt: `ci-36694513963-summary.json`. It excludes087–089 and does not prove production or the main-only image CVE gate.


## 090 — Editing a fit pair leaves measurement permanently pending

- Severity: medium availability defect; fixed locally, not deployed. A real successful cube-pair response was delayed four seconds. Changing X during the request left “Measuring this pair…” disabled after HTTP200 completed; the runnable native assertion failed.
- Root cause: the shared `clearStale` invalidated the request ID but retained `running=true`, while the stale request's guarded finally could no longer clear it. One added state reset repairs all input paths without accepting old measurements.
- Native GREEN: X, seating, swap and file-replacement controls each permit a fresh check and withhold the old successful result. Real10mm cubes produce10mm clearance at20mm translation,1000mm³ full overlap, and10mm³ overlap at9.9mm translation. Open-shell refusal recovers after selecting valid CAD. Assembly visibility toggles; native foreground screenshot shows actual collision geometry.
- 494 frontend tests, typecheck, changed-file lint and production build pass. Runnable checks: `scripts/e2e/context-fit-validation.mjs`; evidence: `context-fit-pending-regression.json` and090 screenshots. The response-control proxy is stopped and the frontend again calls API8017 directly. Local QA explicitly enables the previously unset context-fit flag; production enablement is unverified. No STEP fit success is claimed (091).

## 091 — Ordinary STEP pair exceeds fit admission and receives contradictory recovery advice

- Severity: high feature limitation; fixed locally, verified and not deployed. Native two-file upload of the existing20×15×10mm bored `audit-cube.STP` produces370656 parsed faces, above the150000 pair limit. The canonical parser creates185328 faces per file; the customer has no tessellation control in this form.
- The UI accepts STEP and says pair measurement supports it, but this real pair cannot be checked with defaults. The backend adds “Repair both shells to watertight solids and retry the same two files” after the face-budget message, even though these are valid watertight solids and resubmitting the same files cannot help.
- Fix: only over-budget collision inputs reuse installed Manifold with double precision and `simplify(0)` at its native numerical tolerance. Recheck the unchanged effective-face cap before intersection; irreducible curved inputs still refuse. Original meshes continue to drive sampled clearance and all face locators. The result discloses redundant-triangle removal. Kernel failures withhold measurements, and supplementary OBJ/3MF files now obey the existing upload triangle cap. Remove blanket “repairable”/shell-repair advice from unrelated failures.
- Kernel probe: each185328-face STEP becomes24804 faces at2e-11mm native tolerance in0.021s; volume changes only at floating-point roundoff. Native real STEP pair now reports10.000mm gap at30mm X translation and2717.327mm³ full overlap at0mm, matching the submitted mesh. The mesh itself differs from the analytic bored solid by0.002581%; this remains a mesh-level check, with sampled-clearance limitations visible. Gap processing took18.8s locally; full overlap2.7s.
- Dense planar cube regression fails before on6144 faces over1000 and passes after for overlap, gap, source immutability and original face locators. Curved over-budget refusal and API advice/upload limits remain covered. Type baseline216/228 with zero new changed-source diagnostics; Bandit has no medium/high findings. Full backend verification passes2405 tests with3 documented allowlisted skips (173.33s). The initial run incorrectly inherited application runtime overrides; final run uses the repository CI environment with real PostgreSQL/Redis.
- Evidence: `context-fit-step-regression.json`, `091-context-fit-step-limit.png` and091 fixed STEP gap/overlap screenshots. Two-shell previews still explicitly require STL; production context-fit enablement and release proof remain open.


## 092 — STEP fit measurements had no two-shell preview and the fixed camera cropped geometry

- Severity: medium feature gap; fixed locally, not deployed. first divergence: step2, expected the selected STEP pair to render, state was a message requiring STL and no canvas; the runnable native assertion failed. The fixed camera also cropped the10mm STL pair in a tall/narrow viewport.
- Reuse the existing authenticated preview-mesh client for STEP/IGES, preserving every GLTF node and each file's source frame. STL still loads locally. Apply the same solid/ghost materials and measured context transform, without individually centering either shell. Cancel/revoke previous asynchronous loads and withhold sources that do not match the currently selected File objects. Existing Drei Bounds fits/clips the current pair and observes viewport changes.
- Native GREEN: two actual bored STEP files render correctly with the measured10mm gap, including both holes. Mixed STEP/STL also renders and measures10mm; hide/show preserves measurements. The390px pair fits with no horizontal document overflow; native scrolling reaches both result cards and tapping clearance opens the10.000mm callout. No independent IGES native case is claimed yet; OBJ/3MF previews remain explicitly unsupported.
- Evidence:`context-fit-preview-regression.json`,092 screenshots and shared `assertFitPreview` in `scripts/e2e/context-fit-validation.mjs`.494 frontend tests/types/lint/build pass; geometry/service calculations are unchanged from091.

## 093 — Malformed preview geometry crashes the entire Verify workspace

- Severity: medium recovery defect; fixed locally, not deployed. first divergence: step2, expected bad-file feedback beside the retained pair, state was the root “Page temporarily unavailable” screen after loading a20-byte malformedSTL. The input-readiness assertion failed because the entire panel vanished.
- A local React error boundary now contains renderer failures and resets for newly loaded files. HTTP preview failures retain the selected files and offer Retry preview. WebGL-unavailable copy no longer claims measurements have completed before a check occurs.
- Native GREEN: the same malformedSTL leaves the panel and file selectors available; Check fit reports the real backend minimum84-byte error without measurements. Replacing it with STEP restores real rendering and a10mm gap against the retained STL context. Stopping the real API produces Retry preview; restoring it and clicking Retry restores the same two STEP files without re-upload or credentials.
- Evidence:093 screenshots, controlled `malformed-fit.stl`, and existing native readiness/preview/gap assertions.494 frontend tests/types/lint/build pass. No production deployment.

CI checkpoint: [36698927295](https://github.com/zandemha2025/cadverify/actions/runs/36698927295) completed successfully on `a6f81fb` through089: all9 jobs passed, including the complete human/enterprise browser job. Sanitized receipt: `ci-36698927295-summary.json`. This run excludes090–093 and does not prove production, real external tenants or the main-only image CVE gate.


## 094 — A rejected import row aborts valid rows and misstates the outcome

- Severity: high data-integrity/availability defect; fixed locally, not deployed.
- first divergence: step1, expected the quantity outside PostgreSQL's integer range to fail dry-run validation, state was “passed,3/3 valid.” Importing that same file then returned HTTP500 and no import ledger row.
- Root cause: CSV integer parsing had no storage bound; both manifest and actual-cost bulk imports lacked per-row savepoints. A failed insert/update left the transaction unusable. The manifest handler also returned raw database exception text; run counts treated failed writes as valid and could show partial success when every write failed.
- Fix: retain valid manifest rows with database savepoints, include actuals delete-and-replace in the same per-row savepoint, report only safe row-rejection text for data/constraint errors, and let availability/schema failures abort. Count successful writes separately from normalized inputs. Reject manifest integers above2147483647 during parsing. All callers use the shared importers; no new dependency or schema.
- Native proof: `import-overflow.csv` now imports2 rows, skips1 and names line3's invalid quantity. PostgreSQL readback contains exactly the two valid declared parts at quantities2 and3. Real-database regressions also preserve the original row after a failed replacement and successfully process rows on both sides of the failure for both importers. Regression fixtures stay in transactions that roll back.
- Evidence: `import-integrity-regression.json`, `import-storage-readback.json`,094 screenshots and `backend/tests/test_import_failure_isolation.py`. Production and real vendor integrations remain open.

## 095 — Actual-cost validation accepts infinity and non-finite observed times

- Severity: high accuracy/data-integrity defect; fixed locally, not deployed.
- first divergence: step1, expected infinite price, NaN hours and an unstorable quantity to be rejected, state was “passed,4/4 valid” for the controlled quote/actuals CSV.
- Root cause: positive comparisons accept infinity and optional-hour comparisons accept NaN. The shared costing record lacked finite-value validation, and the actuals quantity could exceed the database integer range.
- Fix: enforce finite positive cost and finite nonnegative times in both the CSV parser and shared costing record, and validate the stored quantity before any ingest database work. Existing zero-hour values and the maximum representable quantity remain accepted; negative-cost errors retain their established wording.
- Native proof: dry-run now flags lines3–5; import saves only the valid12.5USD/10-unit/zero-hour record. Refresh and PostgreSQL readback reconcile with1 imported/3 skipped. The fixture explicitly uses `source_type=seed`, is stored as a stand-in, and cannot validate real quote accuracy. No invalid cost was deliberately imported before the fix.
- Evidence: `import-integrity-regression.json`,095 screenshots, storage readback and `backend/tests/test_groundtruth_numeric_boundary.py`. Real customer quotes, provider access and production retesting remain required.

Validation through094/095: full backend **2429 passed**, three documented local corpus/OCP-XDE skips in173.26s with the protected skip policy and real PostgreSQL/Redis. Type baseline216/228 passes with no new changed-source diagnostics; changed-source Bandit has no medium/high findings. Native PLM re-import also updates2 existing records without duplicates, a fully invalid file reportsfailed/0of1valid, and the mixed-file dry-run correctly reports2of3valid. Frontend code/build is unchanged from092/093. Exact new-head CI and production verification remain required.


## 096 — BOM rollups invent cyclic counts, truncate shared demand and crash on deep trees

first divergence: step 2, expected a circular BOM to have no valid root count, state was multiplier1 and the native Part standing displayed100/year as BOM ROLLUP. A shared-part regression with a bounded path preview returned6 instead of12; a1,500-level tree raised RecursionError.

- Severity: HIGH — incorrect annual demand can feed portfolio exposure and analysis quantities.
- Fix: validate quantities and cycles with stdlib topological ordering; calculate exact shared counts with dynamic programming independently of bounded ancestry previews. Iterative traversal handles deep trees. Counts outside the browser's exact integer range are withheld, and the existing declared/default fallback is retained.
- The Part screen now distinguishes BOM rollup from declared demand, explains missing annual production and count overflow, clears stale ancestry, and surfaces invalid/missing trees and read failures with Retry BOM.
- Native local proof on the real uploaded STEP's standing: legacy cycle error,12 units/vehicle and1,200/year for the controlled shared graph,12,000/year DECLARED when yearly production is missing, unsafe-count errors, annual overflow fallback, actual stopped-API error and successful retry. Controlled BOM linkage was restored and the temporary tree removed afterward. Saved cost records were unchanged.
- Evidence: `bom-integrity-regression.json`,096 screenshots, `test_bom_service.py` and the existing frontend BOM test. This validates hierarchy arithmetic and failure handling, not customer quote calibration or production deployment.

## 097 — Entirely invalid BOM replacement deletes the saved hierarchy

first divergence: step 2, expected a malformed replacement upload to preserve the existing8-handles-per-car BOM, state was HTTP200 with zero saved edges. The behavior-level real PostgreSQL test fails against cc4ee44 and passes with this fix.

- Severity: HIGH — a typo in an uploaded BOM header can erase the current hierarchy.
- Fix: the onboard route rejects uploads with no valid rows before replacement; the shared replacement service rejects cycles and invalid quantities before DELETE. JSON must contain a list, and declared counts must fit the integer storage boundary. Existing partial-valid row reporting remains intact.
- Real PostgreSQL proof: malformed headers, numeric JSON edges, empty edge lists, cycles and overflowing quantities all return422; after every rejection the original handle→door→car chain and multiplier8 are read back. Test transactions roll back their fixture data.
- Validation through096/097: **2433 backend tests passed**, three documented local corpus/OCP-XDE skips in176.28s; **495 frontend tests passed**, typecheck, lint (two existing unrelated warnings) and production build pass. Backend type baseline216/228 with no added diagnostics; changed-source Bandit has no medium/high findings. Not deployed.

CI36703805005 on bea9a77 completed with8 jobs passing and Browser E2E failing in the34-file corpus (33passed). FTC-07 emitted JSON ending in OK/PASS but its outer subprocess still exceeded90seconds. No timeout or acceptance gate has been relaxed. Its additional missing-data messages are symptoms; shutdown/output-collection root cause remains under investigation. The subsequent restore/load/readiness/training stages were not reached. See `ci-36703805005-summary.json`.


## 098 — Terminating a parser during result transfer can hang Python shutdown

first divergence: step 3, expected a killed parser sender to finish teardown and let the process exit, state was an executor manager blocked in `multiprocessing.connection._recv`, with interpreter shutdown waiting for that thread. A real spawn-pool reproduction prints its completed recycle marker but still exceeds the outer7-second deadline; the behavior-level regression times out after15seconds.

- Severity: HIGH — a timed-out parser can strand a worker-management thread and prevent clean restart/shutdown even after another result has completed.
- Root cause: the parent retains an unused sending end of the result pipe. Killing a child partway through a large pickle leaves the receiving thread expecting more bytes without an EOF.
- Fix: the existing shared hard-kill helper closes that parent sending end before killing the workers. Both shared-pool recycle and final shutdown reuse it, as do isolated retry/rung cancellations. Existing deadlines, native isolation and acceptance criteria are unchanged; partial results are rejected.
- Three real-subprocess regression modes now reject interrupted results, start a fresh pool, complete a task and exit. The isolated control improves from timeout to0.804seconds. Worker timeout diagnostics also remain armed through interpreter exit; a real delayed-thread regression proves a shutdown stack is retained after output.
- Real native replay: pinned NIST FTC-07 uploads with aluminum declared, renders and opens saved record `01M3S1TBH6VZTK11QYESVYEBTV`. Source hash matches; geometry is311.6×135.9×222.7mm,1726.0cm³,watertight,246354analysis faces. All60 stored estimates are finite and reconcile with their line items. Actual API shutdown after the parse completes in0.272seconds and the service is restarted. These are assumption-based estimates, not calibrated customer quotes.
- The native JSON button's download event timed out; this attempt is not counted as successful export proof. Stored numerical checks use the real database record independently. No browser-policy workaround was used.
- Validation:24 focused parser/corpus checks and2437 full backend tests pass, with three documented local skips; type baseline216/228 has no new diagnostics. Production parser Bandit has no medium/high findings. The diagnostic script retains one unchanged B310 on its pinned HTTPS/NIST-allowlisted downloader. Frontend unchanged from495 passing tests.
- Evidence: `098-parser-exit-regression.json`, `098-ftc07-record-check.json`, `098-api-shutdown.json`,098 native screenshots, and real subprocess tests. The historic CI failure's exact cause is still unproven because its stack was cancelled before interpreter exit; this fix closes a reproduced matching failure mechanism. Exact new-head CI and production retest remain required.

The standalone FTC-07 worker also exits successfully in16.183seconds with the fix. Geometry, decision, first estimate, estimate count and finite/sum checks exactly match the pre-fix d107cbe local replay; see `098-ftc07-worker-replay.json`.


## 099 — Geometric routing recommends incompatible or unevaluated processes

first divergence: step 2, expected an aluminum STEP report to recommend a material-compatible evaluated route, state was a geometry note recommending SLS and claiming CNC 3-axis was the tooling crossover, while the actual decision selected WAAM and the crossover was Die Casting.

- Severity: HIGH — the manufacturing explanation contradicted the declared material and its own calculated decision. The independent regression also promoted unevaluated CNC 5-axis; metal enclosure routing named polymer MJF.
- Root cause: geometric alternatives and DFM-clean fallbacks were not reconciled with material, geometry, evaluation or service-environment eligibility. The shared recommendation now uses those gates, removes incompatible alternatives and returns no recommendation when no eligible DFM-ready route exists. Metal enclosure and bulk archetypes use metal-compatible suggestions.
- Removed invented claims that every blocked part was designed for 3D printing and that a demoted process must be the actual tooling crossover. The empty routing UI asks users to review material, findings and notes instead of claiming a missing API feature. Engine/cache identity is0.3.13 so fresh reports do not reuse old routing semantics; historical saved evidence remains immutable.
- RED:5 new behavior cases failed (SLS on aluminum/steel/stainless, MJF metal enclosure, unevaluated route). GREEN covers those cases, all-failed routes and sour-service exclusion. Full backend2442 tests pass with3 documented local corpus/OCP-XDE skips;495 frontend tests, types, changed-file lint and production build pass. Backend type baseline216/228 has no new diagnostics; changed-source Bandit has no medium/high findings.
- Native real STEP replay: same NIST FTC-07 source SHA, aluminum selection and inputs create new saved record `01M3S2XNGHH6342NM253012Y2D`. Its notes name eligible CNC 5-axis and explain why the low-quantity cost pick is WAAM. Old record `01M3S1TBH6VZTK11QYESVYEBTV` remains unchanged. Database readback proves all60 estimates, geometry, decision, assumptions and feasibility exactly match the prior record; all amounts are finite and reconcile.
- Evidence: `099-routing-record-check.json`, `099-routing-before.png`, `099-routing-fixed.png`, and `test_routing_design_templates.py`. Prices remain assumption-based; no customer-quote calibration, production fix or deployment is claimed. Exact new-head CI remains pending.


## 100 — CAD preview is cropped and context covers the filename

first divergence: step 2, expected the real FTC-07 STEP and its filename/dimensions to be visible in the1280px workspace, state was cropped CAD and a context card covering the title. A native DOM layout assertion fails before the fix.

- Severity: MEDIUM — users cannot inspect the complete part or reliably read which CAD is displayed.
- Root cause: normalized geometry used a fixed perspective-camera distance regardless of panel aspect; title, context and controls occupied overlapping absolute layers.
- Fix: reuse the installed Drei Bounds component to fit and clip the camera to geometry and observe viewport changes. Refit on source or seating changes; exclude the illustrative parent envelope while not seated. Normal flex layout reserves separate space for title/context, preview and controls; mobile retains a320px canvas and allows content to grow. No new dependency or geometry/cost change.
- Native proof: the same real NIST FTC-07 fully renders at1280px desktop and390/320px phones. Filename, measured dimensions and context do not overlap the canvas or controls. X-ray changes to wireframe and restores solid; native pointer dragging changes the actual orientation. Record identity stays `01M3S2XNGHH6342NM253012Y2D`; viewport override reset.
- Replaced the old phone CSS-source regex test with runnable native DOM geometry assertions in `scripts/e2e/stage-preview-validation.mjs`.494 remaining frontend tests pass, types and changed-file lint pass, final production build passes. The new assertion fails on the original desktop and passes across all three widths. Actual model visibility is additionally confirmed by native screenshots, not inferred from a canvas element alone. Backend unchanged from2442 passing tests.
- Evidence: `100-stage-layout-proof.json` and100 desktop/phone/X-ray/orbit screenshots. Local verification only; production and additional assembly/STL cases remain open.

CI checkpoint36708617787 on d107cbe (through097) completed with8jobs passing and the browser job failing in the34-file CAD corpus:33passed; FTC-07 exceeded90seconds despite a captured output ending inOK/PASS. The shutdown stack is absent in this old build. Later missing-data errors are symptoms; downstream restore/load/readiness/training did not run. The local098 shutdown fix is not part of that run. See `ci-36708617787-summary.json`.


## 101 — A malformed ASCII STL crashes the main Verify workspace

- Severity: medium availability/recovery defect; fixed locally, not deployed.
- first divergence: step2, expected the selected file and a recoverable preview error to remain visible, state was the root “Page temporarily unavailable” screen after uploading a46-byte recognizable but truncated ASCII STL. The native assertion failed because the filename and workspace had disappeared. A37-byte unrecognized STL was already refused correctly by the existing integrity check.
- Root cause: the bounded ASCII header check intentionally leaves deeper validation to the CAD parser, but the main renderer had no error boundary around STLLoader/GLTFLoader. The loader error escaped to the page boundary and obscured the real backend refusal.
- Fix: extract and reuse the existing pair-preview boundary around the main stage. Key it by the loaded source so replacement recovers; identify the failed preview honestly and disable X-ray/seating when unavailable. Validation and replacement controls remain accessible. No new dependency, parser implementation or acceptance relaxation.
- Native GREEN: the same file and repeated retry retain the filename, minimum84-byte backend refusal, disabled X-ray and Check my CAD. Replacing it with the retained NIST FTC07 STL mesh restores the true shell and holes,311.6×135.9×222.7mm dimensions and1726.00cm³ at desktop and390px. The shared two-part viewer also contains the malformed input, then recovers with two real10mm cubes at20mm X translation and measures10.000mm clearance/no overlap.
- Checks:494 frontend tests, TypeScript, changed-source lint and final production build pass. The reusable native regression assertion is in `scripts/e2e/stage-preview-validation.mjs`; evidence is `101-preview-recovery-proof.json` and101 screenshots. Backend code and estimates were not changed; prior full2442-test result remains applicable. Production and external workflow proof remain open.

## 102 — Cold IGES imports fail before reading valid geometry

- Severity: HIGH; fixed locally, not deployed. First divergence: a valid IGES upload reports a STEP-read refusal because the cold OpenCASCADE IGES reader cannot set its target-unit registry before initialization. After that failure is removed, a closed box still arrives as separate faces and the assembly probe refuses it.
- Fix: shared CAD import configuration retains explicit millimeters for STEP, uses the IGES reader's native millimeter normalization and enables existing OCC face sewing/solid creation for IGES. Existing tolerance and closed-solid acceptance stay unchanged. Both single-part and assembly readers reuse the helper; engine/cache identity is0.3.14.
- Eight real fresh-interpreter regressions cover millimeter/inch files, `.iges`/`.igs`, both readers, closed boxes and deliberately open planes. Closed geometry preserves physical bounds and volume; open surfaces never become invented solids. Fresh processes are essential because an earlier IGES read conceals the initialization bug.
- Native proof: two20×15×10mm IGES boxes render and measure10.000mm clearance at30mm X translation, then3000.000mm³ overlap at zero translation. Main Verify accepts the inch control, displays508×381×254mm and49161.19cm³, and saves record `01M3S5J3S2D8MQADS7FG798BRC`. These are controlled geometry checks, not customer quote validation.
- Checks:2450 backend tests pass, three documented local corpus/OCP-XDE skips; type count215/228 with zero new diagnostic messages; changed-source Bandit has no medium/high findings. Frontend is unchanged from101's494 passing tests/types/lint/build. Evidence: `102-iges-import-proof.json`,102 screenshots and `test_iges_import.py` with four real IGES controls.
- Remaining limitation: a curved bored-block IGES export renders but remains non-watertight, so fit is withheld. Whether this comes from the export or reader remains unresolved; no general closed-solid IGES success is claimed. Exact-head CI and production retest remain required.


## 103 — Owned-process discount bypasses a failed machine-fit verdict

first divergence: step2, expected the inch IGES control rejected by both owned machines to use fully loaded costing, state was “Makeable — not on owned” beside a0.65× OWNED IN HOUSE driver and an unqualified “best machine”.

- Severity: HIGH — the declared ownership shortcut understated the price despite explicit material/envelope failures. The live Verify flow submits owned process families as well as loading the actual machine inventory; the cost orchestrator previously applied that declaration independently of fit.
- Fix: when inventory exists, filter declared ownership through each route's passing fit before both quantity rows and arbitrary-quantity crossover evaluation. Reuse the same filtered options for assumptions, without mutating the caller. Passing machine-rate overrides and legacy no-inventory ownership remain intact. The shared frontend route selector withholds a failed/unknown machine from the best-fit label while retaining its diagnostic failures. Engine/cache identity is0.3.15.
- Regression proof: wrong material, too-small envelope and missing process fail before the fix; unknown-capability and passing-without-rate controls verify the boundary. Tests also compare the entire decision/crossover and assumptions. The frontend regression rejects a failed/unknown closest machine presented as the best fit.
- Native same-file replay saves `01M3S63TWJPSB2VSDH5DZKWQ3G`: CNC3 qty1 changes from$1332.01 to$1762.46 and its crossover from77 to50; invalid OWNED IN HOUSE and best-machine claims disappear. Database comparison proves unchanged geometry/fit and all unaffected estimates, exactly removes the35% machine-line discount from the12 affected CNC3/FDM rows, and reconciles all48 stored estimates. The old0.3.14 record remains immutable.
- Checks:2455 backend tests pass with3 documented local corpus/OCP-XDE skips;495 frontend tests/types/changed-source lint/build pass. Backend types215/228 with zero new diagnostic messages, changed-source Bandit no medium/high findings. Evidence: `103-owned-fit-record-proof.json`,103 native screenshots and existing behavior-test modules. These remain assumption-based prices, not actual quote calibration; not deployed.

CI36713400616 on b163bc1 (through098–100) completed successfully with all9 jobs passing, including Browser E2E. This closes that run's prior FTC-07 gate; it does not establish the historical failure's exact cause or include101–103. PR image vulnerability scans remain main-only. See `ci-36713400616-summary.json`.


## 104 — One invalid machine CSV row aborts the complete import

first divergence: step2, expected two valid machine rows to save with the overflowing count rejected on line3, state was a native HTTP500 and neither valid row appeared.

- Severity: HIGH — count validation did not respect PostgreSQL's integer boundary, and an insert failure poisoned the whole import transaction. Its broad exception handler also returned raw database exceptions and counted rows before the eventual rollback. Shared numeric validation accepted NaN/infinity; array-valued capability enums raised TypeError; oversized CSV fields escaped as an unhandled parser error.
- Fix: reuse the existing importer savepoint/error-class pattern for each machine row. Count only released savepoints, return safe row errors for data/constraint failures and let availability/schema failures abort. Reject non-finite scalars, counts above2147483647 and wrong enum types in the shared validator used by create/update/CSV and shop capability limits. Catch CSV read failures with actionable field-size/quoting guidance. No schema, costing or engine/cache version change.
- Native same-file retry imports2/skips1 of3 and identifies line3's count limit. Both valid rows survive reload and independent PostgreSQL readback with their exact counts/rates. A rejected-only file adds0 machines and reports all3 errors for infinite rate, malformed motion mode and NaN envelope. The prior inventory remains present; the two clearly named Audit104 controls remain in local QA inventory.
- Three behavior regressions fail before the fix; real PostgreSQL proves a storage-rejected row preserves the valid rows before and after it without exposing SQL/driver internals. Full2458 backend tests pass with3 documented local corpus/OCP-XDE skips;46 focused tests pass after the final finite-number wording. Types215/228 add zero diagnostic messages, changed-source Bandit has no medium/high findings. Frontend is unchanged from495 passing tests/types/lint/build.
- Evidence: `104-machine-import-proof.json`, two CSV controls,104 native screenshots and `test_machine_inventory.py`. Local only; exact-head CI and production retest remain required. The existing CI36718240878 is still running the prior pushed103 head and does not include104.


## 105 — Machine inventories stop at the first 100 records

first divergence: step3, expected all101 stored machines after the successful97-row import, state was100 visible cards and the final imported machine absent.

- Severity: medium — the shared inventory client discarded the API cursor, so the Machines screen, Home counts and Verify ownership list saw only the first page. Backend cost evaluation already loaded the complete inventory.
- Fix: follow the existing cursor in the shared client and return the complete list to all three callers. Encode cursors, reject any page failure instead of presenting a partial inventory, and refuse repeated cursors. No new dependency or backend change; an explicit ponytail comment records the in-memory fleet-size ceiling.
- Native proof uses101 actual local PostgreSQL records. Before:100 cards ending in temporary096. After:101 cards, Home shows101 machines, and formerly hidden temporary097 opens its correct detail. The97 temporary fixtures were backed up then removed by exact IDs/org; the original four rows match their pre-test hash exactly. Reloaded Home and Machines both show4 and no temporary names remain.
- One runnable behavior test fails before the fix and passes after, covering complete reads, cursor encoding, a second-page503 and a repeated cursor. All496 frontend tests, types, changed-source lint and production build pass. Backend remains at104's2458 passing tests with3 documented local skips.
- Evidence: `105-machine-pages-proof.json`, `105-machine-pages-cleanup.json`, the97-row CSV, and before/after/detail/count screenshots. Local only; production and external-workflow proof remain open.


## 106 — Machine-detail read failures invent default rates and an empty history

first divergence: step2, expected explicit unknown rate context and unreadable records after stopping the local API, state was “no governed rate card in effect”, a default-card footer and “nothing routed yet” alongside a request error.

- Severity: medium accuracy/recovery defect. RateHistory discarded rejected Promise.allSettled results and interpreted null data as the default. RoutedParts rendered its empty-state branch after a failed read. Neither panel offered an in-place retry.
- Fix: require both rate-library reads before claiming a context; show an unconfirmed state on loading/error and retain the machine's own saved scalar declaration. Make record-error, loading, empty and populated states exclusive. Reuse local effect retry counters and existing buttons for each panel; no backend/schema/dependency change.
- Native RED/GREEN uses a real stopped local API, not mocked browser responses. Both panels retain the saved machine specs, suppress false default/empty claims and expose Retry. Repeated outage retries remain recoverable. After restarting the API, both buttons recover without reloading; the rate context resolves and all3 existing process-related records return, including both historical inch-IGES results.
- All496 frontend tests, types, changed-source lint and production build pass. The runnable native assertion is `scripts/e2e/machine-detail-validation.mjs`; evidence is `106-machine-detail-proof.json` plus before/fixed/recovered screenshots. Backend remains104's2458 passing tests. Not deployed.


## 107 — Opening a machine-related record loses the selected decision

first divergence: step2, expected the selected inch-IGES decision to open, state was the generic47-row Records list at `/verify`.

- Severity: medium navigation defect. Every machine-detail Open button discarded the row ID and navigated to the same list.
- Fix: use a native accessible link to the existing authenticated `/cost-decisions/{id}` page, encoding the ID. Remove the unused navigation prop from the machine component chain and its sole parent caller. No new route or state layer.
- Native proof: the first inch-IGES link targets `01M3S63TWJPSB2VSDH5DZKWQ3G` and opens that exact URL. The saved page shows `box-inch.igs`, the matching CAD hash and$1762.46 at quantity1. The older same-name record has its own distinct link; no saved data changes.
- All496 frontend tests, types, changed-source lint and production build pass. Backend unchanged from2458 passing tests. Evidence: `107-machine-record-proof.json` and before/fixed screenshots. This is a simple link change checked through the real browser; no source-text test added. Not deployed.

CI36718240878 completed successfully on a028e56 (through103): all9 jobs passed, including Browser E2E. This excludes104–107; their exact-head run follows the next push. Main-only image CVE scans and production/external-provider proof remain open. See `ci-36718240878-summary.json`.


## 108 — Home counts inventory entries instead of declared machines

first divergence: step2, expected6 machines from declared quantities2+1+1+2, state was4 machines added/declared/owned on Home.

- Severity: medium numerical accuracy defect. Both total and rated-machine counts used array lengths, so grouped quantities were ignored.
- Fix: sum declared counts for both totals, matching the inventory service's existing default of1 for null counts. Reuse one small count helper for both calculations; retain zero/unknown loading distinctions.
- Native Home, onboarding and Your Floor now all report6; independent PostgreSQL readback confirms4 entries with quantities[2,1,1,2] and6 machines with rates. No inventory records changed.
- A runnable behavior test covers grouped quantities, the existing null default, subsets and empty lists. All497 frontend tests/types/changed lint/build pass. Backend unchanged from2458 passing tests. Evidence: `108-inventory-total-proof.json` and before/fixed screenshots. Local only; prior105 proof recorded the then-current entry-count behavior, now corrected to physical quantities.


## 109 — Inventory and Records outages are presented as empty workspaces

first divergence: step2, expected an unavailable-list state after stopping the local API, state was “No records yet” beside the records error and “Declare your floor” beside the inventory error.

- Severity: medium correctness/recovery defect. Both catch branches assigned empty arrays and the rendering branch treated a failed fetch as a confirmed empty result. Neither initial-read error had a Retry control.
- Fix: keep loading/error/confirmed-empty states distinct and reuse the existing refresh functions from explicit Retry controls. Records pagination still retains already loaded rows and retries the failed next page; no new fetch abstraction or API change.
- Native RED/GREEN uses actual stopped/restarted local API processes. Both lists suppress false empty claims and keep retries usable during the continued outage. Once the API returns, Retry inventory restores4 real entries and Retry records restores47 saved decisions, independently in two native tabs without reloading. No saved data changed; the extra test tab was closed.
- All497 frontend tests/types/changed lint/build pass. The runnable native assertion extends `scripts/e2e/machine-detail-validation.mjs`; evidence is `109-list-recovery-proof.json` and before/fixed/recovered screenshots for both screens. Backend unchanged from2458 passing tests. Not deployed; exact-head CI still required.


## 110 — Inventory labels overstate machine-fit and costing evidence

first divergence: step2, expected an undeclared machine rate to disclose fallback assumptions, state was “marginal cost is withheld” even though the existing engine control proves a passing machine without a declared rate can retain default ownership costing.

- Severity: medium disclosure accuracy defect. A rated inventory entry also said OWNED → MARGINAL before any part-specific fit. The detail list called same-process decisions PARTS ROUTED HERE even when the record's own machine-fit verdict failed. Its existing footer only partially explained the process filter.
- Fix: identify owned rates as declarations, state the passing-fit requirement, explain missing-rate assumptions, and stop describing an absent rate as a USER declaration. Label the existing last25 process-filtered records precisely and direct users to each record's fit verdict. No pricing, matching, record filtering or backend behavior changes; the existing native links remain intact.
- Native before/after checks use a temporary3-machine no-rate CSV entry. Home reports9 total/3 missing-rate machines, corroborated by PostgreSQL. The no-rate detail discloses default assumptions; rated CNC says RATE DECLARED and retains both same-name historical links under the process-specific heading. The existing engine passing-machine/no-rate behavior test passes.
- Cleanup removes only the backed-up temporary entry; all4 pre-test records match their original complete-row hash. Native reload confirms6 machines across4 entries and no temporary name. All497 frontend tests/types/changed lint/build pass; the existing manufacturing-browser evidence label and native detail assertion follow the corrected copy. Backend unchanged from2458 passing tests.
- Evidence: `110-machine-label-proof.json`, `110-machine-label-cleanup.json`, the one-row CSV and no-rate/count/process screenshots. This proves accurate disclosure of assumption-based behavior, not customer-quote accuracy. Local only; deployment remains pending.
