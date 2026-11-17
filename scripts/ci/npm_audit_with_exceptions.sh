#!/usr/bin/env bash
# npm audit with a documented, reviewable exception list.
#
# `npm audit` alone has no exception mechanism, so an unpatchable transitive
# (no fixed release exists) blocks every PR. This wrapper fails on every
# vulnerability EXCEPT advisories listed in frontend/.audit-exceptions with
# a reason. Every exception is a deliberate, visible decision.
set -euo pipefail
cd "$(dirname "$0")/../../frontend"

EXCEPTIONS_FILE=.audit-exceptions
mapfile -t ALLOWED < <(grep -Ev '^\s*(#|$)' "$EXCEPTIONS_FILE" | cut -d'|' -f1 | tr -d ' ')

report=$(npm audit --omit=dev --json 2>/dev/null || true)
if [ -z "$report" ]; then
  echo "npm audit produced no output" >&2
  exit 1
fi

fails=$(python3 - "$report" "${ALLOWED[@]}" <<'PY'
import json, sys

report = json.loads(sys.argv[1])
allowed = set(sys.argv[2:])
vulns = report.get("vulnerabilities") or {}


def ghsas_of(name, seen=None):
    """All GHSA ids behind a package, following transitive ('via' package
    name) chains so a carrier that merely DEPENDS on an allowed advisory is
    itself allowed — and a carrier of anything unallowed is not."""
    seen = seen or set()
    if name in seen or name not in vulns:
        return set()
    seen.add(name)
    ids = set()
    for via in vulns[name].get("via", []):
        if isinstance(via, dict):
            g = via.get("url", "").rsplit("/", 1)[-1]
            if g.startswith("GHSA"):
                ids.add(g)
        else:  # a package-name string: the advisory lives downstream
            ids |= ghsas_of(via, seen)
    return ids


unhandled = []
for name, info in vulns.items():
    if info.get("severity") not in ("moderate", "high", "critical"):
        continue
    ids = ghsas_of(name)
    if not ids or (ids & allowed):
        continue
    unhandled.append(f"{name}: {sorted(ids)} severity={info.get('severity')}")
if unhandled:
    print("\n".join(unhandled))
PY
)

if [ -n "$fails" ]; then
  echo "npm audit: unhandled vulnerabilities:" >&2
  echo "$fails" >&2
  echo "(to accept one deliberately, add its GHSA id + reason to frontend/.audit-exceptions)" >&2
  exit 1
fi
echo "npm audit: pass (exceptions: ${#ALLOWED[@]} documented in frontend/.audit-exceptions)"
