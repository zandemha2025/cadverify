#!/usr/bin/env bash
# ProofShape one-command launcher (macOS / Linux).
#
#   bash start-proofshape.sh
#
# Needs Docker Desktop (macOS) or Docker Engine + compose plugin (Linux).
# Safe to run repeatedly: the first run builds everything (10-20 minutes);
# later runs start in seconds. Your data survives restarts (Docker volumes).
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1;36m[proofshape]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[proofshape] PROBLEM:\033[0m %s\n' "$*" >&2; read -r -p "Press Enter to close..." _ 2>/dev/null || true; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker is not installed.
Download Docker Desktop from https://www.docker.com/products/docker-desktop/
install it, open it once, then run this again."

docker info >/dev/null 2>&1 || fail "Docker is installed but not running.
Open the Docker Desktop app, wait for the whale icon to settle, then run this again."

# First run: create .env from the template with real generated secrets.
if [ ! -f .env ]; then
  say "First run — creating local configuration…"
  cp .env.example .env
  gen() { openssl rand -base64 32; }
  for key in SESSION_SECRET HMAC_SECRET API_KEY_PEPPER DASHBOARD_SESSION_SECRET MAGIC_LINK_SECRET AUTH_PROXY_SECRET; do
    secret="$(gen)"
    # Replace the whole line for this key, whatever its current value.
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$secret" 'BEGIN{FS=OFS="="} $1==k{$0=k"="v} {print}' .env > "$tmp" && mv "$tmp" .env
  done
  say "Configuration written to .env (keep this file private)."
fi

say "Building and starting ProofShape (first time takes 10-20 minutes)…"
docker compose up -d --build

say "Waiting for the app to come up…"
for _ in $(seq 1 90); do
  if curl -fsS -o /dev/null http://localhost:3000/ 2>/dev/null; then
    say "ProofShape is running at http://localhost:3000"
    (open "http://localhost:3000" 2>/dev/null || xdg-open "http://localhost:3000" 2>/dev/null || true)
    say "First visit: click Sign up, choose any email + password (8+ chars, a letter and a digit)."
    say "To stop later:  docker compose down     (your data is kept)"
    exit 0
  fi
  sleep 10
done
fail "The app did not come up in time. Run 'docker compose logs --tail 50' in this folder and send me the output."
