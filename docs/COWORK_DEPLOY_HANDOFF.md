# CadVerify — Production Deploy Handoff (for Cowork)

**Paste this whole file to Cowork as the task.** It's the context + decisions +
acceptance bar. The step-by-step commands live in **`docs/LAUNCH_RUNBOOK.md`** —
this document tells you how to use it and what must not be missed.

---

## 0. What you're doing (read first)

You are deploying **CadVerify** — a CAD manufacturing-cost / DFM / makeability
platform (FastAPI backend + gmsh geometry engine + arq worker + Next.js frontend
+ Postgres + Redis) — to production so **10 real organizations** (oil & gas,
automotive, aerospace/defense, job-shops) can sign up and use it. Auth is
**password + magic-link (no Google)**.

**The app is already hardened and tested for this launch — your job is
PROVISIONING + DEPLOY, not fixing app code.** Specifically, in the current
branch:
- Full backend test suite: **1626 passing**.
- Auth: password + magic-link works without Google; a missing launch secret
  fails the *deploy*, not the first user's login.
- Multi-tenant isolation is verified (cross-org reads → 404, no leaks).
- Per-org rate limits + daily quota (fail-open) guard against noisy neighbors.
- A load-critical bug (one heavy STEP freezing all tenants) is fixed + verified.
- **10-org concurrency load-tested + verified:** a burst of 70 concurrent uploads
  across 10 orgs returns **0% 5xx** — excess load gets an honest, retryable
  **429 + Retry-After** (admission control), `/health` stays responsive, and no
  org can starve the others (per-org concurrency cap). (Before this fix the same
  burst 500'd 55% of requests via DB-pool exhaustion.)
- Deploy config, secrets gate, and health gates are wired.

**Honest capacity note (not a blocker, but know it):** the single web machine has
a real throughput ceiling — **~8 concurrent analyses per machine** (each analysis
is 30–80s of CPU). Above that, users get a *retryable* "server busy" 429, not a
failure. For 10 orgs in normal use this is invisible; under a *synchronized* burst
(e.g. all orgs uploading at a kickoff) some requests get told to retry. Levers, in
order: run web at **≥2 machines** (`fly scale count web=N`), then raise
`MAX_CONCURRENT_ANALYSES` / `DB_POOL_SIZE` (see §7). A deeper fix (releasing the DB
connection during compute, to admit more per machine) is written up as a staged
post-launch follow-up. Also: blobs default to a single volume unless you enable S3
(see §2).

## 1. Current code state

- Everything is on branch **`claude/resume-review-oxqw0l`**, **not yet merged to
  `main`**. CI deploys **only on push to `main`** (`.github/workflows/ci.yml`).
- So step 1 of going live is: get this branch reviewed + **merged to `main`**
  (it's large — a review pass is prudent), which triggers the deploy pipeline.
- The regression gate for ANY code change is the full backend suite
  (`cd backend && .venv/bin/python -m pytest -q`). Do not ship a red suite.

## 2. Decisions to confirm with the human BEFORE provisioning

1. **Where to host.** The repo default is **Fly.io** (`backend/fly.toml` app
   `cadvrfy-api`, `frontend/fly.toml` app `cadvrfy-web`) — fastest to stand up,
   good for a 10-org beta. Alternatives already supported by the repo:
   - **Kubernetes** (AWS EKS / GCP GKE / Azure AKS / on-prem) via the Helm chart
     in `charts/cadverify/` — the enterprise-standard path.
   - **Self-host** via `docker-compose.yml`, or the air-gapped
     `cadverify-enterprise/` bundle (SAML) — **likely required for a
     defense/ITAR customer** that can't use public multi-tenant cloud.
   Recommend **Fly for the beta** unless a defense org needs on-prem *now*.
2. **Object store.** **S3 (recommended, durable)** vs the single Fly volume
   (simpler, but a single point of data loss). For paying customers, use S3.
3. **Domain** for `DASHBOARD_ORIGIN` (magic-link URLs + cookie origin + CORS).

## 3. Prerequisites the HUMAN must supply (you can't create these)

| What | Where to get it | Env var(s) |
|---|---|---|
| Fly.io account + `flyctl` auth | fly.io | (login) |
| Managed Postgres (Neon / RDS / Cloud SQL) — **pooled + direct URLs** | provider | `DATABASE_URL`, `DATABASE_URL_DIRECT` |
| Redis (Upstash / Fly Redis / ElastiCache) | provider | `REDIS_URL` |
| Resend account + **verified sending domain** | resend.com | `RESEND_API_KEY`, `RESEND_FROM` |
| Cloudflare Turnstile | cloudflare | `TURNSTILE_SECRET` (+ site key for FE) |
| A domain | registrar/DNS | `DASHBOARD_ORIGIN` |
| (Recommended) S3 bucket + creds | AWS/compatible | `OBJECT_STORE_BACKEND=s3`, `OBJECT_STORE_S3_*` |
| (Recommended) Sentry project | sentry.io | `SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_DSN` |

Note: **Neon is just managed Postgres and Fly is just a container host — neither
is load-bearing in the code.** Swapping Postgres providers is a connection-string
change; moving off Fly is the Helm/compose path above.

## 4. The deploy sequence — follow `docs/LAUNCH_RUNBOOK.md` exactly

That runbook is authoritative (11 sections: prerequisites → provision → secrets →
object store → deploy → verify → data safety → monitoring → tunables → rollback).
The spine:

1. **Provision** the two Fly apps + the `/data` volume (runbook §2).
2. **Secrets**: run `bash scripts/ops/gen-launch-secrets.sh` — it generates the
   random secrets (`os.urandom(32)`) as ready-to-paste `fly secrets set` lines and
   marks the external ones `<FILL_ME: ...>`. Set them all (runbook §3).
3. **Object store** (runbook §4) — set S3 if chosen.
4. **Deploy** (runbook §5): merge to `main` (CI deploys) or `fly deploy`.
   Migrations run automatically (`alembic upgrade head` via `release_command`).
5. **Verify** (runbook §6) — see acceptance bar below.

## 5. Acceptance criteria — do NOT declare "done" until ALL pass

- [ ] `node scripts/ops/fly-required-secrets-gate.mjs` passes (every required
      secret is set) — this is also enforced in CI.
- [ ] `node scripts/ops/fly-live-health-gate.mjs` passes, and `GET /health/deep`
      shows **postgres + redis + worker all green** (not degraded).
- [ ] A real person can **sign up, receive a magic-link email, click it, and log
      in.** (If no email arrives, the Resend secrets/domain are wrong — see §6.)
- [ ] A real **STEP upload returns a cost/verdict** (upload `cube.step` or any
      real part).
- [ ] **Two different orgs cannot see each other's data** (spot-check a
      cost-decision id across two accounts → 404).
- [ ] (Recommended) run `node scripts/ops/load-profile.mjs` with
      `CADVERIFY_API_URL=<deployed url>` and confirm `/health` p95 stays low and
      the cost path completes without 5xx.

## 6. Critical gotchas (these silently break a launch)

1. **Real secrets, not the dev stubs.** The dev runbook uses well-known
   `base64('a'/'b'/'c'*32)` and `SESSION_SECRET=dev` / `TURNSTILE_SECRET=test`.
   These are PUBLIC. Use the values from `gen-launch-secrets.sh`. The startup
   guard blocks *absent* secrets but a stub base64 would pass the length check —
   so this is on you to get right.
2. **Magic-link needs email.** It's enabled via `AUTH_MODE=password` +
   `MAGIC_LINK_ENABLED=true` (already set in `backend/fly.toml`) **plus** the
   Resend trio (`RESEND_API_KEY`, `RESEND_FROM`, `DASHBOARD_ORIGIN`). No email
   creds ⇒ no login links go out ⇒ users can't get in.
3. **The Turnstile env var is `TURNSTILE_SECRET`** (the name the backend reads),
   not `TURNSTILE_SECRET_KEY` (which some docs use). Wrong name = captcha silently
   off.
4. **`DASHBOARD_ORIGIN` must be the real https domain** or magic-link URLs and
   the session cookie break.
5. **Enable Postgres backups (Neon PITR / RDS automated backups)** — this is a
   provider dashboard toggle, not in the repo. Then run
   `scripts/ops/postgres-restore-drill.sh` against a scratch DB to prove restore.
6. **Frontend cold start**: `frontend/fly.toml` is set to `min_machines_running
   = 1` so first-hit isn't slow — keep it ≥1.

## 7. Post-launch

- Uptime monitor on `/health`; billing alerts on Fly + the DB provider; confirm
  Sentry is receiving (if DSN set).
- **Per-org rate tunables** (adjust from real usage via the admin usage summary):
  `ORG_RATE_LIMIT_PER_HOUR` (2000), `ORG_RATE_LIMIT_PER_DAY` (20000),
  `ORG_ANALYSES_PER_DAY` (5000). Kill-switch: `ORG_RATE_LIMIT_DISABLED` (only
  bypasses outside a real `RELEASE`).
- **Capacity / concurrency tunables** (the load-tested admission gate):
  `MAX_CONCURRENT_ANALYSES` (8 per web machine — keep it under `DB_POOL_SIZE +
  DB_MAX_OVERFLOW`), `MAX_CONCURRENT_ANALYSES_PER_ORG` (3 — fairness),
  `DB_POOL_SIZE` (10 → 20 slots), `DB_POOL_TIMEOUT` (10s), `DB_POOL_RECYCLE`
  (300s). Kill-switch: `ADMISSION_DISABLED` (bypass only outside `RELEASE`).
- **If users see "server busy, retry" (429 `server_busy`) too often** under real
  load, in order: (1) `fly scale count web=N` (linear capacity — each machine adds
  ~8 concurrent), (2) raise `MAX_CONCURRENT_ANALYSES` **and** `DB_POOL_SIZE`
  together (keep the cap under the pool, and the pool under the DB provider's
  connection budget × machines), (3) implement the staged "release DB session
  during compute" follow-up to admit more per machine. **Never** raise the cap
  above the pool — that reintroduces the 500s the admission gate exists to prevent.

## 8. Rollback

- `fly releases` → `fly deploy --image <previous>` (runbook §10). Kill-switch
  script: `scripts/ops/kill-switch.sh`.

---

**Summary for the human:** the code is launch-ready and tested; what remains is
real infrastructure you provision. Give Cowork the accounts/creds in §3, have it
follow `docs/LAUNCH_RUNBOOK.md`, and hold it to the §5 acceptance bar. The one
thing no agent can do for you is create the accounts and hold the API keys.
