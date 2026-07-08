# CadVerify — Production Deploy Runbook

**Status:** living document, grounded in the repo at `dev` HEAD (commit `a6ce85b`, 2026-07-04). Written to satisfy `outputs/product-gaps.md` §25 (Go-live/ops gaps, item 25). Documentation only — nothing in this file was deployed, built, or mutated to produce it; every claim below is either a direct code/config citation or explicitly marked unproven.

**Two deploy topologies exist in this repo and they are NOT equally proven:**

| Topology | Backend | Frontend | Proof |
|---|---|---|---|
| **A. SaaS (Fly.io + Vercel)** | `backend/Dockerfile` → Fly machines (`backend/fly.toml`) | Vercel (implied by `next.config.ts`'s "Vercel uses its own adapter" comment; not automated in CI) | `.github/workflows/ci.yml` `docker-build` + `deploy` jobs — **last proven green 2026-06-18**, see §2 and §10 |
| **B. Self-hosted / enterprise (Kubernetes + Helm)** | `backend/Dockerfile` via `charts/cadverify/` | `frontend/Dockerfile` via `charts/cadverify/` | **Not exercised by any CI job.** The frontend Docker image is currently broken as configured — see §2 and §10, blocker #1 |

Read both, but if you are doing a first real deploy, read §10 before anything else.

---

## 1. Prerequisites & infra

### Postgres
- **Version 16.** `docker-compose.yml` uses `postgres:16-alpine`; CI's `backend` job runs a `postgres:16` service container (`.github/workflows/ci.yml`).
- `DATABASE_URL` is a hard-required env var — `backend/src/db/engine.py:87` does `os.environ["DATABASE_URL"]` (raises `KeyError`/crashes on startup if unset, no default).
- Fly's `[deploy].release_command` in `backend/fly.toml:47` runs `alembic upgrade head` with `DATABASE_URL=$DATABASE_URL_DIRECT` — a **separate, unpooled** connection string. The root `.env.example` documents why: `DATABASE_URL` is the pooled connection (Neon pooler in prod) and `DATABASE_URL_DIRECT` bypasses PgBouncer for DDL. **You need both secrets set on Fly** (`DATABASE_URL` and `DATABASE_URL_DIRECT`), not just one.
- The Helm chart (`charts/cadverify/templates/secret-db.yaml` + `_helpers.tpl`'s `cadverify.databaseUrl`) only produces **one** `database-url` key (`postgresql+asyncpg://user:pass@host:port/db`) and both `job-migrate.yaml` and the app deployments use it — there is no direct/pooled split modeled in the chart. If you front the chart's Postgres with PgBouncer yourself, you must add your own direct-URL parameter; the chart doesn't have one.
- Prod TLS: `_ensure_prod_tls()` (`src/db/engine.py:45`) auto-appends `sslmode=require` when `RELEASE` names a real deployment and the host isn't localhost/`postgres`/`.local` — off-switch `DB_REQUIRE_TLS=0`.
- Pool sizing: `DB_POOL_SIZE` (default 5), `DB_MAX_OVERFLOW` (default 10) — `src/db/engine.py:84-85`. The batch coordinator + worker can hold several sessions concurrently; size for your worker replica count.

### Redis
- CI uses `redis:7`; `docker-compose.yml` uses `redis:7-alpine`.
- `REDIS_URL` powers: arq job queue (`src/jobs/worker.py:78`, `src/jobs/arq_backend.py:33`), rate limiting (`src/auth/rate_limit.py`), magic-link/session helpers (`src/auth/redis_util.py`, `src/auth/password.py:112`), and gates `/health`'s async-tier probe.
- **Rate limiting fails closed in production without it.** `src/auth/rate_limit.py:31-55`: if `RELEASE` is set (production) and `REDIS_URL` is missing/`memory://`, the app raises `RuntimeError` at import time — "would silently fall back to per-process in-memory storage... not a real rate limit." Off-switch: `RATE_LIMIT_ALLOW_MEMORY=1` (explicit opt-in, not recommended).
- `/health` treats Redis as "expected" whenever `REDIS_URL` is configured **or** `RELEASE` is set at all (`src/api/health.py:70`) — i.e., any named production release is assumed to need the async tier unless you explicitly turn that assumption off with `ASYNC_STRICT_HEALTH=0`.

### The arq worker process
- Must run as its **own process**, separate from the web process: `arq src.jobs.worker.WorkerSettings` (`backend/fly.toml:9`, `charts/cadverify/templates/deployment-worker.yaml`, Dockerfile comment at line 85-86: "Worker overrides CMD to: arq src.jobs.worker.WorkerSettings").
- Fly config marks the worker `auto_stop_machines = "off"` (`fly.toml:39-43`) — deliberately always-on, because "SAM-3D jobs are long-running." The web process, by contrast, is `auto_stop_machines = "suspend"`.
- Worker settings (`src/jobs/worker.py`): `health_check_interval = 30`, `job_timeout = 600` (10 min hard ceiling, arq cancels at deadline), `max_jobs = 12`, `max_tries = 2`, plus a cron job (`sweep_orphaned_batches`, every 5 min + at startup) gated by `BATCH_ORPHAN_SWEEP_ENABLED` (see §5).
- The worker's arq heartbeat (`health_check_interval=30`, default queue name `arq:queue`) is what `/health`'s `ARQ_HEALTH_KEY` default (`arq:queue:health-check`, `src/api/health.py:86`) reads — these are consistent as shipped (no custom queue name override in `WorkerSettings`), so the liveness probe genuinely reflects a running worker, not just a reachable Redis.

### Secrets (backend)
All read via per-module `os.getenv`/`os.environ` — there is **no central settings object**; grep is the source of truth (`backend/.env.example`, root `.env.example`, and the modules cited below).

| Secret | Required when | Source |
|---|---|---|
| `DATABASE_URL` | Always | `src/db/engine.py:87` (KeyError if unset) |
| `DATABASE_URL_DIRECT` | Fly deploy only (migration release_command) | `fly.toml:47` |
| `REDIS_URL` | Always in real prod (see above) | multiple |
| `API_KEY_PEPPER` | Always | `src/auth/hashing.py:31` (KeyError if unset) — base64, decodes to ≥32 bytes |
| `DASHBOARD_SESSION_SECRET` | Always (password auth is mounted unconditionally, `main.py:270`) | `src/auth/dashboard_session.py:39` — base64, must decode to ≥32 bytes or `RuntimeError` |
| `SESSION_SECRET` | Always in prod | `main.py:93-100` fails closed (`RuntimeError`) if unset/`"dev-only"` and `RELEASE` names a real deployment |
| `MAGIC_LINK_SECRET` | `AUTH_MODE` ∈ {google, hybrid} | `src/auth/magic_link.py:39` |
| `RESEND_API_KEY`, `DASHBOARD_ORIGIN`, `RESEND_FROM` (optional) | `AUTH_MODE` ∈ {google, hybrid} (magic-link email send) | `src/auth/magic_link.py:103-107` |
| `TURNSTILE_SECRET` | Only the magic-link `/magic/start` flow (`AUTH_MODE` google/hybrid) — NOT used by password or SAML | `src/auth/turnstile.py:34`, called from `src/auth/magic_link.py:83` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | `AUTH_MODE` ∈ {google, hybrid} | `main.py:101-108` fails closed in prod if still `"dummy"` |
| SAML: `SAML_SP_ENTITY_ID`/`SAML_SP_ACS_URL`/`SAML_SP_SLO_URL` + `samlSecrets.spKey`/`spCert` | `AUTH_MODE` ∈ {saml, hybrid} | `charts/cadverify/templates/configmap-saml.yaml`, `secret-saml.yaml`, `src/auth/saml.py:92` |
| `SENTRY_DSN` | Optional | `main.py:136-144` |
| `RELEASE` | Recommended always in prod (git SHA) | gates `_is_production()` fail-closed checks everywhere; CI's deploy job sets `--env RELEASE=${{ github.sha }}` |

**SAML gotcha (real, documented in the chart itself):** `charts/cadverify/values.yaml:49-57` — `templates/secret-saml.yaml` ships `sp-key.pem`/`sp-cert.pem` as **empty string placeholders** by default. Fine for receiving unsigned assertions; SP request signing / encrypted assertions will **silently fail** with an empty key until you supply real PEMs via `--set-file samlSecrets.spKey=... --set-file samlSecrets.spCert=...` or an external/sealed secret.

### Auth mode
`AUTH_MODE` (default `"google"`, chart default also `"google"` per `values.yaml:73`, enterprise overlay `values-enterprise.yaml:9` sets `"saml"`) — one of `google | saml | hybrid`. Password auth (`/auth/signup`, `/auth/login`) is mounted **unconditionally regardless of `AUTH_MODE`** (`main.py:267-270`) — it is the only login method guaranteed to work with zero external auth infra.

### Object storage
**There is no S3/blob object-store integration today.** There is no `boto3`/S3 client in `backend/requirements.txt`, and remote batch references now reject unconditionally with `501 S3_INPUT_UNSUPPORTED` before any batch row is created. All blobs (meshes, batch inputs, PDFs, SAM-3D cache) live on **local disk** under `BLOB_STORAGE_PATH=/data/blobs` (and its children `MESH_BLOB_DIR`, `RECON_BLOB_DIR`, `BATCH_BLOB_DIR`, `PDF_CACHE_DIR`, `SAM3D_CACHE_DIR`). This is a real, persistent volume, not optional:
- Fly: `[[mounts]] source = "cadverify_data", destination = "/data", processes = ["web","worker"], initial_size = "1gb"` (`fly.toml:33-37`).
- Helm: `templates/pvc-blobs.yaml` — a single `ReadWriteOnce` PVC, default 50Gi, mounted at `/data/blobs` by **both** the backend Deployment (`replicaCount.backend: 2`) and the worker Deployment (`replicaCount.worker: 2`). **See §10 blocker — RWO + 4 total replicas is a scheduling risk that is not resolved by the chart as shipped.**

---

## 2. Build & image

### Backend Dockerfile (`backend/Dockerfile`)
Two-stage build, both stages `python:3.12-slim`:
- **Builder** installs `build-essential` + WeasyPrint/pymeshfix/scipy runtime libs (`libgl1`, `libglib2.0-0`, `libpango-1.0-0`, `libpangocairo-1.0-0`, `libcairo2`, `libgdk-pixbuf-2.0-0`, `libffi-dev`) plus a second `apt-get` layer for `xmlsec1`, `libxmlsec1-dev`, `pkg-config` (python3-saml build deps), creates a venv, `pip install -r requirements.txt`, then **downloads the SAM-2 Hiera Small checkpoint (~150MB) at build time** via `ADD https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt` (Apache-2.0, Meta AI). This is a live external network dependency baked into the image build — not vendored, not verified reachable from your build environment in this session.
- **Runtime** stage re-installs the same libs minus `-dev`/`build-essential` variants, plus `fonts-dejavu-core`, creates a non-root `cadverify` user (`T-06A-01` mitigation comment), copies the venv + SAM-2 weights from the builder, sets `SAM3D_MODEL_PATH`/`SAM3D_CACHE_DIR`/`MESH_BLOB_DIR` defaults, `USER cadverify`, `EXPOSE 8000`. Default `CMD` is the web process; the worker overrides `CMD` to `arq src.jobs.worker.WorkerSettings`.
- `--no-server-header` on the uvicorn CMD (`Dockerfile:88`, `fly.toml:8`) suppresses the `Server: uvicorn` banner; `SecurityHeadersMiddleware` then stamps a neutral value (S6 hardening).

### gmsh / mesher system libs — **unverified in this session**
`requirements.txt:5-8` pins `gmsh>=4.13` with a comment: it "embeds the OpenCASCADE kernel to read STEP and tessellate... py2.py3 wheels exist for macOS arm64 + manylinux x86_64; if no wheel for the deploy target, the route degrades to a clean 501 via `is_step_supported()` (no crash)." `is_step_supported()` (`src/parsers/step_mesher.py:32-51`) is a bare `try: import gmsh except ImportError: pass` — if gmsh's shared-lib dependencies (commonly `libGLU`, `libXft`, `libXcursor`, `libXinerama`, `libSM`, `libXext` on manylinux wheels, depending on the gmsh build) are missing from the runtime image, `import gmsh` fails, and STEP ingestion silently degrades to `501` — the app does **not** crash. The current runtime stage installs `libgl1` but **not** `libGLU`/`libXft`/the X11 family. Whether the pinned gmsh wheel actually needs them, or imports fine on `python:3.12-slim` with only `libgl1`, has **not been confirmed in this session** (no container was built). **Action before first prod cutover:** build the image and run `python -c "import gmsh"` inside it (or exercise a real STEP upload) to confirm STEP ingestion isn't silently degraded.

### Python 3.9 (local) vs 3.12 (deploy) drift
Local dev venv is Python 3.9 (`backend/.venv/lib/python3.9/...`); Docker (`FROM python:3.12-slim`) and CI (`actions/setup-python@v5, python-version: "3.12"`) are 3.12. This is a known, tracked gap (`outputs/product-gaps.md` §27: "Local dev env drift... keep `from __future__ import annotations` discipline; plan a venv upgrade beat"; also called out in `RESUME-CLOUD.md`). **Verified in this pass:** every backend module and every Alembic migration read during this audit (`main.py`, `src/db/engine.py`, `src/api/health.py`, `src/api/metrics.py`, `src/auth/dashboard_session.py`, `src/services/reconstruction_service.py`, `alembic/env.py`, `backend/scripts/backfill_part_summaries.py`, migrations `0019`/`0023`, etc.) opens with `from __future__ import annotations` — this postpones annotation evaluation to strings, so `X | Y` unions and builtin generics (`list[str]`, `dict[str, int]`) in type hints never raise `TypeError` at import time on 3.9, while still behaving correctly under the 3.12 runtime. The discipline is real and consistently applied, not aspirational — but it only covers *annotations*; any code that actually *executes* a 3.10+-only construct at runtime (e.g. `match` statement usage, or executing `X | Y` outside an annotation) would still break on the local 3.9 venv. None was found in the files read here, but this pass did not exhaustively grep the whole `src/` tree for that.

### Does the image actually build? — evidence, not a fresh build
This session **did not build the Docker image** (per the read-only mandate). Here is what real CI evidence shows instead:
- `.github/workflows/ci.yml`'s `docker-build` job builds `backend/` via `docker/build-push-action@v5` (`platforms: linux/amd64`) on every push to `main`, gated on the `backend` test job passing; `deploy` then runs `flyctl deploy --image registry.fly.io/cadvrfy-api:${{ github.sha }}`.
- The **last fully green run** (all jobs including `Docker Build` and `Deploy to Fly.io`) was **2026-06-18** (`run 27736938938`, commit "fix frontend demo STL limit feedback").
- The **most recent push to `main`** (2026-07-03T17:48, run `28675945660`, "checkpoint: version the running demo state") **failed** at `route-auth-coverage`, `Frontend Build & Lint`, and `Backend Tests` — `Docker Build` and `Deploy to Fly.io` were **skipped entirely** (never ran; `needs:` chain short-circuited).
- `main` is **176 commits behind `dev`** (`git rev-list --left-right --count main...dev` → `0 176`) — none of `dev`'s recent work (migrations 0019–0023, the Verify UI flag, the `prometheus-client` dependency, `--no-server-header`) has ever been through a green CI `Docker Build`.
- The actual delta in image-relevant files between the last-green `main` commit and current `dev` HEAD is small: `git diff main dev -- backend/Dockerfile backend/requirements.txt backend/fly.toml` shows only `+prometheus-client>=0.20.0` (pure-Python, "no system deps" per its own inline comment) and the `--no-server-header` CLI flag. This is low apparent risk, but it is **unproven for `dev`'s actual HEAD** — see §10.

### Frontend build (Next 16 / Turbopack) — **the self-hosted image is currently broken**
`frontend/package.json` pins `next: 16.2.3`, `react`/`react-dom: 19.2.4`. `npm run build` runs plain `next build` (no `--turbopack` flag found anywhere in `package.json`/`next.config.ts`; the merge commit `a6ce85b` references "webpack+Turbopack green" in its message, so both bundlers have been exercised at some point in CI/dev, but the shipped build script does not pin one explicitly — Next 16's default applies).

**Concrete finding:** `frontend/Dockerfile:20` does `COPY --from=builder /app/.next/standalone ./` — but `frontend/next.config.ts:15` has `// output: "standalone" is for Docker; Vercel uses its own adapter` **commented out, not set**. Without `output: "standalone"` in `next.config.ts`, `next build` does not produce a `.next/standalone` directory, and that `COPY` will fail. **This means `frontend/Dockerfile` — and therefore the entire Helm/k8s frontend deployment path (`charts/cadverify/templates/deployment-frontend.yaml`) — cannot build as configured today.** This is not exercised by CI at all: `ci.yml`'s `frontend` job only runs `npm run lint` and `npm run build` (plain Next build, no Docker step, no deploy step for the frontend anywhere in CI). The actual frontend production path in use is inferred to be Vercel's git-integration deploy (matching the `next.config.ts` comment and `src/lib/api-base.ts`'s hardcoded `https://cadvrfy-api.fly.dev` fallback), not the chart. **Fix before using the Helm chart:** uncomment/set `output: "standalone"` in `next.config.ts` and rebuild.

---

## 3. Migrations

- Head revision as of this audit: **`0023_ps_makeability`** (23 migrations total, `backend/alembic/versions/0001…0023`). `0024_org_invites_deact` does **not** exist in this tree — `feat/org-membership` is an unmerged branch; treat any reference to a merged `0024` as aspirational, not current.
- Run: `alembic upgrade head` from `backend/` with `DATABASE_URL` set (`alembic.ini:3` — `sqlalchemy.url = %(DATABASE_URL)s`).
- `alembic/env.py` is an **async** env — creates an `AsyncEngine`, forces `postgresql://` → `postgresql+asyncpg://`, rewrites `sslmode=require` → `ssl=require` (asyncpg's param name), and strips Neon's `channel_binding=require` (asyncpg doesn't support it). It wraps `context.run_migrations()` in an explicit `context.begin_transaction()` — the comment notes this is required or "the async connection rolls back on close."
- **Deploy wiring:**
  - Fly: `[deploy].release_command = "sh -c 'DATABASE_URL=$DATABASE_URL_DIRECT alembic upgrade head'"` (`fly.toml:47`) — runs automatically before every new release goes live, against the **unpooled** URL.
  - Helm: `templates/job-migrate.yaml` — a `pre-install,pre-upgrade` Helm hook Job (`helm.sh/hook-weight: "-5"`, `backoffLimit: 3`) that runs `alembic upgrade head` using the single `database-url` secret (no pooled/direct split in this chart — see §1).
- **The 32-char revision-id gotcha (real, not hypothetical):** both `0019_part_summaries.py` and `0023_ps_makeability.py` carry an explicit code comment: *"the revision id is kept <= 32 chars because alembic's `alembic_version.version_num` column is `varchar(32)`."* This bit the project for real — CI history shows a commit titled **"fix(alembic): shorten revision IDs to fit varchar(32)"** (2026-04-16). Every current revision string is short (`0023_ps_makeability`, `0019_part_summaries`, etc.) — verified by listing all 23 `revision = "..."` lines. **When authoring the next migration, keep the revision id ≤ 32 characters** or the `alembic_version` write will fail at deploy time.
- **Up/down discipline:** every migration read (`0019`, `0023`) implements both `upgrade()` and `downgrade()`, dropping indexes/columns in reverse creation order. CI's `backend` job has a dedicated step: "Real-database migration smoke (upgrade → downgrade → upgrade)" against a live `postgres:16` service, explicitly to prove the chain is reversible (its comment notes `test_migration_*.py` "only mocks alembic.op and proves nothing about real DDL"). This was proven green as of the 2026-06-18 run for whatever migrations existed on `main` then; migrations 0019–0023 (Phase D / part-summaries) postdate that and have **not** been through this specific CI gate on `main` — only the in-repo merge-commit self-report (`c42bde6`: "migration cycles clean") vouches for them, which is not independent CI proof.
- Both `0019` and `0023` set `op.execute("SET statement_timeout = '5000'")` at the top of `upgrade()` — a deliberate 5-second DDL timeout guard so a lock contention issue fails fast instead of hanging a deploy.

---

## 4. The mandatory one-time backfill

**Script:** `backend/scripts/backfill_part_summaries.py`. Docstring: *"Deploy one-shot: backfill the part-summary projection (Aramco GAP 2)... run it once after deploying migration `0019_part_summaries`."*

**Why it's mandatory:** `part_summaries` is a materialized per-`(org_id, mesh_hash)` projection that lets the whole-inventory triage/catalog/makeability endpoints do an O(buckets) SQL `GROUP BY` instead of folding the org's raw `analyses`/`cost_decisions` rows in Python. It is maintained automatically on **new** writes (the persist hooks call `refresh_part_summary_safe`, `src/services/part_summary_service.py:369`), but **pre-existing data is never retroactively summarized** except by this script.

**Exact invocation** (from the script's own docstring, run from `backend/`, with `backend/` on `sys.path` — there is no `backend/scripts/__init__.py`, so this relies on Python 3's implicit namespace packages and only works with `backend/` as the working directory / on `PYTHONPATH`):

```bash
cd backend
DATABASE_URL=postgresql://... python -m scripts.backfill_part_summaries
```

- Idempotent — safe to re-run; re-running an unchanged part yields byte-identical output (`refresh_part_summary`'s docstring: "calling twice on unchanged data yields the identical row").
- Implementation (`src/services/part_summary_service.py:493-532`): pages through every distinct `(org_id, mesh_hash)` pair across `analyses` ∪ `cost_decisions` via keyset pagination, `batch_size=500` in memory at a time — bounded memory, unbounded total rows. **However, the wrapping script (`scripts/backfill_part_summaries.py:34`) opens exactly ONE transaction and commits ONCE at the very end** ("Commits in one transaction after the full backfill completes.") — for a very large pre-existing dataset this is one long-lived transaction, not chunked commits. Not tested at scale in this session (see §10).
- **No write happens on any GET** — the fallback behavior when the projection is cold is read-only (see below), so running the backfill late doesn't corrupt anything; it just means slower/capped reads until you run it.

**The Phase D makeability fields ride the same function.** `refresh_part_summary()` (`part_summary_service.py:287-327`) — used by **both** the write-hooks and this backfill script — calls `derive_makeability_fields()` unconditionally as part of the same upsert. Concretely:
- If you already ran the backfill **before** migration `0023_ps_makeability` shipped, pre-existing rows got `makeability_bucket='unknown'` (the column's `server_default`) and were never re-evaluated.
- **Re-running `backfill_part_summaries.py` after `0023` is applied is required** to populate `makeability_verdict`/`in_house_makeable`/`makeability_bucket`/`unlock_*`/`makeability_gap` for parts that existed before the migration. It is the same idempotent script — no separate makeability-specific backfill exists.
- `mark_makeability_fresh` defaults `False` for both the analysis-persist hook and the backfill (only the **cost**-persist hook passes `True`) — this deliberately preserves any pre-existing `makeability_stale` flag rather than silently clearing it; a genuinely new/never-summarized row simply starts at the column default (`false`).

**Until the backfill runs (or a part is freshly re-costed), triage falls back to the legacy capped path — but the three consumer endpoints behave differently, and only some of them expose it as a flag:**

| Endpoint | Cold-projection behavior | Flag exposed |
|---|---|---|
| `GET /api/v1/catalog?keyset=true` | Falls back to the legacy capped fold for that one response (read-only, no write) | `cold_projection: true` **and** `truncated` (`src/api/catalog.py:127-139`) |
| `GET /api/v1/catalog/triage` | Falls back to the legacy capped fold silently | `note` text only when `truncated`; no explicit `cold_projection` key (`src/api/catalog.py:281-301`) |
| `GET /api/v1/catalog/makeability` | **No legacy fallback exists** for this lens — it is projection-only | `cold_projection: true` + an explicit note: *"Run the part-summary backfill or re-cost parts to populate the in-house breakdown."* (`src/api/catalog.py:373-382`) |

**Deploy checklist for this step:**
1. `alembic upgrade head` completes (through `0023_ps_makeability`).
2. Exec into a running backend container/pod (Fly: `fly ssh console -a cadvrfy-api -C "python -m scripts.backfill_part_summaries"` from `/app`; k8s: `kubectl exec` into a backend pod, or add a one-off Job modeled on `templates/job-migrate.yaml` — **no such Job template ships in the chart today**, you must author it or exec manually).
3. Confirm `count` in the printed/logged output is non-zero for a non-empty deployment.
4. Smoke `GET /api/v1/catalog/makeability` for a seeded org and confirm `cold_projection` is absent (see §8).

---

## 5. Feature-flag enablement plan

All flags are per-module `os.getenv` reads (no central settings/registry) — the constant names below are the literal env var names as found in source, confirmed by grep across `backend/src/`.

| Flag | Default | Source | Recommended prod value | Rationale |
|---|---|---|---|---|
| `RATE_LIBRARY_ENABLED` | `false` | `src/services/rate_library_service.py:39` | **On**, deliberately, once the governed rate-card asset (W4 slice 1) is ready to be the source of truth | Purely additive; off preserves today's static rate-card behavior byte-for-byte |
| `SHOP_LIBRARY_ENABLED` | `false` | `src/services/shop_library_service.py:44` | **On** alongside rate-library, same rollout | DB-backed successor to `data/shop_profiles/*.json`; off = legacy JSON files |
| `MATERIAL_LIBRARY_ENABLED` | `false` | `src/services/material_library_service.py:43` | **On** alongside the above | Overrides base rate-card `material_prices` per org; off = base constants only |
| `COST_ENSEMBLE_ENABLED` | `false` (`"0"`) | `src/costing/ensemble.py:56,61` | **Off** until independently validated against real shop data | New numeric behavior — per `RESUME-CLOUD.md`'s non-negotiable rule 2, new cost magnitudes ship `DEFAULT`/unvalidated until measured; flipping this changes served cost numbers |
| `METRICS_ENABLED` | `true` (`"1"`) | `src/api/metrics.py:39` | **On**, but see §6 — scrape only over a private network | `/metrics` is intentionally unauthenticated; enabling it publicly is a policy decision, not a code one |
| `BATCH_COST_ENABLED` | `true` (`"1"`) | `src/api/batch_router.py:101` | **On** (already the shipped default) | W3 cost-batch path is proven (per `RESUME-CLOUD.md`: "byte-identical to `POST /validate/cost`") |
| `BATCH_ORPHAN_SWEEP_ENABLED` | `true` (`"1"`) | `src/jobs/batch_tasks.py:194` | **On** (default) | Reaps batches stuck in pending/processing; turning it off leaves stuck batches unreaped |
| `RECONSTRUCTION_BACKEND` | `"local"` | `src/services/reconstruction_service.py:43,72` | **Leave `local`** (zero-egress default), but see §10 — the base image ships **no working local backend** | `local` vs `remote` (Replicate) vs `none`; remote egresses customer-derived imagery to a third party |
| `RECONSTRUCTION_ALLOW_REMOTE_EGRESS` | off (empty string) | `src/services/reconstruction_service.py:82` | **Off**, unless a customer has explicitly opted into third-party egress | Every egress path logs a loud acknowledgment when this is flipped; ITAR/data-residency sensitive |
| `NEXT_PUBLIC_VERIFY_UI` (frontend) | off | `frontend/src/lib/verify-flag.ts:14-15` | **Off** for now (still "IN DEVELOPMENT" per `product-gaps.md` — flip on when ready to expose the Verify product surface) | Gates the `/verify` route to `notFound()` when off; merge commit `a6ce85b` claims flag-off byte-identity + "tsc/181 tests/webpack+Turbopack green" |
| `MIN_REAL_RECORDS` | **hardcoded `8`, not an env var** | `src/services/groundtruth_service.py:71` | N/A — nothing to set | Unlike every other row in this table this is a Python literal (`MIN_REAL_RECORDS = 8`), gating ground-truth recalibration below 8 real (non-stand-in) records. There is no `os.getenv` wrapping it; changing it requires a code change, not a deploy-time flag flip. Listed here only because it was explicitly asked about — don't go looking for an env var. |

**Other operationally-relevant flags found in the same grep pass** (not explicitly asked for, but load-bearing for a first deploy):

| Flag | Default | Purpose |
|---|---|---|
| `SECRET_ENFORCEMENT_ENABLED` | `1` (on) | Off-switch for the fail-closed prod-secret checks in `main.py:93` — leave on |
| `SECURITY_HEADERS_ENABLED` | `1` (on) | `src/api/security_headers.py:33` — leave on |
| `ASYNC_STRICT_HEALTH` | `1` (on) | Whether an absent-but-expected async tier degrades `/health` to 503 — leave on in prod |
| `RATE_LIMIT_ALLOW_MEMORY` | `0` (off) | Explicit opt-in to unsafe in-memory rate limiting when `REDIS_URL` is missing in prod — leave off |
| `DB_REQUIRE_TLS` | `1` (on) | Leave on |
| `WEBHOOK_SSRF_GUARD_ENABLED` | `1` (on) | `src/services/url_guard.py:56` — leave on |
| `LABELING_ENABLED` | off | **Must stay off in prod** — mounts the dev-only corpus/label routes and widens CORS to localhost (`main.py:62-68,290-297`) |
| `COST_PERSIST_ENABLED` | `true` (on) | `src/services/cost_decision_service.py:40` — leave on |
| `AUTH_MODE` | `"google"` | `google \| saml \| hybrid` — set per deployment; chart default matches, enterprise overlay sets `saml` |

---

## 6. Observability

### `/metrics` (Prometheus)
- Endpoint: `src/api/metrics.py`. **Deliberately unauthenticated at the app layer** ("Prometheus scrapers do not carry API keys — putting it behind `require_api_key` would make it unscrapable") — the code comment is explicit that in production it **must be scraped over a private network / behind an ingress allowlist and never exposed to the public internet.**
- Existence gated by `METRICS_ENABLED` (404 when off); payload is a 503 with a plain-text message if `prometheus-client` isn't installed (it is, per `requirements.txt:34`).
- Labels are bounded-cardinality: `method` / matched-route **template** (not raw path — `_resolve_path_template()` reads `request.scope["route"].path_format`, e.g. `/api/v1/validate/cost`, never a ULID-bearing raw path) / `status`. No filenames, user IDs, ULIDs, or CAD content in the payload.
- `MetricsMiddleware` is installed in `main.py` immediately after `RequestIDMiddleware`, before rate limiting — every request is timed.
- Listed in `scripts/ci/check_route_auth.py`'s public-route allowlist so CI's auth-coverage guard doesn't flag it.
- **Scrape config is not shipped anywhere in this repo.** `charts/cadverify/templates/ingress.yaml` does not route `/metrics` at all (only `/api`, `/auth`, `/health`, `/`), and there is no `ServiceMonitor`/`PodMonitor` template in `charts/cadverify/templates/`. You must hand-wire scraping — e.g., a `ServiceMonitor` pointing at `service-backend.yaml`'s port 8000 path `/metrics`, restricted to in-cluster Prometheus, or a Fly-side private-network scrape job. This is a real gap in the chart, not a config you're missing — the manifest for it doesn't exist yet.

### `/health` — what a green response actually asserts
`src/api/health.py` is deliberately honest by construction (its own docstring calls out "F-ARCH-2"). A `200 {"status":"ok"}` response asserts:
- **Postgres is reachable** — a real `SELECT 1` was executed successfully.
- **If the async tier is "expected"** (`REDIS_URL` configured and not `memory://`, **or** `RELEASE` is set at all) **and `ASYNC_STRICT_HEALTH` is on (default)** — Redis was actually pinged successfully.

A `200` response does **NOT** assert:
- That an arq **worker** is alive and processing. `async.worker` is `"ok"` only if the arq heartbeat key (`ARQ_HEALTH_KEY`, default `arq:queue:health-check`) exists in Redis; if Redis is up but no heartbeat is found, it's honestly reported `"unknown"` — never fabricated as `"ok"`. `"unknown"` does **not** gate the overall status.
- That reconstruction (image→mesh) is available — the `reconstruction` block reports `{available, backend, egress}` truthfully but is explicitly **not a health gate**: "reconstruction being unavailable in a zero-egress deployment is a valid, intended state."
- That any given feature flag in §5 is on or correctly configured.

`version` is populated from `RELEASE` (the deploy job sets this to the git SHA — `--env RELEASE=${{ github.sha }}`).

### Logging / Sentry
- `structlog` is configured in `main.py` with `scrub_processor` (from `src/auth/scrubbing.py`) as the **penultimate** processor before `JSONRenderer` — explicitly so `cv_live_*` API keys and `Authorization` headers never reach stdout or Sentry.
- CI has a dedicated gate for this: the `sentry-leak-grep` job runs `tests/test_sentry_leak.py`, then greps the captured Sentry payload for the `cv_live_` pattern and **fails the build** if found. This job was part of the last fully-green CI run (2026-06-18).
- Sentry itself only initializes if `SENTRY_DSN` is set (`main.py:136-144`); `send_default_pii=False`; `before_send=sentry_before_send` (further scrubbing); `release` tagged from `RELEASE`.
- `LOG_LEVEL` (default `INFO`) controls both stdlib `logging.basicConfig` and structlog's filtering bound logger.

---

## 7. Frontend

- **Framework:** Next.js `16.2.3`, React `19.2.4` (`frontend/package.json`). Build: `next build` (plain — no explicit `--turbopack` flag in scripts; Next 16's default bundler applies; the `a6ce85b` merge commit message references both "webpack+Turbopack" having been green at some point, but the shipped `package.json` doesn't pin either explicitly).
- **Security headers:** `next.config.ts` applies HSTS/`X-Content-Type-Options`/`X-Frame-Options`/`Referrer-Policy`/`Permissions-Policy` to every route via `headers()`, mirroring the backend's `SecurityHeadersMiddleware`. No CSP yet (explicitly deferred — the app inlines styles/scripts).
- **The authed proxy (`API_BASE`):** the browser never holds an API key or a cross-origin cookie. All authenticated data calls go same-origin through `frontend/src/app/api/proxy/[...path]/route.ts`: the browser calls `/api/proxy/<path>` (first-party `dash_session` cookie sent automatically), and this Next.js route handler forwards to the backend at `backendUrl("/api/v1/" + path)` with `Cookie: dash_session=<token>` attached server-side, relaying status/body/rate-limit headers verbatim.
  - `API_BASE` (server-only env var, **no** `NEXT_PUBLIC_` prefix) is the backend origin the proxy and other server actions call. Default `http://localhost:8000` if unset (`frontend/src/lib/api-base.ts:1,13`).
  - `NEXT_PUBLIC_API_BASE` is the **browser-visible** backend origin, used for the public share route and other unauthenticated client-side fetches. If unset, it defaults to `http://localhost:8000` in dev, or the **hardcoded** `https://cadvrfy-api.fly.dev` in production (`api-base.ts:2,16-24`). **This is a footgun for the self-hosted/enterprise topology**: if you deploy the chart without explicitly setting `NEXT_PUBLIC_API_BASE`, the frontend will silently try to call the SaaS Fly backend instead of your in-cluster one. `charts/cadverify/templates/deployment-frontend.yaml` does set both `API_BASE` and `NEXT_PUBLIC_API_BASE` to the in-cluster backend Service — but if you deploy the frontend image any other way, you must set this yourself.
- **Runtime env needed:** `API_BASE`, `NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_VERIFY_UI` (flag, §5), `NEXT_PUBLIC_TURNSTILE_SITEKEY` (public Turnstile site key paired with the backend's `TURNSTILE_SECRET`, only relevant to the magic-link signup flow).
- **The Docker image is currently broken** — see §2's "Frontend build" subsection. Fix `next.config.ts`'s `output: "standalone"` before relying on `frontend/Dockerfile`/the Helm chart's frontend Deployment.

---

## 8. Post-deploy smoke checklist

Run these in order against the freshly-deployed environment.

1. **`GET /health`** → expect `200 {"status":"ok", "postgres": true, ...}`. If `RELEASE` is set (it should be), also expect `async.redis: true`. A `503` here means stop and diagnose before proceeding — don't chase the remaining steps.
2. **Migration/version check:**
   - `alembic current` (or `alembic heads`) against `DATABASE_URL_DIRECT` should show `0023_ps_makeability` (or later) as the applied head — mirrors CI's own "Alembic migration check" step (`alembic heads; pytest tests/test_migration_*.py -q`).
   - Cross-check `/health`'s `version` field against the image tag you just deployed (both are the git SHA in the Fly path).
3. **Authed `/validate` + `/validate/cost` round trip** (password auth works with zero external infra, so use it for this smoke regardless of `AUTH_MODE`):
   - `POST /auth/signup` (email + password, ≥8 chars incl. a letter and a digit) → sets the `dash_session` cookie.
   - `POST /api/v1/validate` with a small STL/STEP file (multipart) — gated by `require_kill_switch_open`, so confirm `ACCEPTING_NEW_ANALYSES` is `true` (fly.toml default) first.
   - `POST /api/v1/validate/cost` with the same file + machine params — confirm a real cost decision comes back, not a fixture/zero.
   - (Optional lighter smoke, unauthenticated: `POST /api/v1/validate/demo`, also kill-switch gated.)
4. **Machine-inventory CRUD** (`src/api/machine_inventory.py`), org-scoped and tenant-isolated:
   - `POST /api/v1/machine-inventory` (create) → `GET /api/v1/machine-inventory` (list) and `GET .../{machine_id}` (detail) → `PATCH .../{machine_id}` → `DELETE .../{machine_id}`.
5. **Backfill effect check** (§4): `GET /api/v1/catalog/makeability` and `GET /api/v1/catalog/triage` for a seeded/non-empty org — confirm `cold_projection` is absent/false and counts are non-zero once real parts exist.
6. **`/metrics`** (from inside the private network / allowed scrape source only): confirm it returns Prometheus text exposition, not a 404 (which would mean `METRICS_ENABLED=0` or the flag misconfigured) and not a public-internet-reachable 200 (which would mean the ingress/network policy is wrong — it should not route here at all per §6).

---

## 9. Rollback

- **Coarse, fast lever — the kill-switch, not a rollback:** `scripts/ops/kill-switch.sh off` runs `fly secrets set ACCEPTING_NEW_ANALYSES=false -a cadvrfy-api && fly deploy -a cadvrfy-api`. Per its own comment, this makes `POST /api/v1/validate` (and `/validate/cost`, `/validate/repair`, machine-inventory writes — everything behind `require_kill_switch_open`) return `503 + Retry-After: 3600` within ~30s of the secret propagating. Use this first if you need to stop new analyses immediately while you investigate, before reaching for a full image rollback.
- **Image rollback (Fly path):** images are tagged by `github.sha` and `:latest` in `registry.fly.io/cadvrfy-api` (`ci.yml`'s `docker-build` job). Roll back with `flyctl deploy --config backend/fly.toml --image registry.fly.io/cadvrfy-api:<previous-sha>` — the same pattern CI's own `deploy` job uses.
- **Image rollback (Helm path):** `helm rollback cadverify <REVISION>`, or `helm upgrade --set image.backend.tag=<previous-tag> --set image.frontend.tag=<previous-tag>`.
- **Migration downgrade caveat — read before running `alembic downgrade`:**
  - Neither the Fly `release_command` nor the Helm `job-migrate.yaml` hook ever runs anything but `alembic upgrade head` — there is **no automated downgrade path**. A downgrade is always a deliberate, manual `alembic downgrade <revision>` invocation against `DATABASE_URL_DIRECT`.
  - The migrations audited in this pass (`0019`, `0023`) are deliberately **additive-only**: new nullable columns / server-defaulted columns that older application code simply never reads. `0023`'s own docstring states this explicitly: "Purely ADDITIVE and reversible. Absent inventory the whole makeability lens reads 'unknown' and every legacy column/read is byte-identical." This means the **default rollback move should be: roll back the image only, and leave the database at its current (newer) migration head** — older code tolerates a newer, additive schema fine.
  - Only run `alembic downgrade <revision>` if a specific migration is itself the thing that broke (e.g., a bad index blocking writes), and only after confirming no other currently-running release (during a staged rollback) depends on the columns/indexes you're about to drop.

---

## 10. NOT YET PROVEN / OPEN

Honesty over completeness, per the mandate. These are the things this pass could not confirm from the repo, or actively found to be broken/unfinished — not glossed over.

1. **The self-hosted (Helm/k8s) frontend image does not build as configured.** `frontend/Dockerfile` copies `.next/standalone`, but `next.config.ts` does not set `output: "standalone"`. This is a static-analysis finding (config mismatch), not something I ran a build to confirm — but it is a very high-confidence one given how Next.js's standalone output mode works. **Fix `next.config.ts` before attempting the chart-based frontend deploy.**

2. **The `dev`-HEAD Docker image (backend) has never been through a green CI `Docker Build`.** `main` (176 commits behind `dev`) was last proven green on 2026-06-18; the most recent push to `main` failed upstream of the Docker/Deploy jobs entirely. The `dev`→last-green-`main` diff on image-relevant files is small (`+prometheus-client`, `+--no-server-header`), which is reassuring but not proof. **Recommend running the CI pipeline (or an equivalent local build) against current `dev` before promoting to `prod`.**

3. **gmsh's actual runtime import success on the shipped runtime image is unconfirmed.** The Dockerfile installs `libgl1` but not the X11/GLU family some gmsh wheel builds dynamically link against. Failure mode is graceful (a silent `501` on STEP uploads, not a crash), which is good, but "STEP ingestion silently doesn't work" is exactly the kind of thing that should be confirmed, not assumed. **Action: `python -c "import gmsh"` inside a real built image before first cutover.**

4. **Reconstruction (image→mesh) has no working backend in the shipped image.** `requirements.txt`'s own comment says local TripoSR needs `torch` + `tsr`, "installed on GPU workers, not in the base API image" — and no GPU node pool, separate worker image, or corresponding Helm/Fly config exists anywhere in this repo. `RECONSTRUCTION_BACKEND=local` (the safe, zero-egress default) will report `unavailable` in this topology unless a currently-undocumented GPU worker variant is built and wired in separately. This is an infra gap, not a flag you forgot to set.

5. **PVC/replica topology conflict in the Helm chart.** `values.yaml` sets `replicaCount.backend: 2` and `replicaCount.worker: 2`, while `templates/pvc-blobs.yaml` provisions a single `ReadWriteOnce` PVC mounted by both Deployments. Depending on the CSI driver/storage class, RWO volumes commonly bind to one node (or one writer pod) at a time — 4 total replicas against one RWO volume is a real scheduling risk that has not been exercised against a live cluster in this session.

6. **No Prometheus scrape manifest ships anywhere** (no `ServiceMonitor`/`PodMonitor`, and `/metrics` isn't in the chart's `ingress.yaml` paths) — scrape wiring is 100% left to the operator.

7. **SAML signing/encryption is untested** — the chart ships empty `sp-key.pem`/`sp-cert.pem` placeholders by default (explicitly documented as a footgun in `values.yaml`'s own comments); no SAML IdP was available to exercise this in this session.

8. **Load/soak envelope is unknown.** `fly.toml`'s `[http_service.concurrency]` (`hard_limit=50, soft_limit=25`), `[[vm]]` (`memory=1gb, cpus=2 shared`), and `auto_stop_machines=suspend` on the web process are the *configured* numbers, not validated ones — no load test was run in this session (or found evidence of one having been run), and meshing (`gmsh`) is explicitly documented as CPU-bound and **not thread-safe** (serialized via a process-global lock in `step_mesher.py`), which caps real concurrency in ways the configured `cpus=2` doesn't obviously reveal.

9. **The real-Redis async tier under sustained load (batch backlog, reconstruction queueing, concurrent magic-link/rate-limit traffic) is unproven.** CI only exercises a single-container `redis:7` for functional correctness, not backlog/soak behavior; arq worker behavior under sustained load was not observed here.

10. **`backfill_part_summaries.py`'s single end-of-run commit at real ("Aramco GAP 2" / millions-of-parts) scale is untested.** The paging logic is bounded-memory by design, but the whole run is one open transaction — whether that's acceptable at the scale this table exists to serve has not been validated in this session.

11. **No CI job exercises the Helm chart at all** (no `helm lint`/`helm template`/`kind`-cluster install step in `.github/workflows/ci.yml`) — everything in §1/§2/§6 about the chart's k8s behavior is derived from reading the templates, not from a live cluster reconciliation.

---

### Top 3 things that would block a real first deploy (summary)

1. **Frontend Docker image is broken as configured** (`next.config.ts` missing `output: "standalone"` vs `frontend/Dockerfile`'s `COPY .next/standalone`) — blocks the entire self-hosted/Helm path immediately at image build.
2. **No green CI proof for `dev` HEAD's backend image** — the only proven-green Docker build is 176 commits stale; `dev`'s actual deployable artifact has not been through the pipeline.
3. **Reconstruction has no real backend in this topology** (no GPU worker, no `torch`/`tsr` in the base image) — anyone expecting image→mesh to work out of the box on a first deploy will hit a silent `501`, and there's no infra in this repo today to fix that quickly.
