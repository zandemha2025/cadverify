#!/usr/bin/env bash
# Validate required Kubernetes Secret keys without printing values. For SAML,
# the gate decodes the two JSON documents only into a pipe to jq so a weak IdP
# profile cannot pass merely because the files exist.
set -euo pipefail

NAMESPACE="${CADVERIFY_NAMESPACE:-cadverify}"
RUNTIME_SECRET="${CADVERIFY_RUNTIME_SECRET:-cadverify-runtime}"
AUTH_MODE="${CADVERIFY_AUTH_MODE:-saml}"
SAML_SECRET="${CADVERIFY_SAML_SECRET:-cadverify-saml}"
OTEL_CA_SECRET="${CADVERIFY_OTEL_CA_SECRET:-}"
OTEL_CA_KEY="${CADVERIFY_OTEL_CA_KEY:-ca.crt}"

command -v kubectl >/dev/null 2>&1 || {
  echo "kubectl is required" >&2
  exit 2
}
command -v jq >/dev/null 2>&1 || {
  echo "jq is required" >&2
  exit 2
}
command -v base64 >/dev/null 2>&1 || {
  echo "base64 is required" >&2
  exit 2
}

kubectl get namespace "$NAMESPACE" >/dev/null
kubectl get secret "$RUNTIME_SECRET" --namespace "$NAMESPACE" >/dev/null

required_runtime_keys=(
  DATABASE_URL
  DATABASE_URL_DIRECT
  REDIS_URL
  SESSION_SECRET
  DASHBOARD_SESSION_SECRET
  AUTH_PROXY_SECRET
  API_KEY_PEPPER
  CONNECTOR_SECRET_KEY
  CONNECTOR_FINGERPRINT_KEY
  DASHBOARD_ORIGIN
  DEEP_HEALTH_TOKEN
)

if [[ "$AUTH_MODE" == "password" || "$AUTH_MODE" == "hybrid" ]]; then
  required_runtime_keys+=(
    MAGIC_LINK_SECRET
    RESEND_API_KEY
    RESEND_FROM
    TURNSTILE_SECRET
    TURNSTILE_SITE_KEY
  )
fi

missing=()
forbidden=()
for key in "${required_runtime_keys[@]}"; do
  value="$(kubectl get secret "$RUNTIME_SECRET" \
    --namespace "$NAMESPACE" \
    --output "go-template={{ index .data \"$key\" }}")"
  if [[ -z "$value" || "$value" == "<no value>" ]]; then
    missing+=("$RUNTIME_SECRET/$key")
  fi
done

# The approved SAML baseline uses workload identity, in-boundary OTLP, and
# local/disabled reconstruction. Reject stale credentials that would bypass
# those boundaries or let an envFrom Secret silently select an external path.
if [[ "$AUTH_MODE" == "saml" ]]; then
  forbidden_runtime_keys=(
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_SESSION_TOKEN
    SENTRY_DSN
    NEXT_PUBLIC_SENTRY_DSN
    RESEND_API_KEY
    RESEND_FROM
    MAGIC_LINK_SECRET
    TURNSTILE_SECRET
    TURNSTILE_SITE_KEY
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    OIDC_CLIENT_ID
    OIDC_CLIENT_SECRET
    REPLICATE_API_TOKEN
  )
  for key in "${forbidden_runtime_keys[@]}"; do
    value="$(kubectl get secret "$RUNTIME_SECRET" \
      --namespace "$NAMESPACE" \
      --output "go-template={{ index .data \"$key\" }}")"
    if [[ -n "$value" && "$value" != "<no value>" ]]; then
      forbidden+=("$RUNTIME_SECRET/$key")
    fi
  done
fi

if [[ "$AUTH_MODE" == "saml" || "$AUTH_MODE" == "hybrid" ]]; then
  kubectl get secret "$SAML_SECRET" --namespace "$NAMESPACE" >/dev/null
  for key in settings.json advanced_settings.json; do
    value="$(kubectl get secret "$SAML_SECRET" \
      --namespace "$NAMESPACE" \
      --output "go-template={{ index .data \"$key\" }}")"
    if [[ -z "$value" || "$value" == "<no value>" ]]; then
      missing+=("$SAML_SECRET/$key")
    fi
  done
fi

if [[ -n "$OTEL_CA_SECRET" ]]; then
  kubectl get secret "$OTEL_CA_SECRET" --namespace "$NAMESPACE" >/dev/null
  value="$(kubectl get secret "$OTEL_CA_SECRET" \
    --namespace "$NAMESPACE" \
    --output "go-template={{ index .data \"$OTEL_CA_KEY\" }}")"
  if [[ -z "$value" || "$value" == "<no value>" ]]; then
    missing+=("$OTEL_CA_SECRET/$OTEL_CA_KEY")
  fi
fi

if (( ${#missing[@]} > 0 )); then
  echo "NEEDS_FIXES: missing required Kubernetes secret keys:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

if (( ${#forbidden[@]} > 0 )); then
  echo "NEEDS_FIXES: forbidden regulated Kubernetes secret keys are present:" >&2
  printf '  - %s\n' "${forbidden[@]}" >&2
  exit 1
fi

if [[ "$AUTH_MODE" == "saml" || "$AUTH_MODE" == "hybrid" ]]; then
  settings_b64="$(kubectl get secret "$SAML_SECRET" \
    --namespace "$NAMESPACE" \
    --output 'go-template={{ index .data "settings.json" }}')"
  advanced_b64="$(kubectl get secret "$SAML_SECRET" \
    --namespace "$NAMESPACE" \
    --output 'go-template={{ index .data "advanced_settings.json" }}')"

  if ! printf '%s' "$settings_b64" | base64 --decode | jq -e '
    def nonempty: type == "string" and length > 0;
    def https_url: type == "string" and test("^https://[^/[:space:]]+");
    def certificate:
      type == "string" and (gsub("[[:space:]]"; "") | length) >= 256;
    .strict == true
    and .debug != true
    and (.sp.entityId | https_url)
    and (.sp.assertionConsumerService.url | https_url)
    and (.sp.singleLogoutService.url | https_url)
    and (.idp.entityId | nonempty)
    and (.idp.singleSignOnService.url | https_url)
    and (
      (.idp.x509cert // "" | certificate)
      or ((.idp.x509certMulti.signing? // []) | map(select(certificate)) | length > 0)
    )
    and (
      [.sp.entityId, .sp.assertionConsumerService.url, .sp.singleLogoutService.url]
      | map(capture("^https://(?<authority>[^/]+)").authority)
      | unique
      | length == 1
    )
  ' >/dev/null; then
    echo "NEEDS_FIXES: SAML settings must use strict mode, one HTTPS SP origin, HTTPS IdP SSO, and a real IdP signing certificate" >&2
    exit 1
  fi

  if ! printf '%s' "$advanced_b64" | base64 --decode | jq -e '
    ((keys - ["contactPerson", "organization", "security"]) | length) == 0
    and .security.wantMessagesSigned == true
    and .security.wantAssertionsSigned == true
    and (.security.wantNameId // true) == true
    and (.security.allowSingleLabelDomains // false) == false
    and (.security.allowRepeatAttributeName // false) == false
    and .security.rejectDeprecatedAlgorithm == true
    and .security.signatureAlgorithm == "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
    and .security.digestAlgorithm == "http://www.w3.org/2001/04/xmlenc#sha256"
  ' >/dev/null; then
    echo "NEEDS_FIXES: SAML advanced settings must require signed messages/assertions and SHA-256 algorithms" >&2
    exit 1
  fi

  unset settings_b64 advanced_b64
fi

echo "PASS: required Kubernetes secret keys are present in namespace $NAMESPACE"
