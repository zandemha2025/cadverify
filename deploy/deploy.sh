#!/usr/bin/env bash
# Ships the app source to the provisioned box, builds the images there, runs DB
# migrations, and brings the stack up. Reads deploy.state written by provision.sh.
# Run from inside the deploy/ folder, which must live at the repo root
# (so ../backend and ../frontend exist).
set -euo pipefail
cd "$(dirname "$0")"

[[ -f deploy.state ]] || { echo "!! deploy.state missing — run provision.sh first." >&2; exit 1; }
# shellcheck disable=SC1091
source deploy.state

REPO_ROOT="$(cd .. && pwd)"
SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i ${KEY_FILE} ubuntu@${PUBLIC_IP}"
SCP="scp -o StrictHostKeyChecking=accept-new -i ${KEY_FILE}"

# ── App secrets: generated once, persisted (gitignored), reused on redeploys ──
if [[ ! -f .secrets.env ]]; then
  echo ">> Generating app secrets → deploy/.secrets.env (gitignored, keep private)…"
  {
    echo "SESSION_SECRET=$(openssl rand -hex 32)"
    echo "HMAC_SECRET=$(openssl rand -hex 32)"
    echo "API_KEY_PEPPER=$(openssl rand -base64 32)"
    echo "DASHBOARD_SESSION_SECRET=$(openssl rand -base64 32)"
    echo "MAGIC_LINK_SECRET=$(openssl rand -base64 32)"
    echo "PGPASS=$(openssl rand -hex 16)"
  } > .secrets.env
fi
# shellcheck disable=SC1091
source .secrets.env

echo ">> Waiting for the box to finish first-boot setup (Docker install + swap)…"
for i in $(seq 1 60); do
  if $SSH "test -f /opt/cadverify/.cloud-init-done" 2>/dev/null; then echo "   ready."; break; fi
  sleep 10
  [[ $i -eq 60 ]] && { echo "!! Timed out waiting for cloud-init. SSH in and check: $SSH" >&2; exit 1; }
done

echo ">> Packaging source (excluding heavy build dirs)…"
TARBALL="$(mktemp -t cadverify-src.XXXXXX).tgz"
tar czf "$TARBALL" -C "$REPO_ROOT" \
  --exclude='node_modules' --exclude='.venv' --exclude='.next' --exclude='.git' \
  --exclude='build' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='*.zip' --exclude='.vercel' --exclude='tsconfig.tsbuildinfo' \
  backend frontend

echo ">> Rendering .env (server IP + secrets)…"
cat > .env.rendered <<EOF
RELEASE=1.0.0
AUTH_MODE=password
LOG_LEVEL=INFO
SAM3D_ENABLED=false
ACCEPTING_NEW_ANALYSES=true
RATE_LIBRARY_ENABLED=1
DESIGN_INTELLIGENCE_ENABLED=1
ANALYSIS_TIMEOUT_SEC=60
MAX_UPLOAD_MB=100
POSTGRES_PASSWORD=${PGPASS}
DATABASE_URL=postgresql://cadverify:${PGPASS}@postgres:5432/cadverify
DATABASE_URL_DIRECT=postgresql://cadverify:${PGPASS}@postgres:5432/cadverify
REDIS_URL=redis://redis:6379/0
BLOB_STORAGE_PATH=/data/blobs
CORS_ORIGIN_REGEX=^http://${PUBLIC_IP}(:\d+)?\$
ALLOWED_ORIGINS=http://${PUBLIC_IP}:3000
SESSION_SECRET=${SESSION_SECRET}
HMAC_SECRET=${HMAC_SECRET}
API_KEY_PEPPER=${API_KEY_PEPPER}
DASHBOARD_SESSION_SECRET=${DASHBOARD_SESSION_SECRET}
MAGIC_LINK_SECRET=${MAGIC_LINK_SECRET}
API_BASE=http://backend:8000
NEXT_PUBLIC_API_BASE=http://${PUBLIC_IP}:8000
NEXT_PUBLIC_VERIFY_UI=1
NEXT_PUBLIC_DESIGN_INTELLIGENCE=1
NEXT_PUBLIC_SHOW_DEV_TOOLS=0
NEXT_PUBLIC_TURNSTILE_SITEKEY=1x00000000000000000000AA
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
RESEND_API_KEY=
SENTRY_DSN=
EOF

echo ">> Uploading source + config…"
$SSH "mkdir -p /opt/cadverify"
$SCP "$TARBALL"                ubuntu@"${PUBLIC_IP}":/opt/cadverify/src.tgz
$SCP docker-compose.prod.yml   ubuntu@"${PUBLIC_IP}":/opt/cadverify/docker-compose.yml
$SCP .env.rendered             ubuntu@"${PUBLIC_IP}":/opt/cadverify/.env
$SCP Dockerfile.frontend.prod  ubuntu@"${PUBLIC_IP}":/opt/cadverify/Dockerfile.frontend.prod
rm -f "$TARBALL" .env.rendered

echo ">> Building + starting the stack on the box (first build takes several minutes)…"
$SSH bash -s <<'REMOTE'
set -euo pipefail
cd /opt/cadverify
tar xzf src.tgz && rm -f src.tgz
# Use the build-arg-aware frontend Dockerfile (repo copy is left untouched)
cp Dockerfile.frontend.prod frontend/Dockerfile

# Bring up datastores first, then migrate, then the app.
docker compose up -d postgres redis
echo "   waiting for postgres…"
until docker compose exec -T postgres pg_isready -U cadverify >/dev/null 2>&1; do sleep 2; done

echo "   building backend image (for migrations)…"
docker compose build backend
echo "   running database migrations (alembic upgrade head)…"
# DATABASE_URL in .env already points straight at postgres (no pooler here),
# and the backend service reads it via env_file, so plain alembic works.
docker compose run --rm backend alembic upgrade head

echo "   building + starting all services…"
docker compose up -d --build

echo "   waiting for backend /health…"
for i in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then echo "   backend healthy."; break; fi
  sleep 5
done
docker compose ps
REMOTE

echo ""
echo "==================================================================="
echo " Deployed. Your app is live at:"
echo "   Frontend : http://${PUBLIC_IP}:3000"
echo "   API      : http://${PUBLIC_IP}:8000   (health: /health)"
echo ""
echo " Note: plain HTTP (no domain / HTTPS yet). Fine for testing."
echo "==================================================================="
