#!/usr/bin/env bash
set -Eeuo pipefail

required=(RELEASE_SHA AWS_RELEASE_IMAGE_ARCHIVE_DIR)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || {
    echo "missing required environment variable: $name" >&2
    exit 2
  }
done

for command_name in curl docker jq sha256sum; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "required command not found: $command_name" >&2
    exit 2
  }
done

[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "RELEASE_SHA must be a lowercase 40-character commit SHA" >&2
  exit 2
}

manifest="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/manifest.json"
backend_archive="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/backend.tar"
frontend_archive="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/frontend.tar"

for path in "$manifest" "$backend_archive" "$frontend_archive"; do
  [[ -f "$path" ]] || {
    echo "release image artifact is incomplete: $(basename "$path")" >&2
    exit 1
  }
done

verify_archive() {
  local component=$1
  local archive=$2
  local expected actual
  expected=$(jq -r --arg component "$component" '.images[$component].sha256 // empty' "$manifest")
  actual=$(sha256sum "$archive" | awk '{print $1}')
  [[ "$expected" =~ ^[0-9a-f]{64}$ && "$actual" == "$expected" ]] || {
    echo "$component archive does not match the sealed manifest" >&2
    exit 1
  }
}

verify_archive backend "$backend_archive"
verify_archive frontend "$frontend_archive"

docker load --input "$backend_archive" >/dev/null
docker load --input "$frontend_archive" >/dev/null

backend_image="proofshape-release/backend:${RELEASE_SHA}"
frontend_image="proofshape-release/frontend:${RELEASE_SHA}"
docker image inspect "$backend_image" >/dev/null
docker image inspect "$frontend_image" >/dev/null

# Exercise the contract from the exact backend archive without AWS credentials
# or network access. This proves direct uploads cannot silently inherit the
# durable, versioned evidence bucket.
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -e OBJECT_STORE_BACKEND=s3 \
  -e OBJECT_STORE_S3_BUCKET=proofshape-durable-contract \
  -e OBJECT_STORE_S3_PREFIX=staging \
  -e OBJECT_STORE_S3_REGION=us-east-1 \
  -e DIRECT_UPLOAD_S3_BUCKET=proofshape-transient-contract \
  -e DIRECT_UPLOAD_S3_PREFIX=staging \
  -e DIRECT_UPLOAD_S3_REGION=us-east-1 \
  -e DIRECT_UPLOAD_S3_KMS_KEY_ID=arn:aws:kms:us-east-1:111111111111:key/11111111-1111-1111-1111-111111111111 \
  --entrypoint python \
  "$backend_image" \
  -c 'from src.storage.factory import get_direct_upload_store, get_object_store; durable = get_object_store("health", default_root="/tmp/unused"); transient = get_direct_upload_store(); assert durable._bucket == "proofshape-durable-contract"; assert durable._prefix == "staging/health"; assert transient._bucket == "proofshape-transient-contract"; assert transient._prefix == "staging/direct-uploads"; assert durable._bucket != transient._bucket'

direct_upload_origin=https://proofshape-transient-contract.s3.us-east-1.amazonaws.com
auth_proxy_secret=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=
frontend_container=""
cleanup() {
  if [[ -n "$frontend_container" ]]; then
    docker rm -f "$frontend_container" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# Start the exact frontend archive under the same read-only/runtime guardrails
# used by ECS, then prove its served build identity and narrowly scoped S3 CSP.
frontend_container=$(docker run --detach \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --tmpfs /app/.next/cache:rw,noexec,nosuid,size=64m \
  --publish 127.0.0.1::3000 \
  -e API_BASE=https://proofshape.invalid \
  -e API_ORIGIN=https://proofshape.invalid \
  -e AUTH_PROXY_CLIENT_IP_SOURCE=cloudfront \
  -e AUTH_PROXY_SECRET="$auth_proxy_secret" \
  -e DASHBOARD_ORIGIN=https://proofshape.invalid \
  -e DIRECT_UPLOAD_ORIGIN="$direct_upload_origin" \
  -e MAGIC_LINK_UI_ENABLED=1 \
  -e PRODUCTION_AUTH_PROXY_REQUIRED=1 \
  -e PRODUCTION_DIRECT_UPLOAD_REQUIRED=1 \
  -e PRODUCTION_PUBLIC_API_TLS_REQUIRED=1 \
  -e PRODUCTION_VERIFIED_SIGNUP_REQUIRED=1 \
  -e PROOFSHAPE_BUILD_ID="$RELEASE_SHA" \
  -e PUBLIC_PASSWORD_SIGNUP_ENABLED=0 \
  -e RELEASE="$RELEASE_SHA" \
  -e TURNSTILE_SITE_KEY=proofshape-contract-site-key \
  "$frontend_image")

host_port=$(docker port "$frontend_container" 3000/tcp | awk -F: 'NR == 1 {print $NF}')
[[ "$host_port" =~ ^[0-9]+$ ]] || {
  echo "could not resolve the exact frontend image's published port" >&2
  exit 1
}

headers=$(mktemp)
body=$(mktemp)
trap 'rm -f "$headers" "$body"; cleanup' EXIT
ready=false
for _ in $(seq 1 60); do
  if curl --silent --show-error --max-time 5 \
    --dump-header "$headers" \
    --output "$body" \
    "http://127.0.0.1:${host_port}/"; then
    ready=true
    break
  fi
  sleep 1
done

if [[ "$ready" != true ]]; then
  docker logs "$frontend_container" >&2 || true
  echo "exact frontend image did not become ready" >&2
  exit 1
fi

build_header=$(awk 'BEGIN {IGNORECASE=1} /^x-proofshape-build:/ {sub(/^[^:]+:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit}' "$headers")
csp_header=$(awk 'BEGIN {IGNORECASE=1} /^content-security-policy:/ {sub(/^[^:]+:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit}' "$headers")
[[ "$build_header" == "$RELEASE_SHA" ]] || {
  echo "exact frontend image served an unexpected build identity" >&2
  exit 1
}
[[ "$csp_header" == *"connect-src"* && "$csp_header" == *"$direct_upload_origin"* ]] || {
  echo "exact frontend image CSP does not allow only the configured direct-upload origin" >&2
  exit 1
}
[[ "$csp_header" != *"*.amazonaws.com"* ]] || {
  echo "exact frontend image CSP contains a wildcard AWS origin" >&2
  exit 1
}

echo "Exact backend/frontend archives passed runtime storage, read-only filesystem, build identity, and CSP checks."
