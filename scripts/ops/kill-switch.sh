#!/usr/bin/env bash
# Flip ACCEPTING_NEW_ANALYSES on an explicitly selected Fly API app.
#
# Usage: FLY_APP_NAME=<target-api-app> ./scripts/ops/kill-switch.sh {on|off}
#
# "off" causes POST /api/v1/validate to return 503 + Retry-After: 3600
# within 30 s of the secret propagating through fly.
set -euo pipefail
app=${FLY_APP_NAME:?Set FLY_APP_NAME to the exact target API app}
case "${1:-}" in
  off) flyctl secrets set --app "$app" ACCEPTING_NEW_ANALYSES=false ;;
  on)  flyctl secrets set --app "$app" ACCEPTING_NEW_ANALYSES=true ;;
  *)   echo "Usage: FLY_APP_NAME=<target-api-app> $0 {on|off}"; exit 1 ;;
esac
