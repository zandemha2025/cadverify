#!/usr/bin/env bash
# ProofShape — one-step LOCAL web app launcher (macOS).
#
# Double-click this file in Finder, or run:  bash scripts/run-local-app.sh
#
# It will:
#   1. ensure the local database schema (alembic upgrade head)
#   2. start the backend  (FastAPI / uvicorn) on  http://127.0.0.1:8000
#   3. start the frontend (Next.js dev)       on  http://localhost:3000
#   4. wait for both to be up
#   5. open  http://localhost:3000  (the marketing site → Sign up / Log in)
#   6. keep both running until you press Ctrl-C, which stops them cleanly
#
# REAL ACCOUNTS: the whole platform is gated behind Sign up / Log in. Create an
# account with an email + password (>=8 chars, a letter and a digit), then you're
# in. Accounts + sessions live in your LOCAL Postgres; your CAD never leaves this
# machine. (Google / magic-link / SAML are wired but need deploy credentials.)
#
# Safe to re-run: it frees ports 8000 and 3000 first, and reuses your saved
# session secret so existing logins keep working across restarts.

set -u

# ── resolve repo layout (works double-clicked or run from anywhere) ─────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
VENV_ARQ="$BACKEND_DIR/.venv/bin/arq"
# Put long-running child services in their own sessions. A terminal Ctrl-C then
# reaches this launcher only; cleanup can send each service an orderly SIGTERM
# instead of Python CAD-pool children all receiving SIGINT simultaneously.
ISOLATED_EXEC=(
  "$VENV_PY" -c
  'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])'
)

BACKEND_PORT=8000
FRONTEND_PORT=3000
HEALTH_URL="http://127.0.0.1:${BACKEND_PORT}/health"
APP_URL="http://localhost:${FRONTEND_PORT}"

# ── env: kill-switch open + localhost CORS + local database ─────────────────
export ACCEPTING_NEW_ANALYSES=true   # kill-switch OPEN -> analyses accepted
export LABELING_ENABLED=1            # main.py broadens CORS to localhost:3000
export RATE_LIBRARY_ENABLED=1        # enterprise governed rate cards are active
export SIGNUP_RATE_LIMIT_DISABLED=1  # local proof runs create many throwaway accounts
export DATABASE_URL="${DATABASE_URL:-postgresql://cadverify:localdev@localhost:5432/cadverify}"
# Container defaults use /data/blobs, which is not writable on a normal macOS
# host. Keep every local object-store namespace under the ignored project data
# directory unless the operator explicitly supplies another local root.
export OBJECT_STORE_LOCAL_ROOT="${OBJECT_STORE_LOCAL_ROOT:-$REPO_ROOT/data/local-blobs}"

# WeasyPrint's macOS wheels load Pango/GLib through cffi. Homebrew installs the
# correct dylibs, but they are outside the default loader path used by the
# bundled Python runtime. Make local RFQ/PDF exports use the same real renderer
# as the Linux container instead of silently falling back to pdf-unavailable.
if [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
  HOMEBREW_LIB="$(brew --prefix)/lib"
  if [ -d "$HOMEBREW_LIB" ]; then
    export DYLD_FALLBACK_LIBRARY_PATH="$HOMEBREW_LIB${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
  fi
fi

# Persistent local auth secrets so sessions survive restarts (gitignored file).
AUTH_ENV_FILE="$REPO_ROOT/.env.local-auth"
if [ -f "$AUTH_ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$AUTH_ENV_FILE"
else
  DASHBOARD_SESSION_SECRET="$(openssl rand -base64 32)"
  API_KEY_PEPPER="$(openssl rand -base64 32)"
  { printf "DASHBOARD_SESSION_SECRET='%s'\n" "$DASHBOARD_SESSION_SECRET";
    printf "API_KEY_PEPPER='%s'\n" "$API_KEY_PEPPER"; } > "$AUTH_ENV_FILE"
  chmod 600 "$AUTH_ENV_FILE"
fi
export DASHBOARD_SESSION_SECRET API_KEY_PEPPER

# Background jobs (SAM-3D reconstruction, batch analyses) run in the arq worker,
# which — like the backend's arq client — talks to Redis. Both default to the
# same local Redis when REDIS_URL is unset; we only *start* the worker if that
# Redis is actually reachable (see below), so a missing Redis is a clear warning
# instead of a crash-looping process.
REDIS_URL_EFFECTIVE="${REDIS_URL:-redis://localhost:6379}"

BACK_PID=""
FRONT_PID=""
WORKER_PID=""

log()  { printf '\033[1;36m[proofshape]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[proofshape]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[proofshape]\033[0m %s\n' "$*" >&2; }

port_listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }

free_port() {
  local port="$1" pids
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    warn "Port $port busy — stopping PID(s): $(echo "$pids" | tr '\n' ' ')"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
    if [ -n "$pids" ]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
      sleep 1
    fi
  fi
}

cleanup() {
  trap - INT TERM EXIT
  echo
  log "Shutting down…"
  [ -n "$FRONT_PID" ]  && kill "$FRONT_PID"  2>/dev/null || true
  [ -n "$WORKER_PID" ] && kill "$WORKER_PID" 2>/dev/null || true
  [ -n "$BACK_PID" ]   && kill "$BACK_PID"   2>/dev/null || true
  sleep 1
  free_port "$BACKEND_PORT"
  free_port "$FRONTEND_PORT"
  log "Stopped. Your CAD never left this machine."
}
trap cleanup INT TERM EXIT

# ── preflight ───────────────────────────────────────────────────────────────
[ -x "$VENV_PY" ] || { err "Python venv not found at $VENV_PY"; exit 1; }
"$VENV_PY" -c "import uvicorn" 2>/dev/null || {
  err "uvicorn not installed in the venv. Run:  $VENV_PY -m pip install 'uvicorn[standard]'"; exit 1; }
if ! "$VENV_PY" -c "from weasyprint import HTML" >/dev/null 2>&1; then
  warn "WeasyPrint native libraries are unavailable — RFQ PDF export will fail."
  warn "On macOS install them with: brew install pango"
fi
command -v npm >/dev/null 2>&1 || { err "npm not found on PATH."; exit 1; }
[ -d "$FRONTEND_DIR/node_modules" ] || {
  err "frontend/node_modules missing. Run:  (cd '$FRONTEND_DIR' && npm install)"; exit 1; }
mkdir -p "$OBJECT_STORE_LOCAL_ROOT" || {
  err "Could not create local object storage at $OBJECT_STORE_LOCAL_ROOT"; exit 1; }
[ -w "$OBJECT_STORE_LOCAL_ROOT" ] || {
  err "Local object storage is not writable: $OBJECT_STORE_LOCAL_ROOT"; exit 1; }

# ── ensure the database schema (idempotent) ─────────────────────────────────
log "Ensuring database schema (alembic upgrade head)…"
if ! ( cd "$BACKEND_DIR" && "$VENV_PY" -m alembic upgrade head ) >/dev/null 2>&1; then
  warn "Could not apply migrations. Is local Postgres running on :5432 with the 'cadverify' role/db?"
  warn "First-time setup (run once):"
  warn "  psql -h localhost -p 5432 -d postgres -c \"CREATE ROLE cadverify LOGIN PASSWORD 'localdev';\""
  warn "  psql -h localhost -p 5432 -d postgres -c \"CREATE DATABASE cadverify OWNER cadverify;\""
  warn "  then re-run this script. (Or set DATABASE_URL to your own Postgres.)"
fi

# ── idempotent: free the ports first ────────────────────────────────────────
free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

# ── start backend ───────────────────────────────────────────────────────────
log "Starting backend (uvicorn) on http://127.0.0.1:${BACKEND_PORT} …"
(
  # The terminal sends Ctrl-C to the whole foreground process group. Child
  # services must leave SIGINT to this launcher; otherwise every CAD pool child
  # prints a KeyboardInterrupt before the parent can perform its orderly TERM
  # shutdown. SIG_IGN survives exec, while cleanup below still sends SIGTERM.
  trap '' INT
  cd "$BACKEND_DIR" || exit 1
  # multiple workers so the part's cost + DFM analyses run in parallel (faster resolve)
  exec "${ISOLATED_EXEC[@]}" "$VENV_PY" -m uvicorn main:app --host 127.0.0.1 --port "$BACKEND_PORT" --workers 4
) &
BACK_PID=$!

# ── start the arq worker (background jobs), only if Redis is reachable ───────
# fly.toml runs this as its own 'worker' process; locally nothing else does.
# Same env as the backend (DATABASE_URL etc.); talks to REDIS_URL_EFFECTIVE.
if [ -x "$VENV_ARQ" ] && REDIS_PROBE_URL="$REDIS_URL_EFFECTIVE" "$VENV_PY" -c \
     "import os,redis; redis.from_url(os.environ['REDIS_PROBE_URL'], socket_connect_timeout=2).ping()" \
     >/dev/null 2>&1; then
  log "Starting arq worker (background jobs) — Redis at ${REDIS_URL_EFFECTIVE} …"
  (
    trap '' INT
    cd "$BACKEND_DIR" || exit 1
    exec "${ISOLATED_EXEC[@]}" "$VENV_ARQ" src.jobs.worker.WorkerSettings
  ) &
  WORKER_PID=$!
else
  warn "Redis not reachable at ${REDIS_URL_EFFECTIVE} — NOT starting the arq worker."
  warn "Background jobs (SAM-3D reconstruction, batch analyses) will not run."
  warn "Start Redis (e.g. 'brew services start redis') and re-run to enable them."
fi

# ── build + start frontend (PRODUCTION build = fast + stable; no dev "rendering" jank) ──
export API_BASE="http://localhost:${BACKEND_PORT}"
# Mount the product /verify surface. NEXT_PUBLIC_* is inlined at BUILD time, so
# this MUST be exported before `npm run build` (flag-off, /verify 404s).
export NEXT_PUBLIC_VERIFY_UI=1
export NEXT_PUBLIC_SHOW_DEV_TOOLS=1
log "Building the frontend (production build — ~1–2 min the first time; instant after)…"
if ! ( cd "$FRONTEND_DIR" && npm run build ); then
  err "Frontend build failed — see the output above."; exit 1
fi
log "Starting frontend (Next.js production) on http://localhost:${FRONTEND_PORT} …"
(
  trap '' INT
  cd "$FRONTEND_DIR" || exit 1
  exec "${ISOLATED_EXEC[@]}" npm start -- -p "$FRONTEND_PORT"
) &
FRONT_PID=$!

# ── wait for the backend to start serving HTTP ──────────────────────────────
log "Waiting for backend to be ready…"
backend_ok=0
for _ in $(seq 1 60); do
  if ! kill -0 "$BACK_PID" 2>/dev/null; then
    err "Backend process exited before becoming ready. See output above."; exit 1; fi
  if curl -sS -o /dev/null --max-time 2 "$HEALTH_URL" 2>/dev/null; then backend_ok=1; break; fi
  sleep 1
done
if [ "$backend_ok" = 1 ]; then
  log "Backend is up (serving on :${BACKEND_PORT})."
else
  warn "Backend not detected yet; continuing anyway."
fi

# ── wait for the frontend port to be listening ──────────────────────────────
log "Waiting for frontend to be ready (first compile can take ~10-30s)…"
frontend_ok=0
for _ in $(seq 1 90); do
  if ! kill -0 "$FRONT_PID" 2>/dev/null; then
    err "Frontend process exited before becoming ready. See output above."; exit 1; fi
  if port_listening "$FRONTEND_PORT"; then frontend_ok=1; break; fi
  sleep 1
done
if [ "$frontend_ok" = 1 ]; then
  log "Frontend is up: http://localhost:${FRONTEND_PORT}"
else
  warn "Frontend not detected yet; opening the browser anyway."
fi

# ── open the app ────────────────────────────────────────────────────────────
log "Opening $APP_URL …"
open "$APP_URL" 2>/dev/null || warn "Could not auto-open the browser. Visit $APP_URL manually."

echo
log "ProofShape is running."
log "  • App:      $APP_URL   (Sign up / Log in to enter the platform)"
log "  • Backend:  http://127.0.0.1:${BACKEND_PORT}"
[ -n "$WORKER_PID" ] && log "  • Worker:   arq (PID $WORKER_PID) — background jobs on ${REDIS_URL_EFFECTIVE}"
log "  • First sign-up: email + password (>=8 chars, a letter and a digit)."
log "Press Ctrl-C in this window to stop everything."
echo

# Stay alive until Ctrl-C; the trap handles a clean shutdown of both servers.
wait
