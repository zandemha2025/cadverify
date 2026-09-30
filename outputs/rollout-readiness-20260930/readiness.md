# Parallel rollout readiness — 2026-09-30

The rollout is not complete. This branch isolates applicable fixes from the active production audit and preserves the external-evidence and security gates.

## Scope and coordination

- Base: PR #107 at `772f3b56233789b036dba1f16c0bc77613043db1`.
- Worktree: `/Users/nazeem/.codex/worktrees/1dfc/cadverify`; branch `codex/rollout-readiness-20260930`.
- The active audit chat retains its BOM demand, portfolio, part-context, Verify/Programs, and production audit work. Its working files, processes, database and branch were not changed here. The user authorized direct coordination; lane ownership was sent to that chat.
- Parallel ownership: container security evidence; SAP read/preview contract; manufacturing-process calibration evidence. This report tracks the remaining service/release work.
- Local integration tests use a separate PostgreSQL cluster on 55431 and Redis on 6398. Existing Python dependencies are executed read-only; frontend dependencies are installed in this worktree.

## External services

| Gate | Observed evidence | Required next evidence |
| --- | --- | --- |
| Email login/invitations | No Resend key, sender or controlled inbox configured in this shell/worktree or the existing audit's local runtime configuration. A scoped search of connected Gmail found no matching recent CadVerify/ProofShape receipt; absence from that search is not proof of delivery failure. | Authorized receiving inbox and configured provider; actual receipt, one-time link exchange, invite acceptance, expiry/reuse refusal. No messages were sent in this effort. |
| Company sign-in and SCIM | Local SAML/OIDC and transport regressions pass; these use controlled fixtures, not a company tenant. No IdP credentials configured in inspected local runtime. Deployed OIDC status route returns404. | Existing pending IdP tenant access, successful org/role assignment, session/logout, provisioning and revocation. |
| SAP | Product probe already exists; SAP lane owns the BOM read contract. | Authorized tenant, exact API metadata/selectors and known assembly reconciliation. An API-shaped test is not a vendor pass. |
| Windchill | Prior complete BOM preview/import implementation and isolated HTTP contract checks pass. | Authorized tenant, exact part iteration/navigation criteria, complete structure/count/quantity reconciliation, successful preview/import and change/restriction refusal. |

No secrets or vendor payloads were copied into this report. Credentials should use existing secure configuration and credential-profile surfaces. The other chat has already requested the missing accounts; those questions remain pending.

A read-only transaction against the existing local audit database found two SAP credential profiles and three Windchill profiles, all revoked. No profile was decrypted or used. This confirms the absence of an active saved vendor credential in that local environment; it does not inventory production secrets.

## Production and release

Read-only public probes at 22:34 UTC returned HTTP200 for the login page and backend health. Health identifies deployed build `09555c18121305b7e577c0a76e47e5f97abfb8e8`, PostgreSQL/Redis true, worker okay, worker strict-health false, reconstruction unavailable, and version `dev`. This is an availability baseline, not acceptance of the later fixes. Receipt: [production-baseline.json](production-baseline.json).

Upstream [CI36779785629](https://github.com/zandemha2025/cadverify/actions/runs/36779785629) completed with eight successful jobs and one failed container job. Its branch head is772f3b5; its built PR merge SHA is2622bbe861b9ff0889d53e8c5b0535ccf0ca86ee. Neither proves later changes. Receipt: [upstream-ci.json](upstream-ci.json).

The failed gate is five HIGH Debian package findings with no supported stable fixes currently published. Actual-image STEP parsing and frontend startup passed. See [security-review.md](security-review.md) and its source-bound SBOM/scan evidence. No waiver, scanner relaxation or package deletion was applied.

Before rollout: integrate the parallel changes with the active audit's latest work, obtain passing checks on that exact revision, resolve the image security gate, and complete the pending production repository/configuration access. The prior chat's PR107 merge/deploy decision remains pending. Final production acceptance must exercise the released revision: login/session, real STEP and known dimensions, cost/record/export consistency, BOM demand, role boundaries, worker jobs and error recovery. Real-service and supplier-quote gates remain separate from these application checks.

## Local checks

At the upstream baseline, isolated identity/connector/release tests passed122 with one explicit PostgreSQL-dependent OIDC test skipped;14 release-evidence runner checks passed. The later combined run below must supersede this limited baseline for changed code. Details: [baseline-checks.json](baseline-checks.json).

Final change-specific results and review are recorded in [accuracy.md](accuracy.md) and [sap.md](sap.md), with the combined verification receipt added after the parallel work finishes. No local result is a claim that the branch is live or that real suppliers have validated its estimates.
