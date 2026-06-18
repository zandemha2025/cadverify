#!/usr/bin/env bash
# Flip the ACCEPTING_NEW_ANALYSES kill-switch on or off for cadvrfy-api.
#
# Usage: ./scripts/ops/kill-switch.sh {on|off}
#
# "off" causes POST /api/v1/validate to return 503 + Retry-After: 3600
# within 30 s of the secret propagating through fly.
set -euo pipefail
case "${1:-}" in
  off)  fly secrets set ACCEPTING_NEW_ANALYSES=false -a cadvrfy-api
        fly deploy -a cadvrfy-api ;;
  on)   fly secrets set ACCEPTING_NEW_ANALYSES=true  -a cadvrfy-api
        fly deploy -a cadvrfy-api ;;
  *)    echo "Usage: $0 {on|off}"; exit 1 ;;
esac
