# Production deploys (Render: web + api + worker)

Verified 2026-11-14. The three live services, all deployed from this repo on
Render, all with auto-deploy **off**:

| Service | Render id | Plan |
| --- | --- | --- |
| `cadverify-web` (scalecad.ai) | `srv-daiqvcrm8hqs73duucd0` | Starter 1 CPU / 2 GB |
| `cadverify-api` | `srv-daibaifqj5pc739cvas0` | Starter 1 CPU / 2 GB |
| `cadverify-worker` | `srv-dajgag0ae00c739s91h0` | Starter 2 CPU / 4 GB |

## One command, one commit

```
scripts/deploy_prod.sh            # deploys origin/main's tip to all three
scripts/deploy_prod.sh <sha>      # any commit that is on origin/main
```

It deploys worker → api → web (the worker first, so it never lags the API
that enqueues onto it), then verifies `GET /api/health` until `build_id`
equals the deployed SHA with `status: ok` and a live worker heartbeat, and
that the web answers 200. `/health`'s `version` field reports the same
`build_id` (`backend/src/api/health.py`), so a stale deploy is visible in the
API itself — this is how the Nov 2 frontend / Oct 24 API drift was caught.

Before deploying, the script prints each service's current **live deploy ID
and commit** — the rollback anchor. Rolling back is
`render deploys create <service> --commit <old-sha>` (or the dashboard's
Deploy button on that row). The old API image is kept by Render for this.

## Why auto-deploy stays off

Render's auto-deploy triggers per service when a push touches the repo, so
the three services roll at different times — exactly the partial-version
window the atomic script exists to close. Migrations run in the API image's
CMD before it binds (`backend/Dockerfile`); an auto-deployed worker can start
against a not-yet-migrated schema. `main` has received pushes whose CI later
failed, and a rollback pin ("deploy exactly this SHA to all three") is much
harder to state when deploys also follow every push. If push-to-deploy is
wanted later, prefer Render's "After CI passes" mode on all three services —
it still deploys them one by one, so pair it with the `/health` `build_id`
check, which the script already models.

## The health contract

`GET https://cadverify-api.onrender.com/health` reports `build_id`
(`RENDER_GIT_COMMIT` et al.), `status`, `postgres`, and
`async.worker` (the ARQ worker's heartbeat). `/health/deep` additionally
proves the CAD runtime (gmsh) and the check pipeline load. Verify a deploy
with: same `build_id` on every deploy listed by `render deploys list`, health
ok, and the version field equal to `build_id`.

## Render one-off jobs run the start command with no shell

A Render **one-off job** executes its start command directly — not through a
shell. `cd backend && python …` or anything with `&&`, `;`, `>` silently
fails (observed 2026-11-13: a job "succeeded" doing nothing). Use
`python3 -c "…"` with everything inlined, or `python3 -m …` with the working
directory set on the service. Job logs are not reliably surfaced through the
Render logs API; test the command first against the same image locally.

## Operator access to production data

The worker's environment (read with the Render CLI: `render env-vars list`)
carries `DATABASE_URL` with the external hostname — both services point at
the same database. Staff operations that touch accounts go through the
audited scripts, never raw SQL: plan changes use
`backend/scripts/set_plan.py` (writes a `user.plan_changed` audit row, actor
"staff script"). Keep the connection string out of shells, logs and
terminals.

## E2E smoke accounts

Users 50/51 (plus the work-tier signup) are permanent smoke accounts on
production. The full live pass is
`scripts/e2e/live-production-capability-pass.mjs` — real browser, real UI
(signup/login/uploads/exports/share links), API used read-only for parity
assertions:

```
node scripts/e2e/live-production-capability-pass.mjs            # full pass
ONLY=login-pilot,share-link-lifecycle node …                    # one phase
EXPECT_TOLERANCES=1 node …                # after an OCP/PMI deploy: require
                                           # the Specs PMI block on NIST CTC-01
```

It writes `/tmp/scalecad_live_receipt.json` and screenshots under
`/tmp/live-pass-*`. Note the allowance behaviour while using it
(`docs/operations/free-checks.md`): the personal account's 3 lifetime checks
are spent by the first full run (afterwards its phase verifies the
out-of-checks paywall), and an abandoned in-flight check holds its slot for
`CHECK_LIFETIME` (1 hour) before releasing it.
