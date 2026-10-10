# Integration readiness evidence ledger

This tool measures **demonstrated workflow-stage coverage**, not the probability that an integration works. It performs no network requests, creates no accounts, sends no email, and changes no application or provider settings. A zero means **NOT_DEMONSTRATED by supplied evidence**, not that a vendor connection was attempted and failed.

## Fixed denominator

Every external customer workflow has the same six stages. Each demonstrated stage earns one point; coverage is `100 × demonstrated stages / 6`, rounded to two decimal places. Disabled optional workflows retain their denominator. File-only workflows are listed separately as **N/A** for external network coverage.

| Stage ID | Operator acceptance criterion |
|---|---|
| `configuration_trust` | Independently observe the actual provider and ScaleCad runtime using the intended tenant, endpoint, client/service identity, trust configuration and callback/return destination. A saved configuration flag alone is insufficient. Local HTTP is acceptable only for an expressly local isolated test target. |
| `authentication_transport` | Complete real provider authentication/transport to the intended ScaleCad runtime. Validate tenant/provider identity and the relevant credential, token/assertion or transport security behavior. Internal callback fixtures do not qualify. |
| `functional_action` | Complete every functional check listed for this workflow in `registry.json`, with provider and ScaleCad observations. A successful one-product probe does not establish a full BOM import. |
| `source_result_reconciliation` | Compare a documented normalized projection of customer-relevant source fields with the resulting ScaleCad data or delivered output. Hash separate nonempty JSON source/result snapshots and a comparison report identifying fields. All missing/extra/changed counts must be zero, and normalized JSON must match. Operators must review that the projection includes the workflow's full relevant data. |
| `failure_handling` | Cause an authorized real-provider/transport failure or rejection. Observe correct ScaleCad error handling and preserved data/security state. A mocked exception is insufficient. |
| `recovery_retry` | Restore the actual failed dependency/credential condition and complete the same customer action again. Verify the intended result and absence of duplicate/partial state. A standalone successful request is insufficient. |

These equal-sized stages are a deliberately coarse accounting convention. They are not equally difficult, and six points do not prove every possible configuration, edge case, production load, browser, tenant or customer deployment. Evidence from one source commit/runtime is not automatically current for another deployment. The score uses the most recently completed real evidence context and combines stages only within that same environment ID, endpoint, class, source commit and build ID. Other-context run IDs remain visible but cannot inflate its numerator. The matrix keeps evidence paths; reviewers must also check source/build and environment applicability.

## Workflow-specific scope

- **SAP S/4HANA:** product lookup and complete supported BOM **preview**, with source field/count/quantity/unit/structure reconciliation. ScaleCad's unsupported assembly import and SAP write-back/export receive no implied credit.
- **Windchill:** actual part lookup **and full supported BOM import**, including hierarchy, part identity, revisions, quantities and units. An authenticated part probe alone does not pass functional action.
- **SAML providers:** actual provider login, validated signed assertion callback and correct mapped ScaleCad user/session. Check identity, tenant, groups/roles, authorization and rejected assertions in their respective stages.
- **OIDC providers:** actual provider login, authorization-code callback/token validation and mapped ScaleCad user/session. Check issuer, subject/email claims, state/nonce, redirect and tenant/role boundaries as applicable.
- **SCIM:** create, update, group assignment, deactivate and reactivate a synthetic user against the real provider's provisioning client. Confirm identities, active state, groups, idempotency and recovery.
- **Resend magic links:** provider accepts the message, the authorized recipient actually receives it, and the link is redeemed successfully. Acceptance by the send API alone is insufficient.
- **Resend invitations:** provider acceptance, actual recipient delivery and invitation acceptance into the intended organization/role.
- **Resend pilot alert:** provider acceptance, actual alert delivery and correct pilot-intake fields in the received message. Do not send to unapproved people.
- **Batch webhooks:** actual completed-batch event reaches an authorized receiver and its payload matches the intended batch. Observe real rejection/unavailability and actual retry/recovery separately.
- **Turnstile:** real browser challenge, successful actual provider `siteverify` and intended protected action. Cloudflare's always-pass test keys are fixtures, not real-service evidence.
- **Replicate TripoSR:** actual prediction creation, completed provider job and usable imported mesh; currently an optional disabled workflow.
- **Google OAuth:** implemented but not currently advertised; scope is real provider login, callback and mapped user session.
- **Local Keycloak basic OIDC sign-in:** a real self-hosted OSS target on isolated **HTTP loopback in development**, with no provider group mapping configured. The basic workflow covers provider login, authorization-code callback and the mapped ScaleCad user/session. Its source/result reconciliation projection is exactly **issuer, subject and email**, compared between actual provider identity data and ScaleCad's persisted identity/user records. The observed **Viewer** role is ScaleCad's default application policy, not a role supplied or mapped from Keycloak. Provider group-to-role mappings, organization assignment and enterprise authorization are outside this local basic workflow's credited projection. This row **never** credits Okta, Entra, PingFederate, production TLS/deployment readiness, or production tenant configuration.
- **Three shipped offline CSV connectors:** `sap_manifest_csv` (SAP manifest CSV: declared parts, demand, programs and materials), `plm_manifest_csv` (PLM manifest CSV: declared PLM/BOM part registry), and `ground_truth_csv` (Quote/actuals CSV: supplier quotes, invoices and ERP actual costs). Parser and synthetic fixture validation are separate from real source-system reconciliation, which requires approved source exports and output comparisons. All three have N/A external network coverage and NOT_DEMONSTRATED real-source reconciliation.
- **CAD file interchange:** a fourth, separate file capability rather than a CSV connector. Core file import/download and synthetic geometry QA do not establish source-system reconciliation. Its external network coverage is N/A and real-source reconciliation remains NOT_DEMONSTRATED.

`registry.json` records the required `functional_checks` identifiers. Operators must review all six acceptance criteria against the workflow; the scorer cannot infer semantic completeness from an HTTP 200 or a connected label.

The October 10 local Keycloak exercise observed an actual provider password rejection, successful browser login/callback, the authenticated ScaleCad account, exact persisted issuer/subject/email matching, and repeat login to the same identity/user after signout. Those observations support at most configuration, authentication, basic functional action and the scoped identity reconciliation: **4/6 (66.67%)** when their reviewed receipt bundle passes validation. Provider-side wrong-password rejection alone does not demonstrate ScaleCad's app-side failure handling, and ordinary signout/relogin demonstrates repeatability rather than dependency failure recovery. Keep `failure_handling` and `recovery_retry` **NOT_DEMONSTRATED**. State/nonce/replay rejection, provider outages, deprovisioning, group mappings and enterprise authorization remain untested against this real target; the stage percentage does not imply these subcases passed.

## Environment classes and evidence boundaries

Only these classes can earn real-system stage credit:

| Class | Meaning |
|---|---|
| `vendor_sandbox` | A real named vendor's authorized sandbox, with an operator-reviewed tenant manifest. |
| `customer_test_tenant` | An explicitly authorized customer/vendor test tenant or receiver; never an unapproved production tenant. |
| `self_hosted_oss_test` | A real separately running open-source provider in a dedicated local/test environment. It does not certify named vendors. |

`mock`, `fixture` and `simulator` evidence is retained separately and always earns **zero** real-system credit. An environment label is not evidence of provenance. The tenant manifest must be independently reviewed against actual provider/runtime configuration and the authorization record. The operator acceptance review must inspect the referenced receipts and their relevance. Self-asserted JSON, booleans, receipt identifiers or hashes cannot independently prove that a provider was real or that the operator was authorized.

This is an accounting guardrail, **not a provenance attestation service**. Artifact hashes detect missing/changed supplied bytes; they do not establish who produced those bytes, prove endpoints were contacted, certify TLS/provider ownership, verify a signature, or establish that a normalized source projection is complete. No published percentage should be used without that human review. Synthetic unit-test evidence is not integration readiness evidence.

## Evidence document

One JSON document represents one workflow run. Paths are resolved relative to that document and must stay inside `--artifact-root` (including after symlink resolution). Output evidence paths are relative to the artifact root, so a reviewed bundle and its matrix can move together without machine-specific absolute paths. Parsed JSON must not contain nonstandard `NaN`, `Infinity` or `-Infinity` constants. Retain only sanitized receipts; never persist passwords, bearer/API tokens, client secrets, session cookies or authorization codes in the audit bundle. Hash the sanitized durable artifact that is actually reviewed.

Required top-level fields:

```json
{
  "schema_version": 1,
  "run_id": "unique-run-id",
  "workflow_id": "keycloak_oidc",
  "provider_id": "keycloak",
  "environment_class": "self_hosted_oss_test",
  "environment": {"id": "isolated-local-keycloak-run-id", "base_url": "http://127.0.0.1:18080/realms/scalecad-test"},
  "source": {"commit": "FULL_40_CHARACTER_LOWERCASE_GIT_SHA", "build_id": "actual-runtime-build-or-image-id"},
  "authorization": {"scope": "local synthetic test identities only", "reference": "approved-task-or-authorization-record"},
  "tenant_manifest": {"path": "tenant-manifest.json", "sha256": "LOWERCASE_SHA256_OF_FILE", "reviewed_by": "operator identity", "reviewed_at": "2026-10-10T12:00:00Z"},
  "started_at": "2026-10-10T12:00:01Z",
  "completed_at": "2026-10-10T12:01:00Z",
  "vendor_attempt_count": 0,
  "stages": []
}
```

The uppercase tokens above describe a schema, not usable evidence. `vendor_attempt_count` is mandatory: a nonnegative integer or `null` for unknown. Local OSS/mock/fixture/simulator runs can record only zero or unknown named-vendor attempts. A passing vendor/customer run requires a known positive count. The matrix reports known counts and unknown runs separately. With no evidence, the known supplied count is zero and historical attempt availability remains unknown; **absence of evidence is not proof that nobody ever tried**. Do not double-count the same vendor request across multiple workflow run documents.

The hashed `tenant-manifest.json` must contain matching values:

```json
{
  "operator_reviewed": true,
  "provider_id": "keycloak",
  "environment_class": "self_hosted_oss_test",
  "environment_id": "isolated-local-keycloak-run-id",
  "base_url": "http://127.0.0.1:18080/realms/scalecad-test",
  "authorization_reference": "approved-task-or-authorization-record"
}
```

Each observed stage has this structure (a NOT_DEMONSTRATED stage needs only `stage_id`, `outcome` and optional valid artifacts):

```json
{
  "stage_id": "authentication_transport",
  "outcome": "PASS",
  "independently_observed_action": true,
  "action_description": "Describe the actual provider and ScaleCad runtime action and the acceptance criterion observed.",
  "request_id": "actual-correlatable-request-or-test-action-id",
  "provider_receipt_id": "actual-provider-event-or-response-receipt-id",
  "acceptance_review": {"reviewed_by": "operator identity", "reviewed_at": "2026-10-10T12:00:59Z", "reference": "operator-review-record"},
  "artifacts": [
    {"path": "provider-response.json", "sha256": "LOWERCASE_SHA256_OF_FILE", "kind": "provider_receipt"},
    {"path": "runtime-observation.json", "sha256": "LOWERCASE_SHA256_OF_FILE", "kind": "runtime_observation"}
  ]
}
```

PASS and FAIL both require independently observed actions and separate provider/runtime artifacts. A PASS additionally requires an operator acceptance review. `provider_receipt_id` can be a provider event/message/job ID or a durable receipt ID correlating an actual response where the provider has no event IDs; document its origin in the receipt. It must not be a made-up success label. Receipt IDs must be unique per provider/environment across supplied runs. Unknown workflows/stages, duplicates, contradicting simultaneous outcomes, provider/workflow mismatches, manifest mismatches, missing/tampered/out-of-root artifacts, incomplete acceptance checks and failed reconciliation reject the **whole audit**, with exit code 2 and no new matrix written. A later actual FAIL removes that stage's current credit until subsequent valid PASS evidence is supplied; historical evidence files remain available.

For `functional_action` PASS also supply every workflow's required check with `PASS`. For Keycloak:

```json
"acceptance_checks": {
  "provider_login": "PASS",
  "authorization_code_callback": "PASS",
  "mapped_user_session": "PASS"
}
```

For `source_result_reconciliation` PASS add separate hashed artifacts of kinds `source_snapshot`, `result_snapshot`, `reconciliation_report`, then reference their exact paths:

```json
"reconciliation": {
  "source_artifact": "source-normalized.json",
  "result_artifact": "scalecad-normalized.json",
  "diff_artifact": "diff.json",
  "missing_count": 0,
  "extra_count": 0,
  "changed_count": 0
}
```

The two snapshots must contain equal, nonempty JSON objects/arrays. `diff.json` must identify the compared fields and repeat all three integer zero counts:

```json
{"compared_fields": ["subject", "email", "organization", "role"], "missing_count": 0, "extra_count": 0, "changed_count": 0}
```

Do not include fields in `compared_fields` that the projection does not actually compare. Review mapping/normalization semantics against raw authorized source receipts; arbitrary identical snapshots do not establish data fidelity.

## Run locally

No dependencies beyond Python 3.9+ standard library are needed. Baseline with no supplied real-provider evidence:

```sh
python3 integration-tests/readiness.py \
  --artifact-root .gstack/qa-reports/integration-readiness-2026-10-10 \
  --output-json .gstack/qa-reports/integration-readiness-2026-10-10/baseline-matrix.json \
  --output-markdown .gstack/qa-reports/integration-readiness-2026-10-10/baseline-matrix.md
```

To score actual reviewed runs, add `--evidence` followed by the explicit run JSON paths (do not include manifest/receipt JSON as run documents). Check exit status before using output; a rejected invocation does not replace an older successful report. Output is deterministic for a fixed registry and evidence set; no current timestamp or network state is injected.

Guardrail tests:

```sh
python3 -m unittest discover -s integration-tests/tests -v
```

The tests use synthetic temporary fixtures, including deliberately real-labelled fixtures to test accounting logic. They receive no readiness credit and must never be submitted as actual provider evidence.
