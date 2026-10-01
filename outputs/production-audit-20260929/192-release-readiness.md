# Frozen release candidate — readiness and remaining decisions

The user proposed ending audit expansion and deploying. Feature work is frozen at `07d56ea0a622d27a3eab0efe0227d74c1a8bb140` (engine 0.3.47). This document does not certify every feature or authorize deployment.

## Candidate and tests

The candidate's full local backend suite passed 2,839 tests, with three recorded environment skips. Its unchanged frontend retains 528 passing tests, type checking, scoped lint and a production build. Real STEP disk/bar proofs, independent arithmetic and immutable-record checks are in `190-checks.json` and `190-cylinder-fit-proof.json`.

The published PR head is still `7bcec0a`; CI run36878250012 is terminal: eight jobs pass, including Browser E2E, and the container security job fails on the five recorded HIGH findings. The receipt is in `ci-36878250012-summary.json`. Publish the frozen product changes with these release notes, then obtain CI for that exact revision. Documentation-only packaging does not alter the validated product source.

## Current Render baseline, rechecked 2026-10-01

Authenticated native dashboard inspection confirms web, API and worker are deployed on `09555c18121305b7e577c0a76e47e5f97abfb8e8`. Public API health at15:16:26UTC agrees and reports PostgreSQL, Redis and the worker healthy. It also reports `version: dev` and `worker_strict: false`. See `192-production-health.json` and `192-render-inventory.json`.

Recorded rollback targets:

- API: `dep-dau1e07avr4c73faj84g`.
- Worker: `dep-dau1e27lk1mc73dai7og`.
- Web: `dep-dau1dtmk1f9s73a070r0`.

Use the existing manual deployment controls. Reconnecting GitHub is a separate automation improvement and is not a prerequisite for the previously working manual public-repository deployment path. No new repository access grant is proposed for this release.

API key inventory has20 entries, worker19 and web5; no linked environment groups. API/worker still lack RELEASE. API lacks SESSION_SECRET and AUTH_MODE. The two non-secret signup flags were read directly: PUBLIC_PASSWORD_SIGNUP_ENABLED=true and PRODUCTION_VERIFIED_SIGNUP_REQUIRED=false; both were concealed again. No credential value was displayed, copied or changed.

Before rollout, securely provide a strong SESSION_SECRET, explicitly select the intended password auth mode, and set the approved release identity on API/worker/web. A read-only command in the running API confirmed that the existing dashboard signing key is strict-base64, at least32 decoded bytes, with at least8 distinct bytes. Its value was never output. This is a format/length/diversity check, not proof of secret randomness or cross-service equality. Preserve the key and validate complete candidate startup. Check worker heartbeat and enable strict health. Validate startup against the complete candidate configuration before serving traffic. Setting RELEASE alone would refuse startup with the current missing session key/default Google configuration. Do not disable enforcement to make deployment pass. Connector/proxy encryption settings and any enabled external providers require their own complete configuration; unsupported features remain documented limitations.

Migrations0047_ground_truth_units and0048_disposition_basis are additive. Confirm the production schema and backup/restore path before migration. Retain the three rollback targets and do not delete historical records or downgrade away new data.

## Five security findings: three distinct CVEs

The exact preceding-image scan fails on libexpat1, libx11-6, libx11-data, libx11-xcb1 and libxrender1. There are five HIGH and zero CRITICAL findings. No finding has been waived. A read-only production `dpkg-query` confirms the same five installed library versions as the candidate scan; the API runtime has no DISPLAY value. See `192-production-readiness-check.txt`. These observations support a bounded risk review, not a blanket non-exploitability claim.

| CVE | Current evidence | Release decision still needed |
| --- | --- | --- |
| CVE-2026-93990 | Debian lists the installed trixie Expat2.8.3-1~deb13u1 as vulnerable; fixes exist in other Debian releases. Malformed UTF-16 can alter XML interpretation. | A distro upgrade alone has no currently listed trixie fix. Prove a tested remediation or explicitly review residual risk; do not claim non-reachability from absence of direct app imports. |
| CVE-2026-88806 | Debian lists trixie libX11 as vulnerable and classifies it no-dsa/minor. Exploitation requires a malicious X server. The app's inspected gmsh paths do not invoke its GUI. | The headless call pattern reduces the apparent exposure but is not a complete runtime non-reachability proof. |
| CVE-2026-88807 | Debian lists trixie libXrender as vulnerable and no-dsa/minor. Exploitation requires a malicious X server. | Same runtime qualification as libX11; no silent suppression or claim that the package is fixed. |

Sources: [Debian Expat record](https://security-tracker.debian.org/tracker/CVE-2026-93990), [Debian libX11 record](https://security-tracker.debian.org/tracker/CVE-2026-88806), [Debian libXrender record](https://security-tracker.debian.org/tracker/CVE-2026-88807). Checked2026-10-01. Source inspection is not a substitute for actual candidate-image testing.

## Public acceptance after the approved deployment

Require matching source identities and healthy strict worker status, then exercise signup, incorrect/correct password login, logout/relogin, actual STEP/STP upload, numerical controls, saved records/reload, report downloads, batch/worker completion and failure recovery. Verify the served frontend and worker are the same release as the API. Roll back if the essential flows regress.

Publish known limitations: prices are assumption-based, owned-machine delivery capacity needs further validation, some geometry cases remain unresolved, and real email/company identity/vendor/customer outcomes have not been proved. A controlled release is not an all-feature certification.
