#!/usr/bin/env bash
set -euo pipefail

export AWS_PAGER=""

required=(
  AWS_REGION
  EXPECTED_AWS_ACCOUNT_ID
  AWS_COMMERCIAL_BOUNDARY
  AWS_CACHE_REPLICATION_GROUP_ID
  AWS_CACHE_AUTH_TOKEN_SECRET_ARN
)

for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "missing required environment variable: ${name}" >&2
    exit 2
  fi
done

for command_name in aws node; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: ${command_name}" >&2
    exit 2
  fi
done

if [[ "$AWS_COMMERCIAL_BOUNDARY" != "proofshape-commercial" ]]; then
  echo "refusing cache mutation outside the proofshape-commercial boundary" >&2
  exit 2
fi

if [[ ! "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "EXPECTED_AWS_ACCOUNT_ID must contain exactly 12 digits" >&2
  exit 2
fi

actual_account_id="$(aws sts get-caller-identity --query Account --output text)"
if [[ "$actual_account_id" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
  echo "AWS account mismatch; refusing cache mutation" >&2
  exit 1
fi

emit_modify_payload() {
  local strategy="$1"

  aws secretsmanager get-secret-value \
    --region "$AWS_REGION" \
    --secret-id "$AWS_CACHE_AUTH_TOKEN_SECRET_ARN" \
    --output json |
    AWS_CACHE_AUTH_TOKEN_JSON_KEY="${AWS_CACHE_AUTH_TOKEN_JSON_KEY:-token}" \
    AWS_CACHE_REPLICATION_GROUP_ID="$AWS_CACHE_REPLICATION_GROUP_ID" \
    AWS_CACHE_AUTH_UPDATE_STRATEGY="$strategy" \
    node -e '
      let input = "";
      process.stdin.setEncoding("utf8");
      process.stdin.on("data", chunk => { input += chunk; });
      process.stdin.on("end", () => {
        const response = JSON.parse(input);
        if (typeof response.SecretString !== "string") {
          throw new Error("cache AUTH secret must use SecretString");
        }

        let token = response.SecretString.trim();
        if (token.startsWith("{")) {
          const document = JSON.parse(token);
          token = document[process.env.AWS_CACHE_AUTH_TOKEN_JSON_KEY];
        }

        if (typeof token !== "string" || !/^[A-Za-z0-9!&#$^<>-]{16,128}$/.test(token)) {
          throw new Error("cache AUTH token does not meet ElastiCache length/character constraints");
        }

        process.stdout.write(JSON.stringify({
          ReplicationGroupId: process.env.AWS_CACHE_REPLICATION_GROUP_ID,
          AuthToken: token,
          AuthTokenUpdateStrategy: process.env.AWS_CACHE_AUTH_UPDATE_STRATEGY,
          ApplyImmediately: true
        }));
      });
    '
}

apply_auth_strategy() {
  local strategy="$1"

  emit_modify_payload "$strategy" |
    aws elasticache modify-replication-group \
      --region "$AWS_REGION" \
      --cli-input-json file:///dev/stdin \
      >/dev/null

  aws elasticache wait replication-group-available \
    --region "$AWS_REGION" \
    --replication-group-id "$AWS_CACHE_REPLICATION_GROUP_ID"
}

# ROTATE safely adds the supplied token. SET then removes unauthenticated and
# prior-token access, making client authentication mandatory.
apply_auth_strategy ROTATE
apply_auth_strategy SET

member_cluster_id="$(
  aws elasticache describe-replication-groups \
    --region "$AWS_REGION" \
    --replication-group-id "$AWS_CACHE_REPLICATION_GROUP_ID" \
    --query 'ReplicationGroups[0].MemberClusters[0]' \
    --output text
)"

read -r auth_enabled transit_enabled < <(
  aws elasticache describe-cache-clusters \
    --region "$AWS_REGION" \
    --cache-cluster-id "$member_cluster_id" \
    --query 'CacheClusters[0].[AuthTokenEnabled,TransitEncryptionEnabled]' \
    --output text
)

if [[ "$auth_enabled" != "True" || "$transit_enabled" != "True" ]]; then
  echo "ElastiCache did not report both AUTH and in-transit encryption enabled" >&2
  exit 1
fi

echo "ElastiCache AUTH is required and TLS is enabled for ${AWS_CACHE_REPLICATION_GROUP_ID}."
echo "After updating REDIS_URL with the same token, set cache_authentication_confirmed=true before enabling services."
