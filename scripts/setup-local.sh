#!/usr/bin/env bash
# ProofShape one-command local setup.
#
#   bash scripts/setup-local.sh
#
# Safe to run more than once — every step checks before it acts. When it
# finishes it hands off to scripts/run-local-app.sh, which starts the app
# and opens http://localhost:3000 in your browser.
#
#   bash scripts/setup-local.sh --setup-only   # prepare everything, don't launch

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
SETUP_ONLY=0
[ "${1:-}" = "--setup-only" ] && SETUP_ONLY=1

say()  { printf '\n\033[1;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[setup]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[setup] PROBLEM:\033[0m %s\n' "$*" >&2; exit 1; }

OS="$(uname -s)"

# ── 1. Check the free tools are installed ────────────────────────────────────
say "Checking required tools…"

command -v git >/dev/null 2>&1 || fail "git is missing. macOS: install Xcode command line tools with:  xcode-select --install"

command -v python3 >/dev/null 2>&1 || fail "Python 3 is missing.
  macOS:  brew install python@3.12
  Ubuntu: sudo apt install python3 python3-venv python3-pip
Then re-run this script."

PYVER="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python $PYVER found, but 3.10 or newer is needed. macOS: brew install python@3.12"

command -v npm >/dev/null 2>&1 || fail "Node.js is missing.
  macOS:  brew install node
  Ubuntu: sudo apt install nodejs npm
Then re-run this script."

command -v psql >/dev/null 2>&1 || fail "PostgreSQL is missing.
  macOS:  brew install postgresql@16 && brew services start postgresql@16
  Ubuntu: sudo apt install postgresql && sudo service postgresql start
Then re-run this script."

command -v redis-server >/dev/null 2>&1 || command -v redis-cli >/dev/null 2>&1 || fail "Redis is missing.
  macOS:  brew install redis && brew services start redis
  Ubuntu: sudo apt install redis-server && sudo service redis-server start
Then re-run this script."

say "All tools found (Python $PYVER)."

# ── 2. Make sure PostgreSQL and Redis are actually running ───────────────────
say "Checking PostgreSQL is running…"
if ! pg_isready -q >/dev/null 2>&1; then
  warn "PostgreSQL is not running — trying to start it…"
  if [ "$OS" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    brew services start postgresql@16 >/dev/null 2>&1 || brew services start postgresql >/dev/null 2>&1 || true
  elif command -v service >/dev/null 2>&1; then
    sudo service postgresql start >/dev/null 2>&1 || service postgresql start >/dev/null 2>&1 || true
  fi
  sleep 3
  pg_isready -q >/dev/null 2>&1 || fail "Could not start PostgreSQL.
  macOS:  brew services start postgresql@16
  Ubuntu: sudo service postgresql start
Then re-run this script."
fi

say "Checking Redis is running…"
if ! redis-cli ping >/dev/null 2>&1; then
  warn "Redis is not running — trying to start it…"
  if [ "$OS" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    brew services start redis >/dev/null 2>&1 || true
  fi
  redis-server --daemonize yes >/dev/null 2>&1 || true
  sleep 2
  redis-cli ping >/dev/null 2>&1 || fail "Could not start Redis.
  macOS:  brew services start redis
  Ubuntu: sudo service redis-server start
Then re-run this script."
fi

# ── 3. Create the app's database user + database (skips if they exist) ──────
say "Setting up the local database…"
run_psql() {
  # Try in order: current user as superuser (Homebrew default), the
  # 'postgres' superuser role, then sudo as the postgres system user (Linux).
  psql -d postgres -v ON_ERROR_STOP=1 -qc "$1" 2>/dev/null && return 0
  psql -U postgres -d postgres -v ON_ERROR_STOP=1 -qc "$1" 2>/dev/null && return 0
  command -v sudo >/dev/null 2>&1 && sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 -qc "$1" 2>/dev/null && return 0
  return 1
}

DB_URL="postgresql://cadverify:localdev@localhost:5432/cadverify"
if ! PGPASSWORD=localdev psql "$DB_URL" -qc 'SELECT 1;' >/dev/null 2>&1; then
  run_psql "CREATE USER cadverify WITH PASSWORD 'localdev' CREATEDB;" || true
  run_psql "CREATE DATABASE cadverify OWNER cadverify;" || true
  PGPASSWORD=localdev psql "$DB_URL" -qc 'SELECT 1;' >/dev/null 2>&1 \
    || fail "Could not create the database. Ask for help with this one — copy the messages above."
fi
say "Database ready."

# ── 4. Python environment for the engine ─────────────────────────────────────
if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
  say "Creating the Python environment (one time)…"
  python3 -m venv "$BACKEND_DIR/.venv"
fi
say "Installing engine dependencies (first run takes several minutes — that's normal)…"
"$BACKEND_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$BACKEND_DIR/.venv/bin/pip" install --quiet -r "$BACKEND_DIR/requirements.txt"
"$BACKEND_DIR/.venv/bin/pip" install --quiet 'uvicorn[standard]' 2>/dev/null || true

# ── 5. Database tables ───────────────────────────────────────────────────────
say "Preparing database tables…"
( cd "$BACKEND_DIR" && DATABASE_URL="$DB_URL" .venv/bin/python -m alembic upgrade head >/dev/null )
say "Tables ready."

# ── 6. Web app dependencies ──────────────────────────────────────────────────
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  say "Installing web app dependencies (one time, a few minutes)…"
  ( cd "$FRONTEND_DIR" && npm install --no-audit --no-fund )
else
  say "Web app dependencies already installed."
fi

# ── 7. Launch ────────────────────────────────────────────────────────────────
say "Setup complete!"
if [ "$SETUP_ONLY" = "1" ]; then
  say "Run the app any time with:  bash scripts/run-local-app.sh"
  exit 0
fi
say "Starting ProofShape — your browser will open at http://localhost:3000 …"
exec bash "$REPO_ROOT/scripts/run-local-app.sh"
