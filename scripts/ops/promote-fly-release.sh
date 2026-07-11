#!/usr/bin/env bash
# Promote one immutable commercial release into a Fly environment.
#
# The caller must supply digest-qualified images from CI's release manifest.
# This script intentionally performs every read-only contract check before the
# backend deploy (which may run a database migration).
set -euo pipefail

require_env() {
  local name=$1
  if [[ -z "${!name:-}" ]]; then
    printf 'Required environment variable is missing: %s\n' "$name" >&2
    exit 1
  fi
}

for name in \
  FLY_API_TOKEN \
  FLY_API_APP \
  FLY_WEB_APP \
  FLY_TARGET_ENVIRONMENT \
  CADVERIFY_PUBLIC_API_BASE \
  CADVERIFY_DASHBOARD_ORIGIN \
  CADVERIFY_DEEP_HEALTH_TOKEN \
  CADVERIFY_RELEASE_SHA \
  CADVERIFY_BACKEND_IMAGE \
  CADVERIFY_FRONTEND_IMAGE; do
  require_env "$name"
done

for command_name in docker flyctl git node curl; do
  command -v "$command_name" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "$command_name" >&2
    exit 1
  }
done

case "$FLY_TARGET_ENVIRONMENT" in
  saas-staging|saas-production) ;;
  *)
    printf 'Unsupported target environment: %s\n' "$FLY_TARGET_ENVIRONMENT" >&2
    exit 1
    ;;
esac

case "$CADVERIFY_RELEASE_SHA" in
  *[!0-9a-f]*|'')
    printf 'CADVERIFY_RELEASE_SHA must be lowercase hexadecimal\n' >&2
    exit 1
    ;;
esac
[[ ${#CADVERIFY_RELEASE_SHA} -eq 40 ]] || {
  printf 'CADVERIFY_RELEASE_SHA must contain 40 characters\n' >&2
  exit 1
}

for app in "$FLY_API_APP" "$FLY_WEB_APP"; do
  [[ "$app" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]] || {
    printf 'Invalid Fly app name: %s\n' "$app" >&2
    exit 1
  }
done
[[ "$FLY_API_APP" != "$FLY_WEB_APP" ]] || {
  printf 'API and frontend must use different Fly apps\n' >&2
  exit 1
}

validate_image() {
  local image=$1
  local repository=$2
  local digest
  case "$image" in
    "$repository"@sha256:*) ;;
    *)
      printf 'Image must be a digest-qualified %s reference\n' "$repository" >&2
      exit 1
      ;;
  esac
  digest=${image##*@sha256:}
  case "$digest" in
    *[!0-9a-f]*|'')
      printf 'Image digest must be lowercase hexadecimal\n' >&2
      exit 1
      ;;
  esac
  [[ ${#digest} -eq 64 ]] || {
    printf 'Image digest must contain 64 hex characters\n' >&2
    exit 1
  }
}

validate_image "$CADVERIFY_BACKEND_IMAGE" "registry.fly.io/cadvrfy-api"
validate_image "$CADVERIFY_FRONTEND_IMAGE" "registry.fly.io/cadvrfy-web"

[[ "$(git rev-parse HEAD)" == "$CADVERIFY_RELEASE_SHA" ]] || {
  printf 'Checked-out commit does not match the requested release\n' >&2
  exit 1
}
git fetch --no-tags origin main
git merge-base --is-ancestor "$CADVERIFY_RELEASE_SHA" origin/main || {
  printf 'Requested release is not reachable from protected main\n' >&2
  exit 1
}

node scripts/ops/validate-https-origin.mjs "$CADVERIFY_PUBLIC_API_BASE"
node scripts/ops/validate-https-origin.mjs "$CADVERIFY_DASHBOARD_ORIGIN"
[[ "$CADVERIFY_PUBLIC_API_BASE" != "$CADVERIFY_DASHBOARD_ORIGIN" ]] || {
  printf 'API and dashboard origins must be distinct\n' >&2
  exit 1
}

# Authenticate and prove both immutable manifests exist before any application
# or database mutation.
flyctl auth docker
docker manifest inspect "$CADVERIFY_BACKEND_IMAGE" >/dev/null
docker manifest inspect "$CADVERIFY_FRONTEND_IMAGE" >/dev/null

FLY_APP_NAME="$FLY_API_APP" \
CADVERIFY_REQUIRE_PRODUCTION_STORAGE=1 \
CADVERIFY_REQUIRE_OBSERVABILITY=1 \
CADVERIFY_FORBIDDEN_FLY_SECRETS=DASHBOARD_ORIGIN,AUTH_MODE,MAGIC_LINK_ENABLED,PASSWORD_LOGIN_ENABLED,PUBLIC_PASSWORD_SIGNUP_ENABLED,SESSION_COOKIE_DOMAIN,OBJECT_STORE_BACKEND,RELEASE,DEPLOYMENT_ENVIRONMENT,SECRET_ENFORCEMENT_ENABLED,WEBHOOK_SSRF_GUARD_ENABLED,SECURITY_HEADERS_ENABLED,METRICS_ENABLED,RECONSTRUCTION_BACKEND,RECONSTRUCTION_ALLOW_REMOTE_EGRESS,PRODUCTION_STORAGE_REQUIRED,PRODUCTION_OBSERVABILITY_REQUIRED,PRODUCTION_TLS_REQUIRED,PRODUCTION_DEEP_HEALTH_AUTH_REQUIRED,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,PRODUCTION_HOST_ONLY_SESSION_COOKIE_REQUIRED,PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED,PRODUCTION_SSRF_GUARD_REQUIRED,PRODUCTION_SECURITY_HEADERS_REQUIRED,ASYNC_STRICT_HEALTH,WORKER_STRICT_HEALTH,RATE_LIMIT_ALLOW_MEMORY,DB_REQUIRE_TLS,NODE_ENV \
node scripts/ops/fly-required-secrets-gate.mjs

# Frontend-only runtime secrets. AUTH_PROXY_SECRET must equal the backend value;
# the post-deploy handshake below proves equality without exposing either one.
FLY_APP_NAME="$FLY_WEB_APP" \
CADVERIFY_REQUIRED_FLY_SECRETS=AUTH_PROXY_SECRET,TURNSTILE_SITE_KEY \
CADVERIFY_FORBIDDEN_FLY_SECRETS=AUTH_MODE,MAGIC_LINK_UI_ENABLED,PUBLIC_PASSWORD_SIGNUP_ENABLED,API_BASE,RELEASE,DEPLOYMENT_ENVIRONMENT,SSO_LOGIN_PATH,PRODUCTION_PUBLIC_API_TLS_REQUIRED,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,NODE_ENV \
node scripts/ops/fly-required-secrets-gate.mjs

flyctl deploy \
  --app "$FLY_API_APP" \
  --config backend/fly.toml \
  --image "$CADVERIFY_BACKEND_IMAGE" \
  --env "RELEASE=$CADVERIFY_RELEASE_SHA" \
  --env "DEPLOYMENT_ENVIRONMENT=$FLY_TARGET_ENVIRONMENT" \
  --env "DASHBOARD_ORIGIN=$CADVERIFY_DASHBOARD_ORIGIN" \
  --strategy rolling

flyctl scale count web=2 worker=2 --app "$FLY_API_APP" --yes
FLY_APP_NAME="$FLY_API_APP" \
FLY_REQUIRED_PROCESS_GROUPS=web,worker \
node scripts/ops/fly-ensure-process-groups.mjs

CADVERIFY_API_URL="$CADVERIFY_PUBLIC_API_BASE" \
CADVERIFY_REQUIRE_WORKER=1 \
CADVERIFY_REQUIRE_WORKER_STRICT=1 \
CADVERIFY_REQUIRE_DEEP=1 \
CADVERIFY_DEEP_HEALTH_TOKEN="$CADVERIFY_DEEP_HEALTH_TOKEN" \
node scripts/ops/fly-live-health-gate.mjs

flyctl deploy \
  --app "$FLY_WEB_APP" \
  --config frontend/fly.toml \
  --image "$CADVERIFY_FRONTEND_IMAGE" \
  --env "RELEASE=$CADVERIFY_RELEASE_SHA" \
  --env "DEPLOYMENT_ENVIRONMENT=$FLY_TARGET_ENVIRONMENT" \
  --env "API_BASE=$CADVERIFY_PUBLIC_API_BASE" \
  --strategy rolling

flyctl scale count 2 --app "$FLY_WEB_APP" --yes
curl --fail --silent --show-error --retry 12 --retry-all-errors \
  --retry-delay 5 --max-time 20 "$CADVERIFY_DASHBOARD_ORIGIN" >/dev/null
curl --fail --silent --show-error --retry 12 --retry-all-errors \
  --retry-delay 5 --max-time 20 \
  "$CADVERIFY_DASHBOARD_ORIGIN/api/auth/proxy-health" >/dev/null

evidence_dir=${CADVERIFY_EVIDENCE_DIR:-outputs/saas-promotion}
mkdir -p "$evidence_dir"
record="$evidence_dir/${FLY_TARGET_ENVIRONMENT}-${CADVERIFY_RELEASE_SHA}.txt"
printf '%s\n' \
  "environment=$FLY_TARGET_ENVIRONMENT" \
  "release_sha=$CADVERIFY_RELEASE_SHA" \
  "backend_image=$CADVERIFY_BACKEND_IMAGE" \
  "frontend_image=$CADVERIFY_FRONTEND_IMAGE" \
  "api_app=$FLY_API_APP" \
  "frontend_app=$FLY_WEB_APP" \
  "api_origin=$CADVERIFY_PUBLIC_API_BASE" \
  "dashboard_origin=$CADVERIFY_DASHBOARD_ORIGIN" \
  "verified_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$record"

printf 'Commercial promotion passed: %s\n' "$record"
