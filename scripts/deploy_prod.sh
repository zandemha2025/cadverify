#!/usr/bin/env bash
# Atomic 3-service production deploy for ScaleCAD on Render.
#
# Deploys cadverify-worker, cadverify-api and cadverify-web to the SAME commit
# (default: origin/main) and verifies the deployed build afterwards:
#   - API /health build_id must equal the deployed SHA
#   - /health status must be ok with a live worker heartbeat
#   - web deploy must be live and answer 200
#
# Every previous live deploy ID is printed first as a 1-click rollback anchor
# (Render dashboard -> service -> deploys, or `render deploys list <id>`).
#
# Usage:
#   scripts/deploy_prod.sh              # deploy origin/main tip
#   scripts/deploy_prod.sh <sha>        # deploy an explicit commit
#
# Requires: git, curl, and an authenticated Render CLI (`render login`).

set -euo pipefail

API_SERVICE=srv-daibaifqj5pc739cvas0
WORKER_SERVICE=srv-dajgag0ae00c739s91h0
WEB_SERVICE=srv-daiqvcrm8hqs73duucd0
API_HEALTH=https://cadverify-api.onrender.com/health
WEB_URL=https://scalecad.ai/login
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '[deploy_prod] %s\n' "$*"; }
die() { printf '[deploy_prod] FAIL: %s\n' "$*" >&2; exit 1; }

command -v render >/dev/null 2>&1 || die "Render CLI not found (brew install render-cli)"
render whoami >/dev/null 2>&1 || die "Render CLI not authenticated (render login)"

cd "$REPO_ROOT"
git fetch origin main --quiet

SHA="${1:-$(git rev-parse origin/main)}"
git cat-file -e "${SHA}^{commit}" 2>/dev/null || die "commit ${SHA} not found locally"
if ! git merge-base --is-ancestor "$SHA" origin/main; then
  die "refusing: ${SHA} is not on origin/main"
fi
log "target commit: ${SHA} ($(git log -1 --format=%s "$SHA"))"

rollback_anchor() {
  render deploys list "$1" -o json 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("unknown"); raise SystemExit
live = next((x for x in d if x.get("status") == "live"), None)
if not live:
    print("none"); raise SystemExit
c = live.get("commit") or {}
print(live["id"], "@", str(c.get("id", "?"))[:9])
'
}

log "rollback anchors (current live deploys):"
log "  api:    $(rollback_anchor "$API_SERVICE")"
log "  worker: $(rollback_anchor "$WORKER_SERVICE")"
log "  web:    $(rollback_anchor "$WEB_SERVICE")"

deploy_one() {
  local name="$1" id="$2"
  log "deploying ${name} -> ${SHA:0:9}"
  render deploys create "$id" --commit "$SHA" --wait --confirm >/dev/null \
    || die "${name} deploy failed; rollback via the anchors above"
}

# Worker first so it never lags the API that enqueues onto it.
deploy_one worker "$WORKER_SERVICE"
deploy_one api    "$API_SERVICE"
deploy_one web    "$WEB_SERVICE"

log "verifying API /health build parity (up to 5 min)..."
deadline=$((SECONDS + 300))
while (( SECONDS < deadline )); do
  body="$(curl -fs --max-time 20 "$API_HEALTH" 2>/dev/null || true)"
  if [ -n "$body" ]; then
    if python3 - "$body" "$SHA" <<'PY'
import json, sys
try:
    h = json.loads(sys.argv[1])
except Exception:
    sys.exit(1)
ok = (
    h.get("build_id") == sys.argv[2]
    and h.get("status") == "ok"
    and h.get("postgres") is True
    and h.get("async", {}).get("worker") == "ok"
)
sys.exit(0 if ok else 1)
PY
    then
      log "API verified: build_id == ${SHA:0:9}, status ok, worker heartbeat ok"
      break
    fi
  fi
  sleep 10
done
if (( SECONDS >= deadline )); then
  die "API /health did not report build ${SHA:0:9} within 5 minutes"
fi

log "verifying web answers..."
code="$(curl -fs -o /dev/null -w '%{http_code}' --max-time 30 "$WEB_URL" || true)"
[ "$code" = "200" ] || die "web returned HTTP ${code} (expected 200)"

log "OK: worker + api + web live on ${SHA:0:9}, build parity verified."
log "web build parity is enforced by deploying the same SHA above; the web has"
log "no /health endpoint, so its check is deploy status + HTTP 200."
