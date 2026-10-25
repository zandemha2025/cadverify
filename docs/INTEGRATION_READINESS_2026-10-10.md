# ScaleCad integration readiness audit — 10 October 2026

## Finding

ScaleCad's tested core platform is not evidence that its enterprise integrations
have been validated against vendor systems. The available repository, CI artifacts
and production owner-workspace observations demonstrate **zero completed real
SAP, PTC Windchill, Okta, Microsoft Entra or PingFederate workflows**. They contain
useful implementation, normalization, cryptography, authorization and simulated
protocol tests. Those are recorded separately below.

This is a broader readiness gap than a few missing credentials. The connectors
also have unsupported operations, constrained network/quantity/completeness
support, manual recovery and incomplete evidence provenance. No available test
receipt supports treating them as production-validated enterprise integrations.

This audit does not establish that no test has ever occurred outside the inspected
evidence. It measures **demonstrated coverage in the evidence available here**.
No secret values, one-time login links or customer records belong in this report.

Audited application source and current production release:
`c52267285f622237250306b81ae24db1da1759c9`.
The follow-up environment/tooling and documentation changes are on
`codex/integration-readiness`; they do not modify production configuration.

## How the percentages work

Each named external workflow has six equally weighted acceptance stages:

1. **Configuration and trust:** approved nonproduction target, exact provider and
   tenant identity, trust metadata/callbacks and least-privilege credentials.
2. **External authentication/transport:** a real successful exchange with that
   system; an empty configuration, mock token or anticipated DNS failure is not a
   successful connection.
3. **Functional action:** the full operation advertised for that workflow runs
   against that target. A one-product probe is not a BOM import.
4. **Source/result reconciliation:** independently read source identities,
   revisions, groups, units, quantities and counts agree with ScaleCad's saved
   result, with missing/extra/changed records explained and recorded.
5. **Failure handling:** authorized negative cases are observed through the real
   integration, preserving data and access boundaries.
6. **Recovery/retry:** restore service or valid credentials, complete the same
   workflow safely and check duplicates, stale results and unintended access.

`real demonstrated coverage = credited real-system stages / 6 × 100`.

This is **not** percentage implemented, probability of success, test pass rate,
manufacturing correctness or vendor certification. Missing evidence is
`NOT_DEMONSTRATED`, not a fabricated failed test. No real vendor attempts are
recorded in the inspected baseline, so the baseline is zero demonstrated successes
and zero evidenced vendor attempts, rather than six failures per integration.

Keep four evidence classes separate:

- Real vendor sandbox / authorized customer test tenant.
- Independently running self-hosted provider, such as a local Keycloak runtime.
- Local protocol simulator or mocked HTTP transport.
- Offline CSV/JSON/file fixture.

Keycloak success can credit only the Keycloak OIDC row. It cannot credit Okta,
Entra, PingFederate, SAP or PTC. Provider-owned test addresses or dummy CAPTCHA keys
also do not prove real inbox delivery or production bot protection.

The executable registry and evidence scorer are in `integration-tests/`. Evidence
requires reviewed tenant provenance, source/build identity, actual provider/runtime
receipts, hashed artifacts and explicit reconciliation. Hashes protect artifact
integrity; they do not independently prove that a receipt came from a vendor.
Operator review remains required.

## Customer-facing external workflow inventory and baseline

All external rows below start at **0/6 = 0% real demonstrated coverage**. A
dedicated local provider test is reported separately after it runs; it does not
retroactively change these vendor results.

| Integration / customer workflow | Available implementation and internal proof | Real environment status / missing prerequisite |
|---|---|---|
| SAP S/4HANA product and BOM preview | Encrypted profile; real HTTPS/OData transport; one-product probe; BOM explosion projection; fixture/MockTransport normalization and rejection tests | No authorized SAP sandbox or source export supplied. Business Accelerator Hub offers vendor API sandboxes requiring a signed-in account/API key; exact product/BOM endpoint compatibility still needs verification. |
| PTC Windchill part/BOM import | Real Parts/CSRF/GetPartStructure transport; constrained complete BOM normalization; hash guard; transactional local assembly replacement; fixture-only tests | No authorized WRS tenant, exact part iteration/filter or independent source snapshot supplied. A Navigate trial is not proof of a usable WRS API sandbox. |
| Okta SAML SSO | Generic SP/JIT mapping/request/replay/logout tests, mocked SAML internals; setup guide | No authorized Integrator Free Plan/test org or app assignment supplied. |
| Entra ID SAML SSO | Same generic SAML implementation and setup guidance | No authorized Entra enterprise application/test tenant supplied. |
| PingFederate SAML SSO | Same generic SAML implementation and setup guidance | No authorized PingFederate instance/trust configuration supplied. |
| Okta OIDC SSO | Generic authorization code + PKCE, issuer/audience/nonce/state/signature verification, immutable identity binding and mapping tests | No actual Okta issuer/client/test user supplied. |
| Entra ID OIDC SSO | Same generic OIDC implementation; mocked discovery/token/JWKS/userinfo tests | No actual Entra app/client/test user supplied. |
| PingFederate OIDC SSO | Same generic OIDC implementation; no provider-specific receipt | No actual Ping issuer/client/test user supplied. |
| Okta SCIM joiner/mover/leaver | Real local ScaleCad SCIM endpoint lifecycle; `Okta-sim` caller, not an Okta provisioning agent | Need assigned app, real provisioning-agent requests, retries, source group mapping and access-revocation verification. |
| Entra ID SCIM joiner/mover/leaver | Same local HTTP API lifecycle; `Entra-sim` caller | Need actual provisioning service, app mapping, lifecycle/retry evidence and post-deactivation access checks. |
| Resend email sign-in links | Sender call plus internal single-use/expiry/supersession/error rollback tests; sender mocked | Resend account is available in the user's Chrome session. Sender DNS/domain verification, staging API key, authorized inbox receipt and actual link consumption remain unproven. |
| Resend organization invitations | Local invitation/membership lifecycle and manual-link fallback; sender mocked | Need verified sender, authorized recipient inbox, delivered message and exact org/role acceptance plus replay/expiry/failure/recovery. |
| Resend pilot alerts | Durable pilot receipt/idempotency and optional send/audit code | Need authorized alert inbox and provider/inbox receipts correlated to the saved lead; failure must preserve the lead and retries must avoid duplicates. |
| Batch completion webhooks | HMAC, public-URL/IP/SNI transport, rejection and retry/backoff tests | No authorized public HTTPS receiver receipt. Need independent signature/data reconciliation and real transient failure/recovery. |
| Cloudflare Turnstile email-link gate | Conditional widget/server verification; mocked/test-token coverage | Need a staging site/secret and genuine verification workflow. Dummy keys are a separate test class. Interactive challenges require human completion. |
| Cloudflare Turnstile pilot intake | Conditional public-intake challenge/server verification | Same target prerequisites plus matching durable intake receipt. |
| Optional Replicate TripoSR Image-to-3D | Pinned remote model/prediction/poll/download implementation behind an explicit capability gate | Disabled for the audited production workspace. No authorized provider token/budget/input/actual output receipt supplied. No inference run is claimed. |
| Google OAuth (implemented, not current login promise) | Authlib-backed code and mocked route/discovery/wiring tests | No authorized OAuth project/client/test-user/callback receipt. Current login has no Google button; track separately from marketed enterprise support. |

For source evidence, see the connector registry in
`backend/src/services/integration_service.py:81`, connector UI in
`frontend/src/app/(app)/integrations/connector-credentials.tsx:95`, organization
settings at `frontend/src/app/(app)/settings/organization/page.tsx:282`, and
authentication code under `backend/src/auth/`.

The current public platform/security/developer pages make comparatively narrow
API, file-format and deployment claims. The broader named-provider inventory
comes from the authenticated product and enterprise setup guide. The unsupported
legacy wording “Tested providers: Okta, Azure AD (Entra ID), PingFederate” has been
corrected to configuration guidance, with real-provider acceptance explicitly
unverified.

## File workflows and own API — a separate category

These do not have an external vendor network connection to score. A successful
file/parser/API test must not increase a SAP/PLM/IdP percentage.

| Capability | Actual demonstrated boundary | Still required for real source interoperability |
|---|---|---|
| SAP manifest CSV | Live synthetic 2/2 dry-run/import, exact declared inventory values, persisted receipts and malformed-row refusal | Independently exported authorized SAP data and a full source→import comparison. No SAP authentication/read was involved. |
| Generic PLM manifest CSV | Parser/import contract and synthetic fixtures | Genuine PLM export with identities/revisions/BOM quantities and independent reconciliation. |
| Supplier quote / ERP actuals CSV | Parser/ground-truth import contracts | Authorized source invoices/quotes/actuals, unit/currency reconciliation and actual calibration evidence. Do not fabricate shop actuals. |
| REST/OpenAPI and API keys | Own ScaleCad HTTP API/role/tenant/key lifecycle contracts | Customer client acceptance per supported endpoint; does not imply a vendor-specific adapter. |
| STEP/STL/IGES interchange and generated STEP | Actual neutral CAD uploads/generated STEP downloads and displayed hash checks | A named native CAD application workflow needs that application's own acceptance evidence. |
| Cost JSON/CSV/PDF, batch CSV and RFQ ZIP | All six ordinary production export workflows save real files; content/hash/ZIP/PDF validation recorded in the core QA report | RFQ is a downloadable evidence package. No supplier delivery, purchase order or procurement acceptance is implied. |

There are exactly five shipped connector registry entries: three offline CSV
paths, SAP API preview and Windchill API preview/import. SAP assembly import and
both vendors' write-back/export are unsupported. They are not successful gates
hidden inside the supported-scope percentage.

Coupa, SAP Ariba, cXML/PunchOut, Teamcenter, Autodesk APS/Fusion Manage and native
SolidWorks/Fusion/Onshape/CATIA/Creo/Inventor plugins are retained plan/simulator
targets, not shipped named connectors. No current Slack, Teams, Stripe billing,
Salesforce, NetSuite, Dynamics or Oracle ERP integration was located. Inbound
Resend email processing is not implemented; previous QA wording about inbound
email must not become a product promise.

## What the existing green suites really establish

- Main CI run `38022934094` targets the exact production commit. Its connector
  replay artifact passes two offline synthetic normalizations and ScaleCad
  profile create/probe/revoke handling. **Both vendor probes report
  `connected:false`** at reserved example targets. This is not successful SAP/PTC
  authentication or data retrieval.
- `scripts/e2e/scim-idp-lifecycle.mjs:190` invokes `Okta-sim` and `Entra-sim`.
  Ten local protocol steps pass, but no actual vendor provisioning agent runs.
- `backend/tests/test_oidc.py` intercepts discovery/token/JWKS/userinfo with a mock
  IdP. Real cryptographic checks are useful but are not external-provider traffic.
- `backend/tests/test_saml.py` mocks python3-saml internals. It is not a live
  signed assertion exchange with any named provider.
- `backend/tests/test_auth_magic_link.py` mocks the Resend send call.
- `outputs/production-audit-20260929/121-webhook-worker-proof.json` records zero
  network attempts. The adjacent transport proof is HTTPX MockTransport without
  real TLS or receiver receipt.
- Training JSON named `*-sandbox.json` is authored fixture data; its README says
  the SAP content is not a raw SAP response. Do not infer a vendor-owned sandbox
  from a filename.

Local baseline artifacts remain in
`.gstack/qa-reports/scalecad-paid-qa-2026-10-09/QA-120-main-browser-proof/` and
`outputs/production-audit-20260929/`. Source provenance must be carried forward
when those artifacts are exported to an evidence binder.

## Risks that credentials alone do not solve

1. **Evidence provenance:** `connector_credentials_service.py:383` writes
   `live_readonly` for BOM runs even though that mode label does not establish
   vendor ownership or successful retrieval. Tenant hash, correlation IDs, API
   version and watermark fields exist but are not populated by this writer.
2. **Reconciliation gaps:** canonical normalized hashes and 20 preview rows are
   insufficient to independently reconstruct a complete raw source→saved assembly
   comparison. A fresh test must collect approved, sanitized full snapshots.
3. **Private connectivity:** current transports reject private DNS/IP targets,
   ignore environment proxies and require publicly reachable HTTPS. VPN/private
   CA/proxy-only customer environments need a supported architecture, not a guard
   bypass during testing.
4. **Recovery/scale:** connector recovery is manual. No connector retry queue,
   Retry-After/backoff handling, cursor/checkpoint or incremental sync proof was
   found. Pagination is rejected rather than followed.
5. **SAP scope:** only product/BOM preview is supported. Full hierarchy import,
   demand/actuals sync, write-back and CAD derivatives are absent. Real version,
   alternative/effectivity, phantom/recursive structures and quantity semantics
   still need vendor-source validation before broader support can be promised.
6. **Windchill scope:** exact part iterations and complete unpaginated whole-count
   `ea` structures only. Fractional/non-count units, hidden/unresolved parts,
   large structures and broader metadata/geometry flows are unsupported.
7. **Concurrent imports:** preview hash equality is not a durable server-side
   approval binding. Concurrent assembly replacement, database failure and safe
   retry need explicit acceptance; the connector has no per-assembly idempotency
   key/lock proof.
8. **SSO offboarding:** JIT group mapping grants/promotes; missing groups do not
   demote/deprovision. Real SCIM lifecycle/session/key revocation must be tested
   separately from SSO login.

These are readiness findings. The audit does not silently expand a preview/file
feature into a full synchronization, procurement or certification product.

## Test environments and access

| Target | Environment path | Why it is not running against a vendor yet |
|---|---|---|
| SAP | SAP Business Accelerator Hub API sandbox, then authorized S/4 test tenant | Account/API key plus matching API/selectors and independent expected data needed. Sandbox sample API availability is not whole-customer workflow acceptance. |
| Windchill | Authorized PTC/customer nonproduction WRS instance | No instance, test user, API version, exact root/filter or approved source snapshot supplied. |
| Okta | Integrator Free Plan org with SSO/LCM/SCIM private app | Requires business signup/activation, actual assigned users and app configuration. No new external account or terms acceptance was performed. |
| Entra | Authorized existing test tenant or eligible developer sandbox | Developer sandbox eligibility/licensing is conditional, not universally free. No tenant/app access supplied. |
| PingFederate | Authorized nonproduction instance/trial with approved trust config | No instance/license/admin access supplied. |
| Resend | Existing signed-in account plus dedicated staging sending key and controlled inbox | The signed-in provider dashboard was inspected on 10 October and still showed **Not Started** for the domain and all three required sender records. The current resolver returned none of those records. This is not a global DNS propagation assessment. No sending key was created and no email was sent. |
| Webhooks | Authorized public HTTPS staging receiver with independent HMAC verifier | Local loopback receiver is deliberately rejected by the production transport. Do not relax SSRF/TLS protection to make the test pass. |
| Keycloak | Dedicated local official provider runtime, app, DB, Redis and worker | Independent real software, not a named-vendor sandbox. See `integration-tests/environment/README.md` for tested setup and limits. |

No matching vendor credential variables were populated in the inspected local
process/env locations. GitHub secret-name listing returned HTTP 403; this is an
access limitation, **not evidence that repository secrets do not exist**. Vendor
profiles may live encrypted in another organization; none were present in the
audited owner workspace. Credentials must be entered through protected staging
configuration, not pasted into chat or public evidence.

## Dedicated environment and actual test result

The environment is **running locally**, with its own PostgreSQL, Redis, blob
storage, API, worker and official Keycloak 26.8.0 container. Every listener binds
to loopback. The API reports application source `c5226728`; the frontend uses
Next development mode. No production database, vendor credentials or outbound
email configuration is loaded. Actual container/image digests, project-scoped
volumes, health and secret-file permissions were checked and recorded.

Open `http://localhost:18300/login` for the dedicated environment. Its start,
inspect and non-destructive stop commands are documented in
[`integration-tests/environment/README.md`](../integration-tests/environment/README.md).
Synthetic login credentials stay in the ignored, protected local `.state`
directory and are excluded from the evidence bundle and Git.

**Local Keycloak basic OIDC sign-in: 4/6 = 66.67%.** Configuration/trust,
authentication, basic login and immutable identity reconciliation are demonstrated
for this HTTP loopback target. The real provider recorded two `LOGIN`, two
`CODE_TO_TOKEN` and one `LOGIN_ERROR` events. The actual ScaleCad database contains
one identity and one email account after both logins; its issuer, subject and email
exactly match the independent provider read-back. The browser Account menu showed
the synthetic email and default Viewer role. Sign-out redirected a protected page
to login, and a fresh SSO flow reused the same identity.

The default Viewer role is an application policy, not a tested provider-group
mapping. No group-to-role mapping was configured. Wrong-password rejection and
ordinary sign-out/relogin are retained observations, but **failure handling and
recovery/retry remain NOT_DEMONSTRATED** under the full stage criteria. Provider
outage, malformed/replayed callbacks, tenant boundaries, group/org authorization,
SCIM offboarding and production HTTPS are untested. The local quota UI reported
unavailable, and direct browser navigation to JSON identity endpoints was blocked
by the client; the account UI and independent database read-back establish the
identity result. This is not a claim that every local platform surface passed.

The portable, sanitized evidence bundle is in
[`integration-tests/evidence/2026-10-10-keycloak/`](../integration-tests/evidence/2026-10-10-keycloak/README.md).
The generated [per-workflow matrix](../integration-tests/evidence/matrix.md)
and [machine-readable stage ledger](../integration-tests/evidence/matrix.json)
include the actual reviewed run. **All 18 named-provider/external workflow rows
remain 0/6**, including optional or unadvertised implementations; Keycloak credit
does not transfer to them. The three offline CSV connectors and neutral CAD
interchange are N/A for external connection coverage. Historical mock tests are described above and are not
misrepresented as submitted real-provider receipts.

The evidence scorer's 20 guardrail tests pass, including rejection of mocks,
provider mismatch, tampered/missing artifacts, mixed builds/tenants, incomplete
actions, non-finite JSON and failed reconciliation. Local environment compile,
isolation and read-only identity checks pass. These testing-tool checks are not
additional vendor integration successes.

## Acceptance and evidence required next

For each target, capture approved tenant/provider/version, app commit/image,
timestamps, exact source selectors, request and provider receipt IDs, sanitized
source/result snapshots, complete reconciliation diff, negative-case outcome,
recovery outcome and cleanup/revocation receipt. Hash all artifacts. Keep actual
source data only where authorization permits; public reports contain sanitized
identities/counts/hashes, never credentials or login tokens.

SAP acceptance must compare products/BOM explosion fields to its independently
exported reference without inventing parent edges. Windchill acceptance must
compare every edge/identity/revision/unit/quantity and the final saved graph,
including a source change between preview and import. SSO acceptance must compare
actual provider subject/email/group claims to the exact immutable ScaleCad
identity/org/role. SCIM acceptance must be driven by the actual vendor agent and
prove access is removed after deactivation. Email needs recipient-side receipt
and link consumption, not just an API response. Webhooks need independent TLS
receiver acknowledgement, signature and data checks, real retry and idempotency.

Vendor setup is blocked on named authorized tenants/test users and expected source
data. The local environment and evidence tool provide concrete independent
progress; they do not turn those missing vendor checks green. The prior statement
“Full QA is blocked only on external integration testing” was too broad to convey
the risk. **Core QA repairs are verified; the enterprise integration layer is not
yet production-validated.**

## Official environment references

- [SAP sandbox access](https://developers.sap.com/tutorials/s4sdk-odata-service-cloud-foundry)
- [PTC WRS documentation](https://support.ptc.com/help/windchill/plus/r13.1.2.0/en/Windchill_Help_Center/sublandingpages/WCRESTServices_LP.html)
- [Okta Integrator Free Plan](https://developer.okta.com/docs/reference/org-defaults/)
- [Okta private SCIM integration](https://developer.okta.com/docs/guides/scim-provisioning-integration-connect/)
- [Microsoft developer sandbox eligibility](https://learn.microsoft.com/office/developer-program/microsoft-365-developer-program)
- [Keycloak official Docker runtime](https://www.keycloak.org/getting-started/getting-started-docker)
- [Cloudflare dummy-key testing boundary](https://developers.cloudflare.com/turnstile/troubleshooting/testing/)
- [Resend domain verification](https://resend.com/docs/add-a-domain)
