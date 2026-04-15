# Pitfalls Research

**Domain:** DFM SaaS (CAD analysis) — single-builder public free beta on Vercel + Railway/Fly.io
**Researched:** 2026-04-15
**Confidence:** HIGH (most claims verified against official docs, Fly.io blog, OCP/cadquery issue tracker, WeasyPrint docs; LGPL legal interpretation is MEDIUM)

---

## Critical Pitfalls

### Pitfall 1: cadquery/OCP Docker image bloat and cold-start penalty

**What goes wrong:**
Naively `pip install cadquery` in a `python:3.12-slim` image produces a 2.5–4 GB container. The `cadquery-ocp` wheel alone is ~400 MB (OpenCascade C++ bindings), plus VTK (~300 MB if pulled), plus numpy/scipy/trimesh native deps. Fly.io machines and Railway take 20–90 s to pull and start cold, and image registry pushes from a laptop can exceed 30 minutes. Scale-to-zero becomes unusable.

**Why it happens:**
OCP bundles the full OpenCascade kernel; `cadquery[dev]` pulls VTK which is only needed for interactive rendering, not STEP parsing. Developers copy an example Dockerfile that installs everything.

**How to avoid:**
- Use `cadquery-ocp-novtk` wheel (published on PyPI specifically to avoid VTK bloat) — backend doesn't render, only parses.
- Multi-stage build: builder stage installs, runner stage copies only `/usr/local/lib/python3.12/site-packages` and necessary `.so` files.
- Pin `cadquery-ocp` version; don't let pip resolve fresh on every build.
- Strip debug symbols: `find / -name "*.so" -exec strip {} \;` in builder stage.
- Build on CI (GitHub Actions with buildx) — not from laptop; push layer-cached image to GHCR/Fly registry.
- Target image size: <1.2 GB compressed.

**Warning signs:**
- `docker build` takes >10 min
- `docker images` shows >2 GB
- Fly.io cold start >30 s
- Railway deploy fails with "image too large" or OOM during build

**Phase to address:** `packaging-deploy` (MUST do before public beta URL goes live)

---

### Pitfall 2: cadquery arm64 wheel availability mismatch

**What goes wrong:**
Developer on an M-series Mac runs `pip install cadquery-ocp` locally and it works (uses `cadquery-ocp-arm` from PyPI). CI runs on `ubuntu-latest` (amd64) and produces amd64 image. Deploys to Fly.io `shared-cpu-1x` (amd64) and works. Later someone (or CI) builds with `--platform linux/arm64` (e.g., for Fly's arm64 machines or for local dev on M1) and the build fails because `cadquery-ocp` proper only ships x86_64 manylinux wheels — arm64 lives in the separate `cadquery-ocp-arm` project with different release cadence.

**Why it happens:**
Two different PyPI distributions (`cadquery-ocp` vs `cadquery-ocp-arm`) and uneven Python version coverage (cp39–cp313). `pip` doesn't auto-select between them.

**How to avoid:**
- Commit to amd64-only for production backend (explicit in `fly.toml` / Railway config) — don't offer arm64 builds for beta.
- Document `linux/amd64` as the only supported backend platform in README.
- For M-series local dev: use Docker Desktop with Rosetta emulation (`--platform linux/amd64`) OR install cadquery natively on macOS via `conda`/`mamba` (`conda install -c conda-forge cadquery`).
- If arm64 is needed later, pin `cadquery-ocp-arm` with same OCP version as amd64 counterpart; add a separate CI job.

**Warning signs:**
- `No matching distribution found for cadquery-ocp` on non-x86_64 builds
- M1/M2 developer reports "it works on my machine but Docker build fails"
- Silent pull of emulated amd64 image on arm64 host (2–5× slower)

**Phase to address:** `packaging-deploy`

---

### Pitfall 3: cadquery LGPL-2.1 distribution concerns

**What goes wrong:**
cadquery is licensed Apache-2.0; its dependency **OCP** (OpenCascade bindings) is **LGPL-2.1**, and OpenCascade itself uses a modified LGPL-2.1 with an OpenCascade Exception. If you distribute the Docker image publicly (self-host path), you are distributing LGPL-linked binaries. Pure SaaS use (never ship image/binary to users) is widely considered safe under LGPL, but a public Docker image on GHCR + "one-command install for self-hosters" = distribution.

**Why it happens:**
Developer focuses on "SaaS loophole" (LGPL doesn't trigger on network use) and forgets the self-host Docker image path explicitly committed to in PROJECT.md.

**How to avoid:**
- For SaaS hosted on your Fly/Railway: no LGPL concern for end-users (no binary distributed).
- For public Docker image:
  1. Use dynamic linking (which OCP wheels do — they're `.so` files loaded at runtime).
  2. Include LGPL license text + OpenCascade license in image (`/licenses/`).
  3. Add a `NOTICE` / `THIRD_PARTY_LICENSES.md` at repo root listing cadquery (Apache-2.0), OCP (LGPL-2.1), OpenCascade (LGPL-2.1 with Exception).
  4. Don't modify OCP source; if you do, publish the modified OCP source.
- Consult a lawyer only if planning to sell proprietary derivatives or embed in closed-source commercial appliance. Not needed for standard free beta.

**Warning signs:**
- No `LICENSE` / `NOTICE` file mentioning third-party deps
- No license text bundled in Docker image
- Plan to fork and modify OCP

**Phase to address:** `packaging-deploy` (license file + NOTICE before publishing image); documentation ongoing.

---

### Pitfall 4: Plaintext API key storage and no rotation

**What goes wrong:**
Developer stores API keys as plain strings in Postgres `users.api_key TEXT`. On DB compromise (leaked backup, Supabase/Neon breach, pg_dump in a gist), all keys leak. Users can't rotate because the key is an identifier. Developer logs the key in request middleware. Keys appear in Sentry breadcrumbs, `/metrics`, or customer support tickets.

**Why it happens:**
API keys look like passwords but get treated like session tokens. People forget they're credentials.

**How to avoid:**
- Generate keys as `cv_live_<32 random bytes base62>` with a **visible prefix** (so leaked keys are self-identifying — scannable by GitHub secret scanning).
- Store in DB as **SHA-256 hash** only (not bcrypt — API keys are high-entropy, don't need slow hashing; SHA-256 with per-row salt is correct and fast enough for per-request lookup).
- Store key **prefix** (first 8 chars) in a separate indexed column to make lookup O(1) without scanning all hashes.
- Show full key to user **exactly once** at creation; never retrievable afterward.
- Support multiple keys per user so rotation = create new, delete old (no downtime).
- Strip API keys from logs: custom logging filter that matches `cv_live_*` and replaces with `cv_live_***`.
- Set explicit `Authorization: Bearer cv_live_...` header scheme — never accept key as URL query param (leaks in referrer/logs).
- Optional expiration (`expires_at TIMESTAMPTZ NULL`).

**Warning signs:**
- Can retrieve user's current API key from dashboard (even once after creation) → storing plaintext
- Grep of logs/metrics/error traces contains `cv_live_`
- Single key column (no rotation model)
- Key in URL path or query

**Phase to address:** `auth` — core invariant; get this right the first time. Retrofitting costs a migration + forced key regeneration.

---

### Pitfall 5: Zip bomb / STEP recursion bomb / pathological mesh DoS

**What goes wrong:**
User uploads a crafted STL/STEP to free tier. Attack vectors:
- **Zip bomb:** If you accept `.zip` or `.stpz` (zipped STEP), a 1 MB zip can expand to 100 GB. Even without zip, ascii STEP with deeply nested `MANIFOLD_SOLID_BREP` recursion can OOM cadquery.
- **Mesh explosion:** A binary STL declares 1 trillion triangles in its 4-byte count header; trimesh tries to allocate 12 TB.
- **Ray-cast DoS:** A valid 800k-face mesh with pathological geometry makes `mesh.ray.intersects_location` run for 30 minutes per request. Each request pins a worker core.
- **Infinite watertightness check:** Degenerate non-manifold mesh sends trimesh into unexpected codepath.

Attacker scripts 100 parallel uploads on free tier → your Fly machines OOM, you get a $400 egress bill, service dies.

**Why it happens:**
`MAX_UPLOAD_MB` (file-size cap) is not a compute cap. Free beta = no per-user rate limit yet. Mesh complexity ≠ file size.

**How to avoid:**
- **Magic-byte validation** before parsing (already in PROJECT.md Active list): binary STL starts with 80-byte header; ASCII STL starts with `solid `; STEP starts with `ISO-10303-21`. Reject early.
- **Pre-parse triangle-count check:** For binary STL, read the 4-byte count at offset 80 and reject if `count * 50 + 84 > file_size` (sanity) or `count > MAX_TRIANGLES` (e.g., 2M).
- **Hard resource limits in worker process:** Use `resource.setrlimit(RLIMIT_AS, (2_000_000_000, ...))` for 2 GB address space cap, `RLIMIT_CPU` for wall-clock cap. On Linux only.
- **Subprocess parsing with timeout:** Spawn parser in `multiprocessing.Process` with `Process.join(timeout=30)` and `terminate()` on timeout. Catches trimesh/cadquery hangs where signals don't interrupt C code.
- **Ray-cast budget:** Cap face count for ray casting (sample every Nth face if >50k); implement `ANALYSIS_TIMEOUT_SEC` wall-clock that the request respects (return 504).
- **Reject nested archives entirely** in beta. Don't accept `.zip`, `.tar.gz`. Only `.stl`, `.step`, `.stp`.
- **Decompression bomb guard for gzip** if you ever accept `Content-Encoding: gzip` (FastAPI's default body parser does not, but middleware might).
- **Per-API-key request concurrency limit** (e.g., 2 concurrent analyses per key) to prevent parallelism-based DoS.

**Warning signs:**
- Worker CPU pinned at 100% for >60 s
- Fly/Railway memory graph shows sudden 2–4 GB spikes
- Single user generating >10% of total analysis compute
- `except Exception: pass` in parser code (CONCERNS.md already flags this)

**Phase to address:** `stabilize-core` (magic-byte + timeout + triangle cap) and `performance` (sampled ray-casting, subprocess isolation). Rate-limiting lives in `auth` phase.

---

### Pitfall 6: Async worker state desync on Fly Machines / Railway

**What goes wrong:**
Developer runs Celery/RQ worker on a separate Fly machine with `auto_stop_machines = true`. Worker picks up SAM-3D job, starts inference (45 s), Fly stops the machine because no HTTP traffic, job dies silently. User polls `/jobs/<id>` forever. Or: worker writes SAM-3D embedding to `/tmp/cache/<mesh_hash>`, machine restarts, cache is gone (ephemeral FS), next request re-runs 45-s inference. Or: two worker machines both pick up same job (Redis visibility timeout < inference duration + retries).

**Why it happens:**
Fly Machines are ephemeral VMs with auto-stop; Railway also scales-to-zero services. Celery's default behavior assumes always-on workers with persistent local state.

**How to avoid:**
- **Job queue broker:** Use Redis (Upstash serverless Redis, or Railway Redis addon) — not RabbitMQ (operational overhead). Redis connection must survive worker restarts.
- **Task ack after completion** (`task_acks_late=True` in Celery, or equivalent) so crashed job re-queues, not lost.
- **Visibility timeout >> max job duration:** For 60 s SAM-3D inference, set broker visibility timeout to 10 min (not the default 30 s), otherwise duplicate workers grab same job.
- **Idempotent jobs keyed by mesh hash + job id:** Worker checks DB/cache before starting; if already complete, no-op.
- **Persistent storage for model weights + embeddings:** Don't use `/tmp` or worker-local volume. Use S3-compatible storage (Tigris on Fly, Cloudflare R2, Backblaze B2) — cheap, persistent across machine restarts. Embedding cache keyed by mesh hash.
- **Pre-bake model weights into image** (not downloaded on startup) — but then mind image size (Pitfall 1).
- **Disable auto-stop for worker process group** in `fly.toml` for the worker process, or use Fly's "always-on" machine. Trade-off: costs ~$5/mo per worker vs unbounded cold starts.
- **Worker health check endpoint:** Worker runs a minimal HTTP server on port 8080 returning `{"status":"ok","jobs_in_progress":N}`. Fly uses this for machine status, and you can expose it at `/worker/health` for your own dashboard.
- **Recommendation for single-builder scope:** Start with **Arq** (native asyncio, simpler than Celery, lower memory) or **RQ** (simpler semantics than Celery). Only adopt Celery if you outgrow them. Celery's ecosystem richness is not worth the config complexity for beta.

**Warning signs:**
- Jobs stuck in "pending" forever
- Same job completes twice in logs
- Re-running identical SAM-3D inference repeatedly (no cache hit)
- Worker restart count >10/day in Fly dashboard

**Phase to address:** `async-sam3d` (entirely)

---

### Pitfall 7: Postgres migration breaks live beta

**What goes wrong:**
Alembic migration adds `NOT NULL` column to `analyses` table with 50k rows → locks table for 30 s → ingress stalls → Fly healthcheck fails → all requests 503. Or: drops old column that deployed frontend still reads → frontend crashes. Or: developer edits an already-applied migration file, pulls to prod, Alembic state diverges, future migrations fail with "Can't locate revision."

**Why it happens:**
Alembic templates produce single-step migrations that conflate schema + backfill + constraint. No enforced backward-compatibility window during rolling deploy.

**How to avoid:**
- **Expand-migrate-contract pattern** for every destructive change:
  1. Deploy migration A: add new column nullable (safe, no lock).
  2. Deploy app version that writes both old and new columns.
  3. Deploy migration B: backfill in batches (`UPDATE ... WHERE id BETWEEN x AND y` in 1k chunks with sleep).
  4. Deploy app version that only reads new column.
  5. Deploy migration C: drop old column + add NOT NULL.
- **Never edit an applied migration** — always add a new revision.
- **CI check:** Run `alembic upgrade head` against a seeded test DB on every PR.
- **Set `statement_timeout = '5s'` for migrations** on large tables → migration fails fast instead of locking prod for minutes. Use `CREATE INDEX CONCURRENTLY` for new indexes (Postgres-specific; Alembic needs `op.execute` for this).
- **Test rollback:** `alembic downgrade -1` works cleanly on every migration before merge.
- **Backup before migration:** Managed Postgres (Neon/Supabase) auto-snapshots; verify snapshot <24 h old before running migration.
- **Manual migration runbook:** Document exact command (`fly ssh console -C "alembic upgrade head"`), expected duration, rollback procedure. Don't auto-run on deploy until the pattern is proven.

**Warning signs:**
- Single migration file with >50 lines of schema + data changes
- `alembic history` shows merge revisions (two devs made parallel migrations)
- Any migration that does `op.drop_column` without a prior "readers removed" deploy
- `pg_stat_activity` shows a migration query >10 s

**Phase to address:** `persistence` — establish the pattern at phase start; cheap during beta (low user count), impossible to retrofit after 10k users.

---

### Pitfall 8: Vercel ↔ Fly/Railway CORS + auth footguns

**What goes wrong:**
- Frontend on `cadverify.vercel.app`, backend on `api.cadverify.fly.dev`. Preview deployments spawn `cadverify-git-<branch>-<user>.vercel.app` URLs — CORS `ALLOWED_ORIGINS=https://cadverify.vercel.app` blocks every preview. Dev workarounds with `allow_origins=["*"]` and forgets to tighten.
- `allow_credentials=True` + `allow_origins=["*"]` = browsers reject the response (spec-compliant). Developer sees "CORS error," widens origins further, eventually disables browser security.
- API-key auth via `Authorization` header works in `fetch`, but preflight `OPTIONS` request doesn't include the header → CORS middleware rejects preflight because `Authorization` not in `allow_headers`.
- Third-party cookies deprecated in Chrome (2025+); any session cookie on `.fly.dev` crossing to `.vercel.app` is silently dropped.

**Why it happens:**
CORS + preflight + credentials interact in ways that are only visible in browser devtools Network tab. Devs test with curl/Postman, where CORS doesn't apply, and think it works.

**How to avoid:**
- **Custom domain for backend:** `api.cadverify.com` (Vercel owns `cadverify.com`, Fly/Railway CNAMEs from `api`). Same eTLD+1 = far fewer third-party-cookie issues if you ever add sessions. Cheaper per-request (no Vercel Edge → Fly cross-region hop).
- **Regex origin match** for Vercel preview URLs:
  ```python
  allow_origin_regex=r"https://cadverify(-git-[a-z0-9-]+-[a-z0-9-]+)?\.vercel\.app"
  ```
- **Explicit allow_headers** (don't leave `["*"]` after auth lands): `["Authorization", "Content-Type", "X-Request-ID"]`.
- **`allow_credentials=False`** for API-key auth — it's stateless, doesn't need cookies. Prevents the wildcard-origin footgun.
- **Test preflight explicitly:** `curl -X OPTIONS -H "Origin: https://preview.vercel.app" -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: authorization" https://api.cadverify.com/api/v1/validate -i` — expect `Access-Control-Allow-Origin` header.
- **Cold-start mitigation:** Fly machines auto-start takes 2–8 s. User's first request times out in Vercel Edge's default 10 s. Options: keep min 1 machine warm (`min_machines_running = 1`, ~$5/mo), OR warm-ping on frontend page load, OR accept cold start and show a skeleton for ~10 s.
- **Upload size: bypass Vercel.** Frontend does `fetch(apiUrl, ...)` directly to Fly. Don't proxy 100 MB CAD uploads through Vercel Functions (4.5 MB body limit on Hobby, 10 MB Pro, anyway).

**Warning signs:**
- Preview deploys work locally but not from Vercel preview URL
- `allow_origins=["*"]` in prod
- First request after 5 min of idle takes >5 s
- Network tab shows CORS error only on preflight, not on actual request

**Phase to address:** `auth` (CORS tightening), `packaging-deploy` (custom domain + cold start), `frontend-polish` (preview-URL-aware regex).

---

### Pitfall 9: "Just ship it" with no observability → silent breakage

**What goes wrong:**
Beta launches. Tweet gets traction. 200 users sign up overnight. You wake up to 30 angry DMs about "analysis never completes." You have no error tracking, no per-endpoint latency metrics, no traces. You can't tell if it's cadquery crashing, Fly OOM, a specific STEP file, or your own bug. You spend 6 hours tailing `fly logs` with grep. By the time you diagnose, users have churned.

**Why it happens:**
Observability feels like infrastructure work, not product work. "I'll add Sentry after the launch." Launch is the moment you need Sentry most.

**How to avoid:**
- **Sentry** (free tier: 5k events/mo, enough for beta): `sentry-sdk[fastapi]` in backend, `@sentry/nextjs` in frontend. Capture unhandled exceptions + performance transactions. Cost: 20 min setup.
- **Structured JSON logging** with request ID (`structlog` or FastAPI `Request.state.request_id`); include mesh hash, face count, analysis duration per log line. Makes `fly logs | jq` actually useful.
- **Per-endpoint latency histograms:** FastAPI middleware emitting Prometheus metrics or just logging P50/P95 every 5 min. At minimum: `analysis_duration_seconds{process=...,success=...}` counter/histogram.
- **Uptime monitor:** Free tier of UptimeRobot / BetterStack hitting `/health` every 1 min, SMS/email on failure.
- **Usage dashboard (read-only for you):** Simple page with `SELECT count(*), avg(duration_ms) FROM analyses WHERE created_at > now() - interval '1 hour' GROUP BY verdict` — 1 query, 20 min to build, saves hours.
- **Cost alerts:** Fly.io billing alert at $50/mo, Railway at $50/mo. Catches runaway egress / stuck worker loops early.
- **Error budget:** If error rate >5% for 10 min, auto-page yourself (Sentry alert → email/SMS).

**Warning signs:**
- You answer "how many users used the product today?" with "let me grep logs"
- You find out about outages from user complaints
- No commit touching `sentry_sdk` or `logging` before beta launch

**Phase to address:** `packaging-deploy` (MUST go live with Sentry + structured logs + health + uptime monitor). Non-negotiable for a public URL.

---

### Pitfall 10: No usage caps → runaway cost

**What goes wrong:**
Free beta, no per-key rate limit (only "per IP" middleware which Cloudflare-fronted users bypass trivially). Someone wires CadVerify into their CI pipeline running on every PR. Suddenly 5000 analyses/day from one key. Fly autoscales from 1 to 6 machines. Railway bill goes from $10 to $180 for the month. Or: attacker spins up 100 API keys via signup form and DDoSes you.

**Why it happens:**
"It's free, who would abuse it?" plus "rate limiting is a rabbit hole, I'll do it later."

**How to avoid:**
- **Per-key rate limit** (already in PROJECT.md Active): use `slowapi` (SlowAPI for FastAPI) or roll a Redis INCR + TTL counter. Default: 60 analyses/hour, 500/day per key.
- **Global rate limit** as backstop: 20 req/s total at the ingress (Fly proxy supports this; or a FastAPI middleware).
- **Hard upload cap** separate from rate: `MAX_UPLOAD_MB=50` for free tier (lower than current 100).
- **Bot-resistant signup:** Cloudflare Turnstile (free) or hCaptcha on the "get an API key" form. Prevents bulk key creation.
- **Per-IP signup rate limit:** max 3 signups / IP / day.
- **Usage metering in DB** (row per analysis request with key_id, duration_ms, face_count, mesh_hash). Daily cron computes totals per key.
- **Soft kill-switch:** Environment variable `ACCEPTING_NEW_ANALYSES=true`. Flip to false in 1 SSH command if costs explode.
- **Cloudflare in front** (free tier): absorbs DDoS, caches `/api/v1/rule-packs` and other GETs, doesn't cost you.
- **Budget cap:** Railway/Fly billing alert → automated Slack/email → if exceeded, flip kill-switch.

**Warning signs:**
- Single key >1000 requests/day
- Egress bill >$20/mo during beta
- Fly scaling to >2 machines without you noticing
- Signup rate >50/day (real or bot?)

**Phase to address:** `auth` (rate limit + Turnstile + kill-switch — do NOT ship without these).

---

### Pitfall 11: Shareable URL enumeration / leakage

**What goes wrong:**
Shareable URL is `/analyses/123` (autoincrement ID). Attacker scripts `GET /analyses/1..100000` and scrapes all analyses — including competitors' confidential CAD geometry. Or: URL is `/analyses/<uuid>` but you also expose `GET /analyses?key=...` which returns all IDs for that key, defeating the opaque URL. Or: shareable URL works without auth (by design), but also leaks `owner_email` or `api_key_prefix` in the JSON response. Or: PDF reports cached on Cloudflare include API key in download URL.

**Why it happens:**
"Shareable" gets conflated with "public"; developer forgets opaque ≠ unauthenticated access should be limited.

**How to avoid:**
- **Opaque IDs only:** `ULID` or `uuid4` in URL, never incrementing int. Use ULID for sort-order preservation without leaking creation order.
- **Or signed short URLs:** `/s/<base62(HMAC(id, secret))>` — attacker can't forge without the secret.
- **Expiration optional but offered:** ship with default 30-day expiry, user can opt for "public forever."
- **Scope shared URL to read-only, single resource:** no enumeration endpoint for shared URLs. `GET /analyses/<ulid>` works without auth only if resource is marked shared; `GET /analyses` requires auth and only lists caller's own.
- **Scrub PII from shared response:** never include owner email, API key prefix, IP, or user-agent in shared JSON. Separate serializer for public view.
- **PDF download URLs also signed** and expire: pre-signed S3/R2 URL with 1-hour TTL, not a permanent public URL.
- **`X-Robots-Tag: noindex`** header on shared endpoints to prevent Google indexing.
- **Revocation:** user can "unshare" an analysis — flips a bool, URL 404s.

**Warning signs:**
- Any integer ID in a URL
- Shared page loads any user field beyond "Analysis from Apr 15, 2026"
- No "unshare" button in UI
- `robots.txt` doesn't disallow `/shared/*` or `/s/*`

**Phase to address:** `persistence` (ULID schema + shared flag + read-only serializer) + `frontend-polish` (revoke UI).

---

### Pitfall 12: WeasyPrint / headless Chrome PDF rendering footguns

**What goes wrong:**
WeasyPrint chosen for PDF reports (pure-Python, no Chrome). Installs locally fine (Mac has system fonts). In slim Docker image there are no fonts → WeasyPrint crashes referencing an empty font family list (known issue Kozea/WeasyPrint#677). Or: it "works" but renders `□□□` for any non-ASCII character (unit symbols µm, ø, ±). Or: Pango/Cairo versions don't match between local and container → subtle layout drift. Or: developer switches to headless Chrome (Playwright/Puppeteer) for fidelity and image jumps to 1.5 GB extra (Chromium binaries).

**Why it happens:**
PDF generation is "just a template" in theory, a full font + text-shaping stack in practice.

**How to avoid:**
- **Explicit system deps** in Dockerfile: `apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu fonts-liberation fonts-noto-core` (Noto covers Unicode symbols including µm, ø, ±).
- **Bake fonts into image; don't rely on host** for deterministic rendering.
- **CI smoke test:** render a fixed template → compare `hashlib.sha256(pdf_bytes)` to golden hash OR use `pdftotext` and diff text output. Catches font regressions.
- **Avoid headless Chrome for beta.** Stick with WeasyPrint; only upgrade to Chrome if branded marketing report is a real customer ask.
- **Generate PDF async** in same worker as SAM-3D — PDF rendering of a 3D-view-heavy report can take 5–15 s, don't block HTTP request.
- **Alternative: ReportLab** if WeasyPrint keeps causing issues — less pretty but zero font stack drama (uses built-in Type 1 fonts).

**Warning signs:**
- PDF has `□` boxes instead of Greek/Unicode symbols
- PDF renders differently on developer machine vs production
- Image size jumps >500 MB after adding PDF feature
- WeasyPrint raises `AttributeError: NoneType has no attribute 'family'` (the fontconfig-no-fonts bug)

**Phase to address:** `persistence` (PDF export feature lives here per PROJECT.md) + `packaging-deploy` (system fonts in Dockerfile).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|---|---|---|---|
| Keep legacy `PROCESS_ANALYZERS` dual-path alongside new registry | Don't break existing tests | Two code paths drift; double-maintenance; tests split | **Never past `stabilize-core` phase** — delete by end of that phase |
| `except Exception: pass` in analyzers | Fewer crashes in production | Silent bad data undermines trust in DFM verdict | Never — at minimum `logger.exception(...)` and emit an `Issue` |
| Single API key per user (no rotation) | Simpler schema | Compromised key = forced email-based regen, user friction | Only if users can delete+recreate easily; never without hashing |
| Synchronous SAM-3D inference "because 1 user" | Skip Redis + worker | Single 60-s request pins worker, blocks all other users | Never in production; fine for dev |
| Store analysis results as JSONB blob with no schema | Fast iteration | Backfilling new fields requires reading every row | OK for beta phase 1, migrate to normalized by phase 2 of persistence |
| Skip Alembic, use `create_all()` | Ship faster by 1 day | Impossible to alter schema without DB reset | Never once you have real users |
| `allow_origins=["*"]` in CORS | No preview-URL maintenance | Security footgun after auth lands | Only pre-auth, with `allow_credentials=False` |
| No image hash pinning in Dockerfile (`FROM python:3.12-slim`) | Automatic security updates | Silent behavior change on rebuild | OK for dev; tag-pin (`python:3.12.7-slim-bookworm`) for prod |
| No content-hash cache on analysis results | Simpler code | Duplicate 8-s analyses for same mesh repeatedly | OK pre-beta; mandatory at `performance` phase |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|---|---|---|
| **Fly.io** | Using local volume for shared state between machines | Use Tigris object storage (Fly-native S3-compatible) or managed Redis |
| **Railway** | Deploying worker in same service as API (shared dyno OOMs) | Separate services: `api`, `worker`, `redis`; scale independently |
| **Managed Postgres (Neon/Supabase/Fly)** | Using the unpooled connection URL in serverless/autoscaling backend | Use pooled URL (pgbouncer/Neon pooler) to survive scale-up bursts |
| **Vercel** | Proxying API through Next.js API routes | Frontend calls backend directly; Vercel functions for uploads hit 4.5 MB limit |
| **Upstash Redis / Railway Redis** | No TLS, default persistence | Enable TLS; set eviction policy `allkeys-lru`; use separate DB index for cache vs queue |
| **Cloudflare (in front)** | Not setting `cf-connecting-ip` as trusted header → rate-limit by `remote_addr` = Cloudflare's IP | Trust `CF-Connecting-IP` via proxy headers middleware; deny non-CF IPs at origin |
| **Sentry** | Not scrubbing request bodies → leaks CAD files + API keys into Sentry | Set `send_default_pii=False`, scrub `Authorization` header, don't attach request body |
| **Dependabot / Renovate** | Auto-merge minor updates breaks React 19 / Next 16 internals | Group frontend deps; require CI pass + manual merge for framework updates |
| **OpenAPI docs** | Publish `/docs` publicly with example API key hardcoded | Authenticate `/docs` in prod, or use offline-generated docs site |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|---|---|---|---|
| Ray-cast per face (O(N) rays in 100k-face meshes) | Analysis >5 s, worker CPU pinned | Sample every Nth face; cap at 50k rays; BVH | At ~200k faces (CONCERNS.md confirms) |
| Model weights re-loaded per SAM-3D job | First job 60 s, then 60 s again on next worker | Load once at worker startup; pin min-1-worker-running | Any worker restart |
| No mesh-hash cache on analysis result | Same file analyzed 100× = 100× compute | `SHA256(mesh_bytes) → analysis_id` cache table; return cached result | After ~50 users uploading "example.stl" from tutorials |
| Full `GeometryContext` per process (21×) | 21 processes × 8 s = 168 s | Build context once, share read-only across analyzers | Default "analyze all processes" request at >50k faces |
| Postgres N+1 on analysis list | History page takes 4 s at 100 rows | `SELECT ... JOIN processes` with `joinedload`; add index on `(user_id, created_at DESC)` | ~200 analyses per user |
| Three.js loading full STL for list thumbnails | Frontend OOMs, tab crashes | Generate server-side PNG thumbnail on analysis save; send URL not geometry | ~10 analyses rendered simultaneously |
| `fetch` without `AbortController` on analysis | User navigates away, upload continues, later requests queue behind it | Abort in-flight request on unmount | Any slow connection |
| JSON serialization of numpy arrays in response | 50 MB JSON for large mesh results | Paginate issues; send summary by default, details on demand | >1k issues per analysis |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---|---|---|
| API key in URL path/query | Logged in Fly/Railway access logs, Cloudflare, referrer headers | `Authorization: Bearer ...` header only; reject key in query |
| No CSRF protection on cookie-based dashboard | If you ever add session cookies, CSRF → key theft | API-key-only auth sidesteps this; if sessions added, SameSite=Lax + CSRF token |
| Mesh files cached in Cloudflare | Competitor's CAD geometry cached publicly if edge misconfigured | `Cache-Control: private, no-store` on all analysis endpoints; only `/rule-packs` cacheable |
| Error messages leak internal paths (`/home/app/src/...`) | Reconnaissance vector | `DEBUG=False`; Sentry captures trace, user sees `{"error":"internal","request_id":"..."}` |
| CORS `Access-Control-Allow-Credentials: true` with `*` origin (browsers reject anyway but devs widen to fix) | Pattern forces you into worse workarounds | Never credentials with wildcard; API-key auth doesn't need credentials mode |
| Signup endpoint unthrottled | Key exhaustion DDoS; bot-created keys for abuse | Turnstile + per-IP limit + email verification-lite (optional) |
| No audit log for key creation/deletion | Can't answer "when was this key created?" after incident | `api_key_events` table: created/rotated/revoked/used-first, timestamps |
| Mesh upload endpoint accepts `../../../etc/passwd` as filename | Path traversal if filename used on disk | Never use upload filename for disk path; use `mesh_hash` + extension |
| SQL injection via mesh-hash filter | Rare since hash is hex, but `ORM.raw(f"... {user_input}")` kills you | Always parameterized queries; `LIKE` needs `ESCAPE` clause |
| Reflected XSS in shared analysis page (rendering user-supplied "notes" field) | Session hijack, phishing | Store notes as plaintext; render with React's default escaping; CSP header `default-src 'self'` |
| Timing attack on API-key hash comparison | Attacker can brute-force key bytes | `hmac.compare_digest()` (constant-time) — never `hash == stored_hash` |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---|---|---|
| Analysis fails silently on non-watertight mesh (empty issue list) | User thinks part is fine, it isn't | Emit explicit `Issue{code: 'mesh_non_watertight', severity: 'warning'}` at top |
| Generic "analysis failed" error | User can't self-serve; files support ticket | Categorized errors: `parser_error`, `timeout`, `too_complex`, each with action hint |
| Progress spinner with no ETA for 45-s analyses | User closes tab, assumes broken | Show steps ("Parsing… Extracting features… Running CNC checks…") + elapsed time + soft estimate |
| SAM-3D opt-in UI buried | User doesn't discover the better segmentation | Show side-by-side preview; async badge "takes ~1 min" |
| Shareable URL copies to clipboard silently | User doesn't know it worked | Toast "Copied to clipboard" + show URL in an input |
| PDF report opens inline (browser PDF viewer on mobile = dire UX) | User can't save / share on phone | `Content-Disposition: attachment; filename="cadverify-<date>.pdf"` |
| API docs without a "try it now" button using their own key | Integration friction | Swagger UI with `persistAuthorization: true`; pre-fill from query param |
| Rate-limit rejection with `429` and no `Retry-After` | Client retries immediately → more 429s | Set `Retry-After`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers |
| History list loads all analyses | Frontend slow, DB slow | Paginate 20 per page; infinite scroll with virtual list |
| 3D viewer requires WebGL2; no fallback | iOS Safari old, corporate Chrome policies fail silently | Detect WebGL, show download + static thumbnail fallback |

---

## "Looks Done But Isn't" Checklist

Used by verifier agent in each phase.

- [ ] **API-key auth:** Works in happy path — verify rotate, revoke, replay after revoke returns 401, constant-time comparison, hashed storage, log scrubbing.
- [ ] **Rate limiting:** Returns 429 — verify `Retry-After` header, separate per-key and global limits, doesn't lock out the user's legitimate burst, counter resets correctly at TTL.
- [ ] **File upload security:** Rejects 200 MB file — verify magic-byte check, pre-parse triangle cap, subprocess timeout, ray-cast budget, nested-archive reject.
- [ ] **Postgres migrations:** `upgrade head` works — verify downgrade works, CI runs against empty DB, `statement_timeout` set, no destructive changes without expand-contract.
- [ ] **Shareable URLs:** URL works — verify opaque ID (not int), owner PII scrubbed, expiry enforced, revoke works, `noindex` header.
- [ ] **PDF export:** PDF renders locally — verify Unicode symbols (µm, ø, ±) render correctly, fonts baked in Docker, golden hash test in CI.
- [ ] **SAM-3D async:** Happy-path works — verify job survives worker restart, idempotent on retry, cache hit on duplicate mesh, graceful fallback when model missing.
- [ ] **Docker image:** Builds — verify size <1.5 GB, amd64 only for prod, boots in <10 s, health check passes, no secrets baked.
- [ ] **CORS:** Works from main Vercel URL — verify Vercel preview URLs work (regex match), preflight passes, credentials disabled, explicit allow-headers.
- [ ] **Observability:** Sentry configured — verify errors surface in Sentry, PII scrubbed, request ID in logs, `/health` returns DB + Redis status not just `ok`.
- [ ] **Usage caps:** Rate limit enforced — verify Turnstile on signup, kill-switch env var works, billing alerts fire, per-key + global both active.
- [ ] **License compliance:** `LICENSE` in repo — verify `NOTICE`/`THIRD_PARTY_LICENSES.md` lists cadquery/OCP/OpenCascade, bundled in Docker `/licenses/`.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---|---|---|
| Plaintext API keys in DB | HIGH | (1) Announce forced rotation 72 h ahead. (2) Migration: add `key_hash`, `key_prefix`. (3) Hash existing keys into new columns. (4) Drop plaintext column. (5) Invalidate all keys; force regenerate on next login. |
| Migration locked prod table | MEDIUM | (1) Cancel long query: `SELECT pg_cancel_backend(pid)`. (2) If can't, `pg_terminate_backend`. (3) Revert app to previous version. (4) Redesign migration as expand-contract. |
| Zip/STEP bomb filled disk | LOW | (1) Restart machine (ephemeral FS clears). (2) Deploy magic-byte + triangle-cap fix. (3) Ban attacker IP/key. (4) Add billing alert threshold. |
| SAM-3D worker dead-loop | MEDIUM | (1) Kill worker machine. (2) Inspect job in Redis: `LRANGE failed-jobs 0 -1`. (3) Set visibility timeout to 15 min. (4) Mark bad job as failed; notify user. (5) Ship idempotency key. |
| cadquery image bloat shipped | LOW | (1) Build slimmer image with `cadquery-ocp-novtk`. (2) Deploy as parallel app; A/B test. (3) Cutover when healthy. |
| CORS breaking Vercel previews | LOW | (1) Hotfix: add regex origin to env var. (2) Deploy. (3) Test preflight with curl. |
| Leaked shared URLs indexed by Google | MEDIUM | (1) Add `X-Robots-Tag: noindex`. (2) Submit URL removal to Google Search Console. (3) Invalidate/rotate all existing shared URLs. (4) Notify affected users. |
| Cost runaway | LOW–MEDIUM | (1) Flip `ACCEPTING_NEW_ANALYSES=false`. (2) Identify top 10 keys by usage. (3) Revoke abusive keys. (4) Lower global rate limit. (5) Re-enable. |
| Sentry swamped at free-tier limit | LOW | (1) Set sampling: `traces_sample_rate=0.1`. (2) Add `before_send` filter to drop known noisy errors. (3) Upgrade or wait for monthly reset. |
| Fly cold start too slow for launch traffic | LOW | (1) Set `min_machines_running = 2` in `fly.toml`. (2) Deploy. (3) Monitor cost; revert after peak. |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---|---|---|
| #1 Docker image bloat | `packaging-deploy` | Image <1.5 GB, cold-start <10 s measured |
| #2 cadquery arm64 mismatch | `packaging-deploy` | CI builds linux/amd64 only; README states platform |
| #3 LGPL distribution | `packaging-deploy` | `NOTICE` file + `/licenses/` in image; reviewed |
| #4 API-key plaintext + rotation | `auth` | Hash + prefix columns; rotate/revoke endpoints tested; log scrubbing verified |
| #5 Zip/STEP/mesh bomb DoS | `stabilize-core` (validation) + `performance` (sampled ray-cast, subprocess isolation) | Fuzz-test with hostile files; worker RLIMIT verified |
| #6 Async worker desync | `async-sam3d` | Kill worker mid-job → job re-queues + completes; duplicate detection via mesh hash |
| #7 Postgres migration break | `persistence` | Expand-contract template documented; CI runs `upgrade head`; downgrade tested |
| #8 CORS + cold start | `auth` + `packaging-deploy` + `frontend-polish` | Preview URL regex; custom domain; preflight curl test in CI |
| #9 No observability | `packaging-deploy` | Sentry receives test error; `/health` checks DB+Redis; uptime monitor green |
| #10 No usage caps | `auth` | Rate-limit headers on 429; Turnstile on signup; kill-switch env var tested |
| #11 Shareable URL leakage | `persistence` (schema) + `frontend-polish` (revoke UI) | Opaque IDs; scrubbed serializer; `noindex` header; unshare works |
| #12 WeasyPrint font / PDF deps | `persistence` (feature) + `packaging-deploy` (system deps) | Unicode symbol golden test; fonts in image |
| **Legacy analyzer dual path** (CONCERNS.md) | `stabilize-core` | `PROCESS_ANALYZERS` dict deleted; only registry remains |
| **Silent exception swallowing** (CONCERNS.md) | `stabilize-core` | `grep -rn 'except Exception' backend/src/analysis | wc -l` goes down by >80% |
| **Temp-file leak** (CONCERNS.md) | `stabilize-core` | Context-managed temp + `mode=0o600`; test verifies cleanup on exception |
| **Wall-thickness `inf` bug** (CONCERNS.md) | `stabilize-core` | Non-watertight mesh emits explicit Issue, not silent empty result |

---

## "Finish Your Side-Project" Specific Traps

Generic but brutal for single-builder beta launches:

- **Scope creep during stabilization:** Don't add features to `stabilize-core`. If a bug fix requires a new concept, that's a new phase.
- **Dogfood failure:** Run your own DFM analyses daily on real parts. If you stop using it, users will too.
- **Docs debt:** "I'll write docs after beta." You won't. At minimum: README quickstart + one OpenAPI example per endpoint.
- **Local-only reproducibility:** Verify `docker-compose up` from a fresh clone on a non-dev machine actually works. Tested by: delete `~/.docker`, delete repo, re-clone, follow README. Do it once.
- **Ignoring the boring auth phase:** API-key auth feels less interesting than SAM-3D. It's more important. Do it first, do it right.
- **Underestimating async-sam3d:** 60-s inference + job queue + caching + graceful fallback + retry semantics is 2 weeks, not 2 days.
- **Backing up production DB:** "Managed Postgres does it" — verify by actually restoring a backup to a staging DB before you need to. Once.
- **Launching on Tuesday, going on vacation Thursday:** If you're the only oncall, don't launch before travel. Set expectation: "beta, best-effort support."
- **Responding to every feature request during beta:** Say no. Write a public roadmap. Collect requests in GitHub issues; review weekly, not hourly.

---

## Sources

- [cadquery Docker Hub image](https://hub.docker.com/r/cadquery/cadquery) — base image reference for slim builds
- [cadquery-ocp-novtk on PyPI](https://pypi.org/project/cadquery-ocp-novtk/) — slim variant without VTK
- [cadquery-ocp-arm on PyPI](https://pypi.org/project/cadquery-ocp-arm/) — separate arm64 distribution
- [CadQuery issue #1489 — ARM64 wheels](https://github.com/CadQuery/cadquery/issues/1489) — canonical discussion of arm64 situation
- [cadquery-ocp on PyPI](https://pypi.org/project/cadquery-ocp/) — amd64 wheels
- [FOSSA — LGPL License 101](https://fossa.com/blog/open-source-software-licenses-101-lgpl-license/) — LGPL linking interpretation
- [Revenera — SaaS loophole in GPL](https://www.revenera.com/blog/software-composition-analysis/understanding-the-saas-loophole-in-gpl/) — network-use vs. distribution
- [Blackduck — Open Source in SaaS whitepaper](https://www.blackduck.com/content/dam/black-duck/en-us/whitepapers/wp-opensourse-saas-offerings.pdf)
- [Fly.io blog — Python Async Workers on Fly Machines](https://fly.io/blog/python-async-workers-on-fly-machines/)
- [Fly.io docs — Work Queues blueprint](https://fly.io/docs/blueprints/work-queues/)
- [Fly.io Django Beats — Celery on Fly Machines](https://fly.io/django-beats/celery-async-tasks-on-fly-machines/)
- [Leapcell — Celery vs Arq comparison](https://leapcell.io/blog/celery-versus-arq-choosing-the-right-task-queue-for-python-applications)
- [Judoscale — Choosing a Python task queue](https://judoscale.com/blog/choose-python-task-queue)
- [WeasyPrint docs — First steps (system deps)](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)
- [WeasyPrint issue #677 — no-font crash](https://github.com/Kozea/WeasyPrint/issues/677)
- [WeasyPrint Docker tips](https://www.dataisamess.com/2021-03-06/tips-to-generate-pdfs-inside-a-docker-image-with-weasyprint)
- [Fly.io community — WeasyPrint Django install help](https://community.fly.io/t/help-with-weasyprint-installation-on-docker/17131)
- `.planning/codebase/CONCERNS.md` — existing internal tech debt inventory (ray-cast perf, exception swallowing, temp-file leak, wall-thickness `inf`)
- `.planning/codebase/INTEGRATIONS.md` — current integration surface (none beyond trimesh/cadquery)
- `.planning/PROJECT.md` — active-requirements list and constraints

---
*Pitfalls research for: CadVerify DFM SaaS — finishing-a-side-project beta milestone*
*Researched: 2026-04-15*
*Confidence: HIGH (claims verified against official docs and issue trackers). LGPL-distribution interpretation is MEDIUM (not legal advice).*
