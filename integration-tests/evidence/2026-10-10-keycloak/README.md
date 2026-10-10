# Actual local Keycloak basic OIDC evidence — 10 October 2026

This is a sanitized capture from a separately running official Keycloak 26.8.0
container and actual ScaleCad API, browser and PostgreSQL database. It is not a
mock or a named-vendor sandbox. Application source:
`c52267285f622237250306b81ae24db1da1759c9`.

The reviewed result is **4/6 (66.67%)** for basic HTTP-loopback OIDC sign-in only.
No Okta, Entra, PingFederate, SAP, Windchill or production credit is implied.
See `operator-review.json` for the actual observations and untested boundaries.

- `keycloak-provider-receipts.json`: independently read actual provider client,
  realm, synthetic user, groups and login/code-exchange events. Secrets, tokens,
  session IDs and authorization codes are excluded.
- `environment-status.json`, `isolation-verification.json`: served app build,
  actual healthy services, runtime digests and isolated bindings/volumes.
- `scalecad-identity-reconciliation.json`: read-only actual database rows and
  audit events; one immutable identity/account after two logins.
- `source-identity.json`, `result-identity.json`, `identity-diff.json`: separate
  issuer/subject/email projections and zero missing/extra/changed fields.
- `account-identity.txt`, `account-identity.png`: actual signed-in browser UI.
- `logout-protected-page.txt`: actual protected-page redirect after sign-out.
- `tenant-manifest.json`, `actual-run.json`: reviewed scope and artifact hashes.

Viewer is ScaleCad's default user policy. The new account also owns its freshly
created workspace; this does not represent a provider group/organization mapping.
No enterprise group mapping or offboarding was tested. A rejected password and
repeat login do not satisfy the full failure/recovery gates, which remain
NOT_DEMONSTRATED. No claim is made that every local platform surface passed.

Recompute from the repository root:

```sh
python3 integration-tests/readiness.py \
  --artifact-root integration-tests/evidence \
  --evidence integration-tests/evidence/2026-10-10-keycloak/actual-run.json \
  --output-json integration-tests/evidence/matrix.json \
  --output-markdown integration-tests/evidence/matrix.md
```

Evidence paths in the matrix are relative to `integration-tests/evidence`.
Hashes protect supplied bytes, not provider provenance; the operator separately
reviewed actual runtime, browser, provider and database observations. Synthetic
test credentials and raw service logs remain protected and ignored locally.
