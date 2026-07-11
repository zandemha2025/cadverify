# CadVerify Go-Live Runbook

Authoritative, sequenced, copy-paste procedure for the first production launch
(10 orgs: oil & gas, automotive, aerospace/defense, job-shops). Password +
magic-link auth, Fly.io (`cadvrfy-api` + `cadvrfy-web`) + Neon Postgres + Redis.

Every command below is grounded in a specific file in this repo — the citation
after each command is the source of truth, not decoration. Where this document
could not be verified against the repo (no live Fly/Neon/Resend account in
this session), it says so explicitly instead of guessing.

Legend: **[FOUNDER]** = you must do this by hand with your own credentials.
**[AUTOMATED]** = CI or a script in this repo does this for you.

---

## 1. Prerequisites (founder must provide)

| # | What | Where to get it | Used for |
|---|---|---|---|
| 1 | Fly.io account + `flyctl` installed and logged in (`fly auth login`) | https://fly.io, `brew install flyctl` / https://fly.io/install.sh | Hosting both apps |
| 2 | A GitHub Actions repository secret `FLY_API_TOKEN` | `fly tokens create deploy` (or `fly auth token`), then add it under repo **Settings → Secrets and variables → Actions** | CI's `deploy` and `docker-build` jobs read `secrets.FLY_API_TOKEN` (`.github/workflows/ci.yml:378,417,431,437,448`) |
| 3 | A Neon Postgres project, with **both** a pooled and a direct connection string | https://neon.tech → your project → Connection Details (toggle "Pooled connection" on/off gives you the two URLs) | `DATABASE_URL` (pooled) + `DATABASE_URL_DIRECT` (direct, used only by the migration `release_command`) |
| 4 | A Redis instance (Upstash Redis, or `fly redis create`) | https://upstash.com, or `fly redis create` | `REDIS_URL` — arq job queue, rate limiting, magic-link tokens, `/health` async probe |
| 5 | A Resend account: API key + a verified sending domain/address | https://resend.com → API Keys, and → Domains (verify your sending domain first or sends will fail) | `RESEND_API_KEY`, `RESEND_FROM` |
| 6 | A Cloudflare Turnstile widget + secret key | https://dash.cloudflare.com → Turnstile → Add widget | `TURNSTILE_SECRET` (backend, `src/auth/turnstile.py:34` — **not** `TURNSTILE_SECRET_KEY`, see the callout in §3) |
| 7 | Your production domain for the frontend | Your registrar / DNS | `DASHBOARD_ORIGIN` |
| 8 | *(Recommended)* An S3 bucket + IAM credentials | AWS Console (or MinIO/R2/B2) | Durable object storage — see §4 for why this matters and a required code change |
| 9 | *(Recommended)* A Sentry account + project(s) | https://sentry.io | Error reporting — see §3's Sentry subsection, it has a real gotcha |

---

## 2. Provision the Fly apps

Both `backend/fly.toml` and `frontend/fly.toml` already declare `app = "cadvrfy-api"` / `app = "cadvrfy-web"` and `primary_region = "iad"` (`backend/fly.toml:1-2`, `frontend/fly.toml:1-2`), so use `fly apps create`, not the interactive `fly launch` wizard (which would try to generate a new fly.toml and fight the checked-in one).

```bash
# [FOUNDER] — one-time, run from anywhere
fly apps create cadvrfy-api
fly apps create cadvrfy-web

# [FOUNDER] — the backend mounts a volume at /data (backend/fly.toml:44-48):
#   [[mounts]] source = "cadverify_data" destination = "/data" initial_size = "1gb"
# Create it BEFORE the first deploy, matching that source name and region:
fly volumes create cadverify_data --app cadvrfy-api --region iad --size 1
```

If you provision Neon/Upstash in a different region than `iad`, that's fine functionally, but pick something geographically close to `iad` to keep latency down — the region alignment isn't enforced anywhere in this repo, it's just good practice.

---

## 3. Secrets

### 3a. Generate + set the random ones **[AUTOMATED generation, FOUNDER runs the output]**

```bash
bash scripts/ops/gen-launch-secrets.sh
```

This prints ready-to-paste `fly secrets set --app cadvrfy-api ...` lines with freshly generated values for `SESSION_SECRET`, `DASHBOARD_SESSION_SECRET`, `API_KEY_PEPPER`, `MAGIC_LINK_SECRET`, `CONNECTOR_SECRET_KEY`, `CONNECTOR_FINGERPRINT_KEY`, plus commented placeholders for every external secret below. Nothing it generates is written to a file or sent anywhere by the script itself — it only prints to stdout. Treat the output like a credential file once you save it anywhere.

Note on `CONNECTOR_SECRET_KEY` specifically: it must be a valid **Fernet** key (`src/services/connector_credentials_service.py:43-54` calls `Fernet(key)` and raises if it isn't), which is stricter than plain base64 — the script generates it with the correct URL-safe alphabet so this doesn't surprise you later.

### 3b. The complete required-secret list

This is the exact list `scripts/ops/fly-required-secrets-gate.mjs:31` checks (and what CI's `deploy` job runs as a gate, `.github/workflows/ci.yml:428-432` — **the deploy fails, on purpose, if any of these are missing on the Fly app**, so a merge to `main` won't silently ship a half-configured backend):

| Secret | Source |
|---|---|
| `DATABASE_URL` | Neon (pooled) — §1.3 |
| `DATABASE_URL_DIRECT` | Neon (direct) — §1.3 |
| `REDIS_URL` | Upstash/Fly Redis — §1.4 |
| `SESSION_SECRET` | generated |
| `DASHBOARD_SESSION_SECRET` | generated |
| `API_KEY_PEPPER` | generated |
| `CONNECTOR_SECRET_KEY` | generated (Fernet key) |
| `CONNECTOR_FINGERPRINT_KEY` | generated |
| `MAGIC_LINK_SECRET` | generated |
| `RESEND_API_KEY` | Resend — §1.5 |
| `RESEND_FROM` | Resend — §1.5 |
| `DASHBOARD_ORIGIN` | your domain — §1.7 |
| `TURNSTILE_SECRET` | Cloudflare Turnstile — §1.6 |

**Naming gotcha (real, already tripped once):** the backend reads `TURNSTILE_SECRET` (`src/auth/turnstile.py:34`), but the root `.env.example` and `frontend/.env.example` reference `TURNSTILE_SECRET_KEY` in places — that name is wrong for this purpose and the gate script's own comment (`scripts/ops/fly-required-secrets-gate.mjs:18-23`) calls this out explicitly. Use `TURNSTILE_SECRET`. Getting this wrong won't fail `fly deploy` — it fails invisibly and only 500s on the first real magic-link send, exactly the failure mode the gate script exists to catch *before* that.

Set them all with `fly secrets set --app cadvrfy-api KEY=value ...` (batch multiple per invocation to avoid multiple redundant machine restarts).

### 3c. Sentry — read this before setting anything

Sentry is already wired end-to-end in this repo (see §11 below for what changed this session) and is a complete no-op when unset. Two different env vars, two different mechanisms:

- **Backend** (`SENTRY_DSN`, `backend/main.py:250-258`): a plain `fly secrets set --app cadvrfy-api SENTRY_DSN=...` works. It's read live from `process.env`/`os.getenv` at request time.
- **Frontend** (`NEXT_PUBLIC_SENTRY_DSN`, `frontend/instrumentation-client.ts` + `frontend/sentry.server.config.ts`): **a Fly secret is NOT enough for the browser half.** Next.js inlines `NEXT_PUBLIC_*` variables into the client-side JavaScript bundle at `next build` time — verified empirically this session by building the frontend with and without the variable set and inspecting the compiled `.next/static` output. A value set only via `fly secrets set --app cadvrfy-web` is available at container *runtime*, which is *after* the image (and its frozen browser bundle) was already built in CI. Setting it that way would silently leave browser-side error reporting permanently disabled no matter what you configure afterward.

  To actually turn on browser-side Sentry: add a **GitHub Actions repository secret** named `NEXT_PUBLIC_SENTRY_DSN` (Settings → Secrets and variables → Actions → New repository secret). `.github/workflows/ci.yml`'s "Build frontend production image and push on main" step now passes it as a Docker build-arg, and `frontend/Dockerfile` threads it into `next build` (`ARG NEXT_PUBLIC_SENTRY_DSN=""` → `ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN` → `RUN npm run build`). If you deploy manually instead of via CI (§5), pass `fly deploy --build-arg NEXT_PUBLIC_SENTRY_DSN=<dsn>` explicitly or the browser bundle will bake in an empty value.
  - Leaving it unset anywhere is completely safe — both the client and server Sentry inits are gated on `enabled: !!NEXT_PUBLIC_SENTRY_DSN`, and the frontend build/test suite was re-verified green with the wiring in place either way (§11).

---

## 4. Object store — durability recommendation

The default backend is a single Fly volume (`OBJECT_STORE_BACKEND` unset → `local`, `backend/src/storage/factory.py:26-27,40-46`, root cause `BLOB_STORAGE_PATH=/data/blobs` in `backend/fly.toml:27`). That volume holds every uploaded CAD file, mesh, and rendered PDF for all 10 orgs — it is **a single point of data loss** with no built-in replication; if that volume is destroyed, those blobs are gone (database rows may reference files that no longer exist).

**Recommended for launch:** `OBJECT_STORE_BACKEND=s3` with a real S3 (or S3-compatible) bucket, using `backend/src/storage/s3.py`. Required secrets/env when you opt in:

```bash
fly secrets set --app cadvrfy-api \
  OBJECT_STORE_BACKEND=s3 \
  AWS_ACCESS_KEY_ID=<from your IAM user> \
  AWS_SECRET_ACCESS_KEY=<from your IAM user> \
  OBJECT_STORE_S3_BUCKET=<your-bucket-name> \
  OBJECT_STORE_S3_REGION=<e.g. us-east-1>
  # OBJECT_STORE_S3_ENDPOINT is only for a non-AWS S3-compatible provider
  # (MinIO/R2/B2) — omit it for real AWS S3.
```

**`boto3` is now in the production image** (`backend/requirements.txt` lists `boto3>=1.34.0`; `S3ObjectStore._client()` still imports it lazily so the `local`-backend default never loads it). So S3 works out of the box: set the secrets above and flip `OBJECT_STORE_BACKEND=s3` — no code change needed. (It flows through CI's `pip-audit` security-scan like any other dependency.)

If you stay on the local-volume default, that's a legitimate launch choice — just know the durability tradeoff and make sure §7 (Neon PITR, restore drills) is in place, and set a calendar reminder to move to S3 before the volume becomes the thing an incident report blames.

---

## 5. Deploy

**[AUTOMATED]** The normal path: merge your branch to `main`. `.github/workflows/ci.yml`'s `deploy` job (gated on `needs: [backend, frontend, browser-e2e, docker-build]`, i.e. it only runs after every other CI job is green) then:

1. `flyctl deploy --config backend/fly.toml --image registry.fly.io/cadvrfy-api:<sha> --env RELEASE=<sha>` (`.github/workflows/ci.yml:410-417`) — this runs the Alembic migration automatically via `[deploy] release_command = "sh -c 'DATABASE_URL=$DATABASE_URL_DIRECT alembic upgrade head'"` (`backend/fly.toml:57-58`) **before** the new machines start serving traffic. No manual migration step needed.
2. `flyctl scale count web=2 worker=1 --app cadvrfy-api --yes` + `node scripts/ops/fly-ensure-process-groups.mjs` (`.github/workflows/ci.yml:419-427`) — pins the machine counts (2 web machines for launch headroom, 1 always-on worker) and blocks the deploy until both process groups report a started machine.
3. `node scripts/ops/fly-required-secrets-gate.mjs` (`.github/workflows/ci.yml:428-432`) — fails the deploy if any secret from §3b is missing.
4. `node scripts/ops/fly-live-health-gate.mjs` with `CADVERIFY_REQUIRE_WORKER=1 CADVERIFY_REQUIRE_WORKER_STRICT=1` (`.github/workflows/ci.yml:434-439`) — polls `/health` until Postgres, Redis, and a live arq worker heartbeat all report healthy.
5. `flyctl deploy --config frontend/fly.toml --image registry.fly.io/cadvrfy-web:<sha> --env RELEASE=<sha>` (`.github/workflows/ci.yml:441-448`).

**[FOUNDER, fallback only]** Manual deploy without CI (e.g. first bring-up before `main` is protected, or CI is down):

```bash
cd backend  && fly deploy               # picks up backend/fly.toml + Dockerfile from cwd
cd ../frontend && fly deploy             # picks up frontend/fly.toml + Dockerfile from cwd
# If you want browser-side Sentry on a manual deploy, see §3c — you must pass
#   fly deploy --build-arg NEXT_PUBLIC_SENTRY_DSN=<dsn>
# explicitly; nothing infers it for you outside the CI pipeline.
```
This path was not exercised in this session (no live Fly account available) — the `--config`/cwd assumption above matches how every other Fly.io deploy in this repo is invoked (fly.toml colocated with the Dockerfile it references), but you should treat your first manual run as a dry run and watch the build logs for a "Dockerfile not found" style error before trusting it blind.

---

## 6. Verify (post-deploy)

**[FOUNDER, some automatable]**

1. Re-run the two CI gates locally against the live app, same commands CI uses:
   ```bash
   FLY_API_TOKEN=<your token> FLY_APP_NAME=cadvrfy-api node scripts/ops/fly-required-secrets-gate.mjs
   CADVERIFY_API_URL=https://cadvrfy-api.fly.dev CADVERIFY_REQUIRE_WORKER=1 CADVERIFY_REQUIRE_WORKER_STRICT=1 node scripts/ops/fly-live-health-gate.mjs
   ```
2. Hit the deep health endpoint directly and eyeball it — it reports Postgres/Redis/worker/queue state individually and never fakes a healthy dependency (`backend/src/api/health.py:148-272`):
   ```bash
   curl -s https://cadvrfy-api.fly.dev/health/deep | python3 -m json.tool
   ```
3. **Real signup + magic-link smoke** (do this by hand in a browser, using a real inbox you control):
   - Go to `https://<your DASHBOARD_ORIGIN>/signup`, create a password account.
   - Log out, then trigger the magic-link flow (the login page's magic-link option) with the same email; confirm the email arrives via Resend and the link logs you in.
   - This is the surface the whole `_assert_production_secrets()` fail-closed logic in `backend/main.py:146-222` exists to protect — if any of `MAGIC_LINK_SECRET`/`RESEND_API_KEY`/`RESEND_FROM`/`DASHBOARD_ORIGIN` were wrong, the app would have refused to boot rather than let this fail silently, so a successful boot plus this manual smoke together are strong evidence the whole chain works.
4. **Real STEP upload → cost smoke**: upload an actual `.step`/`.stp` file through the UI and confirm a cost result renders. This exercises the gmsh/OpenCASCADE STEP path (`backend/Dockerfile:65-82`'s runtime libs exist specifically so this doesn't silently 501) and the arq worker (batch/async paths) end to end.
5. *(Optional, not verified against a live prod deployment in this session)* `APP_URL=https://cadvrfy-web.fly.dev E2E_LOGIN_EMAIL=<test account> E2E_LOGIN_PASSWORD=<test account> node scripts/e2e/human-e2e-runner.mjs` — this script supports an `APP_URL` override (`scripts/e2e/human-e2e-runner.mjs:13`) and is CI-proven against a local app, but running it against the real production app was not exercised in this session; treat step 3-4 above as the authoritative smoke test and this as a bonus if you want automated coverage.

---

## 7. Data safety

- **Neon PITR / automated backups [FOUNDER, platform toggle]:** in the Neon console, under your project's Backup/Restore settings, confirm point-in-time recovery is enabled (retention window depends on your Neon plan). This is a Neon-side toggle, not something in this repo — the exact menu path was not verified live in this session since no Neon account is available here; if you don't see it, check your plan tier (PITR window length varies by plan).
- **Restore drill against a scratch DB [FOUNDER/AUTOMATED]:**
  ```bash
  RESTORE_DRILL_ALLOW_REMOTE=1 DATABASE_URL="<your Neon DIRECT url>" bash scripts/ops/postgres-restore-drill.sh
  ```
  By default this runs in `sidedb` mode (`scripts/ops/postgres-restore-drill.sh:67` gates the destructive `inplace` mode behind `RESTORE_DRILL_MODE=inplace`, opt-in only): it `pg_dump`s your real DB, restores into a **new, separate** `<dbname>_restore_drill` database, checks table/`alembic_version` counts, then drops that scratch DB — your real database is never touched in this default mode. It refuses to run against a non-local host at all unless `RESTORE_DRILL_ALLOW_REMOTE=1` is set (`postgres-restore-drill.sh:35-37`), which is a deliberate safety rail — don't remove it casually.
  **Do not set `RESTORE_DRILL_MODE=inplace` against your production Neon database** — that mode intentionally `DROP DATABASE` + recreates the target itself (`postgres-restore-drill.sh:101-103`); it exists for a dedicated ops/scratch database, not prod.
  CI already runs this drill on every backend PR against the ephemeral CI Postgres (`.github/workflows/ci.yml:108-109`) — the command above is the same script, just pointed at Neon instead.

---

## 8. Monitoring

- **Uptime monitor [FOUNDER]:** point an external monitor (UptimeRobot, Better Stack, Pingdom, etc.) at `https://cadvrfy-api.fly.dev/health` (fast liveness check, `backend/src/api/health.py:32`) on a 1-5 minute interval with alerting on non-200.
- **Fly billing/usage alerts [FOUNDER]:** Fly dashboard → Organization → Billing, set a spend alert threshold.
- **Neon usage alerts [FOUNDER]:** Neon console → project → Billing/Usage, similarly.
- **Sentry receiving errors [FOUNDER, verify after §3c]:** once `SENTRY_DSN` / `NEXT_PUBLIC_SENTRY_DSN` are set correctly (§3c), trigger a real error (e.g. a bad request) and confirm it shows up in the Sentry project within a minute or two.
- **OTel collector endpoint [OPTIONAL, not needed for launch]:** tracing is fully opt-in and off unless `OTEL_TRACING_ENABLED=1` or `OTEL_EXPORTER_OTLP_ENDPOINT` is set (`backend/src/obs/tracing.py:50-57`). Like the S3/boto3 situation in §4, the OTel dependencies are **not** in the production image either — they live in `backend/requirements-otel.txt`, explicitly separate "so an unconfigured deploy imports none of these and is byte-identical" (comment at the top of that file). If you want tracing at launch, add those three packages to `requirements.txt` (or a custom image layer) before setting the env vars, or it will fail the same way the S3 backend would.

---

## 9. Tunables (per-org rate limits)

Backend env (`backend/src/auth/org_limits.py:74,78,82,93`), settable via `fly secrets set` or as plain `[env]` values in `backend/fly.toml` (they aren't secrets, just numbers — either works, `fly secrets set` also works for non-secret values if you'd rather not touch the toml):

| Var | Default | Meaning |
|---|---|---|
| `ORG_RATE_LIMIT_PER_HOUR` | 2000 | Org-wide API request ceiling per rolling hour |
| `ORG_RATE_LIMIT_PER_DAY` | 20000 | Org-wide API request ceiling per rolling day |
| `ORG_ANALYSES_PER_DAY` | 5000 | Durable per-day cap specifically on analyses (separate backstop from the request-rate numbers above) |
| `ORG_RATE_LIMIT_DISABLED` | off | Kill-switch to disable org-level limiting entirely — per `org_limits.py:88-93`, this only takes effect outside of a real `RELEASE` build, i.e. it cannot be used to quietly disable limits in production |

Adjust from real usage: watch `/health/deep`'s `checks.queue.depth` (`backend/src/api/health.py:269`) and your Sentry/Fly logs for `429` rates per org; an org legitimately bumping into `ORG_RATE_LIMIT_PER_DAY` during onboarding is a signal to raise that org's ceiling, not a bug.

Related, already set in `backend/fly.toml:21-26`: `MAX_UPLOAD_MB=100`, `DEMO_MAX_TRIANGLES=500000`, `ANALYSIS_TIMEOUT_SEC=60` — these are global (not per-org) and can be tuned the same way if a specific org's real parts are hitting these ceilings.

---

## 10. Rollback

- **Roll back a bad backend deploy [FOUNDER]:**
  ```bash
  fly releases --app cadvrfy-api                       # find the previous good image/version
  fly deploy --config backend/fly.toml --image registry.fly.io/cadvrfy-api:<previous-sha> --app cadvrfy-api
  ```
  Same pattern for `cadvrfy-web` with `frontend/fly.toml` and the `cadvrfy-web` image tag. Every image is tagged with the commit SHA (`.github/workflows/ci.yml:385,395`), so `git log` against `main` tells you exactly which SHA to roll back to.
  **Caution:** rolling the backend image back does **not** roll back the database schema — if the bad deploy included a migration, decide whether the previous code is still compatible with the new schema before rolling back, or you'll need a compensating migration instead.
- **Kill-switch, not a rollback but faster [FOUNDER/AUTOMATED]:** `bash scripts/ops/kill-switch.sh off` sets `ACCEPTING_NEW_ANALYSES=false` and redeploys (`scripts/ops/kill-switch.sh:10-11`) — within ~30s (the in-process cache TTL, `backend/src/auth/kill_switch.py:20`) `POST /api/v1/validate` starts returning `503` + `Retry-After: 3600` instead of accepting new work, without touching existing sessions/data. Use this to stop the bleeding (e.g. a bad model/parser regression) while you prepare a real rollback. Flip back with `bash scripts/ops/kill-switch.sh on`.

---

## 11. What changed in this session (build summary)

For traceability — these are the concrete changes this runbook assumes are in place:

- `frontend/fly.toml`: `min_machines_running` 0 → 1 (no cold start on the 10 orgs' first hit of the day).
- `backend/fly.toml`: `[http_service] min_machines_running` 1 → 2, `soft_limit` 25 → 40 (headroom so one org's concurrent STEP parses can't starve another org behind a single uvicorn machine).
- `.github/workflows/ci.yml`: the "Ensure backend web and worker process groups" step's `flyctl scale count web=1 worker=1` → `web=2 worker=1`, to match the fly.toml change above (**without this, CI would silently reset the machine count to 1 on every deploy**, defeating the fly.toml edit — this was caught, not assumed).
- `frontend/instrumentation.ts` (new): wires the previously-orphaned `frontend/sentry.server.config.ts` into Next's server boot (`register()`) plus `onRequestError`. Before this file existed, `sentry.server.config.ts`'s `Sentry.init(...)` was never called by anything — Next.js does not auto-load it without this hook. Verified via a clean `npx tsc --noEmit` and `npm run build`.
- `frontend/Dockerfile` + `.github/workflows/ci.yml`: added `ARG NEXT_PUBLIC_SENTRY_DSN` threaded into the build, and the corresponding `build-args` in the frontend image build step — required for browser-side Sentry to ever activate (see §3c).
- `scripts/ops/gen-launch-secrets.sh` (new): prints the `fly secrets set` lines described in §3.
- `docs/LAUNCH_RUNBOOK.md` (this file, new).

Frontend gates run this session, all green: `npx tsc --noEmit` (exit 0), `npm test` (275/275 pass), `npm run build` (exit 0, with instrumentation.ts wired in), `npm run lint` (0 errors, pre-existing warnings unrelated to this work).
