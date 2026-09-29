# Engineering package implementation

Build goal: implement the supplied-package workflow in the existing CadVerify platform, on production base `09555c1`. Branch: `codex/engineering-package-readiness`.

Completion ledger (unchecked means unfinished):

- [x] Context-sensitive saved decision identity, missing environmental coverage, process-scoped empirical intervals, and consistent DFM/machine verdicts.
- [x] Organization-scoped packages tied to existing part geometry and saved evaluation; order/revision/effectivity and declared source authority.
- [x] Retained source files, manually confirmed characteristics and bounded CSV/JSON imports from existing engineering tools; source locations, coverage and conflicting requirements.
- [x] Manufacturing/inspection/material evidence with applicability, owner, closure criteria and accountable review; separate screening, qualification evidence and external authorization.
- [x] Immutable issued versions and revision comparison: changed requirements invalidate dependent evidence; unknown dependencies require review; historical orders remain intact.
- [x] Conditional route alternatives using existing engine results, requirements, resource assumptions and concrete outstanding actions.
- [x] Scoped outcomes and evidence reuse, including failures, sample sizes, expiry and explicit applicability review.
- [x] Existing part-workflow UI for the complete loop, portfolio blocker queue, accessible errors and concurrency handling.
- [x] Consistent human packet and structured exports with original source/evidence references.
- [x] Behavioral, storage/API and browser verification, migration checks, production build and reviewable delivery.

Research remains evidence of category demand, not a completed customer pilot. Software completion cannot substitute for external customer qualification or field validation. Native CAD authoring, replacement PLM/QMS, universal OCR/PMI, live customer connectors without access, and automatic engineering authorization are outside the recommended product scope. Explicit source mapping and import contracts must be usable without those systems.


## Delivered workflow

Open **Verify → Parts → Open standing → Engineering package**. The package uses the part's saved engine evaluation. Declare the order, authorized source revision, effectivity and manufacturing scope; retain source files or controlled references; enter or import source-linked requirements. Confirm the source mappings, review applicable evidence and assign unresolved actions. Record actual outcomes, including failures, and review closure evidence. Issuing creates another immutable version with the remaining blockers visible; it grants no manufacturing authorization.

Each explicit confirmation records the authenticated reviewer, time and exact reviewed content. Geometry, requirement content, source evidence, selected setup or physical input changes invalidate dependent reviews. Changed drawing locations/revisions require mapping confirmation even where the engineering requirement itself is unchanged. Current reads check expiry and the saved evaluation against the current machine, shop-operation and service-environment declarations; historic exports retain their original dated assessment. Legacy evaluations without an input snapshot require re-verification.

Prior evidence can be imported from another saved package only as a candidate: source and outcome lineage remain, receiving requirement mappings and review receipts are cleared. Contrary evidence and observed failures require a reviewed disposition. Open assigned actions require a separate closure review. External authorization is recorded separately against the exact order and revision.

The portfolio queue groups **latest saved** blockers by evidence type and accountable owner, with bounded SQL aggregation and keyset drilldown to the exact order. Opening a package reassesses current applicability. The queue is a saved-review work list, not continuous field monitoring.

## Integration and operating contract

- Database: additive migration `0047_engineering_packages`, after `0046_trial_plan`. One tenant-scoped version table; unique latest/version constraints and compare-and-swap saving prevent concurrent overwrites. Existing production data is not rewritten. Apply `alembic upgrade head` with the normal release migration process before serving the new endpoints.
- Storage: existing object-store backend, namespace `engineering-documents`. Each retained file is addressed by organization and SHA-256. Default local directory is `/data/blobs/engineering-documents`; `ENGINEERING_DOCUMENT_BLOB_DIR` overrides that default. Existing `OBJECT_STORE_*` configuration still applies. Include this namespace in the existing backup/retention policy.
- Auth: existing session/API-key, active organization, viewer reads, analyst writes, write kill switch and rate limits. No new credentials or dependency packages.
- API: `/api/v1/engineering-packages` for listing and immutable saves; `/documents` for retained originals; `/import-characteristics` for CSV/JSON; `/queue` for grouped blockers; `/{id}` for the historical document plus current assessment; `/{id}/documents/{source_id}` and `/{id}/export.{json,csv,html,pdf}` for downloads.
- Inputs: 20 MiB per original file; 2 MiB per structured package/import; 100 sources, 500 requirements/evidence entries, 200 actions and 100 outcomes per part package. This bounded part workflow reuses the current inventory and costing engines. It does not load a whole enterprise's raw geometry into the application process.
- Imports: explicit characteristic exchange schema, not a proprietary CAD/CAM parser. CSV columns are `id,characteristic,feature,kind,value,unit,lower,upper,source_id,location,required_evidence`; evidence kinds use semicolons. JSON is an array or `{ "requirements": [...] }`. All mapped source IDs must exist before saving. Imports start unreviewed. CSV export uses the same columns and escapes spreadsheet formula prefixes.
- Outputs: original-source download, reviewed characteristic CSV, complete JSON snapshot, printable HTML and PDF decision packet. PDFs include source hashes/references, requirement locations, physical scope, dispositions, accountable actions, conditional resources, actual outcomes and review receipts.

## Verification receipts

- Backend full suite: **2,315 passed, 3 skipped** against isolated PostgreSQL and Redis. Skips: unavailable real corpus manifest and two unavailable OCP XDE parser tests. No external customer CAD corpus or live specialist connector was claimed tested.
- Final targeted suite after the PDF, action-closure and authorization checks: **62 passed** (engineering packages/trust, PDF, persisted cost API and catalog projection).
- Frontend: **484 passed**; TypeScript and ESLint passed for all changed frontend code; production Next build passed.
- Database/API: live PostgreSQL migration chain, tenant and role boundaries, retained originals, JSON/CSV/HTML/PDF output, immutable history, concurrent save conflict, keyset pagination, expiry on read, exact-part retrieval and stale projection regression.
- Browser: production frontend and real local backend, signed synthetic test account and an engine-computed part. Local receipt and screenshot are in `outputs/product-discovery-2026-09-29/evidence/implementation-browser/`. Exercises invalid input, original upload, explicit review, issued PDF, tighter drawing with unchanged geometry, accountable actions, failed actual outcomes, exact order drilldown and scoped evidence reuse.

The browser fixture is synthetic QA data. Its measured-study text is not a real qualification study, and no result here demonstrates field qualification, customer acceptance or a paid CadVerify deployment.

### Reproduce

Use an isolated local PostgreSQL database, Redis and the repository's existing Python/frontend dependencies. Apply migrations. Set `DATABASE_URL`, `DASHBOARD_SESSION_SECRET` and the existing storage settings consistently for the backend and seed process. The seed rejects non-local database hosts.

```sh
# From backend, with the test DATABASE_URL and REDIS_URL exported:
python -m pytest -q
alembic current

# From frontend:
npm ci --no-audit --no-fund
npm test
npx tsc --noEmit
API_BASE=http://127.0.0.1:8047 npm run build
API_BASE=http://127.0.0.1:8047 npm run start -- --port 3047

# From the repository root, with the local backend running on 8047:
python scripts/e2e/seed-engineering-package.py
APP_URL=http://localhost:3047 node scripts/e2e/engineering-package-e2e.mjs
```

The fixture session file defaults to `/tmp/cadverify-engineering-browser.json` with mode 0600. Override `E2E_SESSION_FILE` when running parallel local stacks. Do not commit the session file. Deployment and production migration remain separate release actions; this branch does not apply them remotely.
