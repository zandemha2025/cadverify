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
