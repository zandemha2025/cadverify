# Identity certification readiness — OIDC RP + SCIM 2.0 PATCH

Date: 2026-07-08
Scope: Rung A of the connector ladder — enterprise identity (SSO + provisioning).
Author: build agent (worktree `worktree-agent-a2e121ed625a68dc9`, off baseline `claude/resume-review-oxqw0l` @ 7a3d7f8).

This document states, without overclaiming, what the identity surface now
supports, which conformance tests actually pass (with the real commands and
counts that were run), and what remains an EXTERNAL GATE.

---

## 1. What is now supported

### 1.1 OpenID Connect Relying Party (NEW — `backend/src/auth/oidc.py`)

A greenfield OIDC RP mounted at `/auth/oidc`, gated on `AUTH_MODE ∈ {oidc,
hybrid}`, parallel to the existing SAML SP. It lands users in the SAME
session + org + group-assignment model SAML uses — it does not fork a second
identity model.

- **Authorization Code flow with PKCE (S256).** `state`, `nonce`, and a PKCE
  `code_verifier`/`code_challenge` are generated at `/login`, stashed in the
  signed Starlette session, and verified at `/callback`. State is single-use
  (popped on use) and expires after 600s — unknown/expired/replayed state is
  rejected (`oidc_bad_state`).
- **OIDC discovery + JWKS.** `/callback` fetches the `.well-known/openid-
  configuration` document (with an RFC 8414 issuer-match check) and the
  advertised `jwks_uri`, and uses the fetched RSA keys to verify the
  `id_token` signature (RS256). JWKS is fetched fresh per callback, so a key
  rotation at the IdP is picked up without restart.
- **id_token validation.** `iss`, `aud`, `exp`, `iat` are validated via
  authlib claim options + `validate()`; `nonce` is checked against the value
  minted at `/login`. Any signature/claim failure is a 400 (`oidc_invalid_token`
  / `oidc_bad_nonce`), never a 500.
- **userinfo fallback.** When the id_token claims are thin (no email, or no
  groups), the RP fetches the `userinfo` endpoint with the access token and
  merges `email` (incl. Entra's `preferred_username`/`upn`) and the groups
  claim.
- **Identity reuse.** Provisioning mirrors `saml._saml_provision_user`
  (`upsert_user(auth_provider="oidc")` + default-key minting only when the
  account has none). Group→role assignment reuses
  `org_saml_service.apply_saml_group_assignment` — the OIDC `groups` claim is
  passed in as the assertion-attribute map, so the per-org `SamlGroupMapping`
  rows govern OIDC identically to SAML. No new table or migration was added.
- **Config surface (env-driven, parallel to SAML).** `OIDC_ISSUER`,
  `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` (optional; PKCE-only public clients
  omit it), with optional `OIDC_DISCOVERY_URL`, `OIDC_REDIRECT_URI`,
  `OIDC_SCOPES`, `OIDC_GROUPS_CLAIM` overrides. Documented in
  `backend/.env.example`. `AUTH_MODE` production guard widened to admit `oidc`.

### 1.2 SCIM 2.0 PATCH hardening (`backend/src/services/scim_service.py`)

`patch_user` and `patch_group` were brought to real RFC 7644 §3.5.2
conformance. Previously `patch_user` ignored the `op` verb and only branched on
`path`; `patch_group` handled member add/remove but no filtered path
expressions.

- **`op` verbs honored:** `add` / `replace` / `remove` for user `active`,
  `roles`/`orgRole`, `name` (accepted, no-op — no dedicated column), `emails`,
  and group `members`.
- **Filtered path expressions:** `members[value eq "123"]` (Okta's canonical
  member removal — id lives in the filter, no value body) and value-path forms
  like `emails[type eq "work"].value`. A small, explicit grammar
  (`_parse_patch_path`) parses attribute + `[attr eq "val"]` filter +
  `.subAttr`.
- **Vendor shape tolerance:** case-insensitive attribute names and `op` verbs;
  both pathed ops (Okta) and pathless whole-value ops with a value object
  (Entra); boolean coercion of Entra's stringy `"True"`/`"False"`.
- **Malformed → SCIM 400, never 500:** unknown `op` → `invalidSyntax`;
  unparseable/unknown path → `invalidPath`; non-boolean `active` or non-numeric
  member id → `invalidValue`; missing `Operations` → `invalidSyntax`. All
  emitted as the SCIM Error schema body.
- **`replace` on group members** reconciles to the exact listed set (adds
  newcomers, removes the absent).
- **Preserved invariants:** last-admin protection (409 `mutability` on
  demoting/deprovisioning the sole admin) and the deprovision semantics
  (`active=false` removes org membership, persists the SCIM identity inactive,
  bumps `session_version`) are unchanged and covered by tests.

---

## 2. Conformance tests that pass (real runs, real counts)

All commands run from `backend/` with the project venv
(`/home/user/cadverify/backend/.venv`). The Postgres runs used the dedicated
DB `postgresql://postgres@127.0.0.1:5433/cadverify_identity`, migrated to head
with `alembic upgrade head` (schema at `0035_connector_credentials`).

### 2.1 Full SQLite suite (DoD #1)

```
$ .venv/bin/python -m pytest -q
1389 passed, 92 skipped, 6 warnings in 100.95s
```

(Baseline before this packet: 1371 passed, 84 skipped. The +8 skipped are the
Postgres-gated identity tests, which skip without a Postgres `DATABASE_URL`.)

### 2.2 Postgres-gated identity subset (DoD #2)

```
$ DATABASE_URL=postgresql://postgres@127.0.0.1:5433/cadverify_identity \
    .venv/bin/python -m pytest -k "scim or saml or oidc or org_membership"
76 passed, 1405 deselected, 1 warning in 9.83s
```

(Baseline before this packet, same DB migrated to head: 50 passed.)

### 2.3 New identity conformance tests (the ones this packet adds)

Run against Postgres so the DB-backed cases execute (not skip):

```
$ DATABASE_URL=postgresql://postgres@127.0.0.1:5433/cadverify_identity \
    .venv/bin/python -m pytest -q \
    tests/test_oidc.py tests/test_scim_patch_conformance.py \
    tests/test_scim_service.py tests/test_scim_api.py
34 passed, 1 warning
```

Breakdown:

| File | Count | What it proves |
|------|------:|----------------|
| `tests/test_oidc.py` | 11 | Happy path (authz redirect → callback → token exchange → verified id_token → provisioned session) for **Okta-shaped** (groups in id_token) and **Entra-shaped** (thin id_token → userinfo fallback) claim sets; negatives: bad state, bad nonce, expired token, wrong aud, tampered signature, JWKS rotated away, positive re-verify after rotation, IdP authz error; plus one **live-Postgres end-to-end** with REAL `upsert_user` + API-key mint + group→role via `SamlGroupMapping` (no provisioning mocks). |
| `tests/test_scim_patch_conformance.py` | 15 | Pure-unit PatchOp path grammar + bool coercion + malformed→SCIM-400; live-PG replay of REAL Okta (`replace active=false`, filtered `members[value eq …]` removal) and Entra (pathless `replace` value object, stringy bool, value-list member removal) payloads; value-path email update; malformed-op 400 matrix (invalidSyntax/invalidPath/invalidValue); last-admin protection preserved. |
| `tests/test_scim_service.py` | 4 | Pre-existing SCIM discovery/serialization contract (still green). |
| `tests/test_scim_api.py` | 4 | Pre-existing SCIM router/auth-boundary contract (still green). |

### 2.4 How the OIDC flow is proven with zero network egress

`tests/test_oidc.py` stands up a **local mock OIDC provider** (`MockIdP`): an
in-process RSA keypair, a fixture discovery document + JWKS, and RS256-signed
id_token minting (with key rotation). The RP reaches it through its **normal
httpx calls**, intercepted by `respx` — nothing touches the network and there
is **no test-only bypass in the production code**; the issuer is simply pointed
at the mock via ordinary `OIDC_*` config. The negative paths mint deliberately
broken tokens (expired, wrong aud, tampered signature, unknown kid) and assert
the 400s.

---

## 3. Real vs EXTERNAL GATE

### Real (proven here, in this container, zero egress)

- OIDC Authorization Code + PKCE (S256) end-to-end, incl. discovery + JWKS
  fetch, RS256 signature verification against fetched keys, iss/aud/exp/iat/
  nonce validation, userinfo fallback, and all listed negative paths — against
  a local mock IdP and Okta-/Entra-shaped fixture claim sets.
- Real user provisioning + group→role assignment through the shared
  `SamlGroupMapping` table, exercised against real Postgres tables.
- SCIM 2.0 PATCH conformance (RFC 7644 §3.5.2) for user `active`/`roles`/
  `emails` and group `members`, replaying REAL Okta and Entra PATCH payload
  shapes, with SCIM-shaped 400s and preserved last-admin/deprovision semantics,
  against real Postgres tables.
- Full SQLite suite and the Postgres identity subset both green (§2).

### EXTERNAL GATE (NOT done here — requires a tenant + network egress)

- **Live certification against a real Okta / Entra / Ping tenant has NOT been
  performed.** It requires a real IdP tenant, real client credentials, and
  network egress to the tenant's discovery/JWKS/token/userinfo endpoints — none
  of which exist in this zero-egress container. What is proven is
  **standards-conformance against a local mock IdP + real-world payload
  fixtures**, not interop against a specific live tenant.
- **Okta / Microsoft app-listing certification** (Okta OIN, Entra gallery /
  SCIM validator) is an external submission-and-review process and has not been
  started.
- **SCIM validated against the live Okta/Entra provisioning agents** (as
  opposed to their documented payload shapes replayed as fixtures) is likewise
  external-gated on a tenant.

### Honesty notes / deviations

- The packet brief described the baseline as tip `7a3d7f8` but the worktree was
  created from the merge-base `17acf61` (12 commits behind), which lacked the
  SCIM code. The branch was fast-forwarded to `7a3d7f8` (a clean fast-forward;
  the branch had no unique commits) so the real SCIM baseline was present before
  any change.
- The dedicated Postgres DB was empty on arrival; it was migrated to head
  (`alembic upgrade head`, existing migrations only) before running the
  Postgres-gated suite. **No new migration was added** — OIDC reuses the
  existing user/membership/`SamlGroupMapping` schema, so there is nothing new to
  reverse.
- `name` PATCH ops are accepted as a no-op because there is no dedicated name
  column (the SCIM `name.formatted` is derived from the email); this is stated
  rather than silently dropped.
