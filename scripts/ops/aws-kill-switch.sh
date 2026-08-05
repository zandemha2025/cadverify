#!/usr/bin/env bash
set -Eeuo pipefail

action=${1:-${AWS_KILL_SWITCH_ACTION:-}}
case "$action" in
  off | on | test) ;;
  *) echo "usage: aws-kill-switch.sh {off|on|test}" >&2; exit 2 ;;
esac

required=(
  TARGET_ENVIRONMENT
  AWS_REGION
  EXPECTED_AWS_ACCOUNT_ID
  AWS_COMMERCIAL_BOUNDARY
  AWS_ECS_CLUSTER
  AWS_ECS_API_SERVICE
  AWS_PUBLIC_API_ORIGIN
  EXPECTED_RELEASE_SHA
)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || {
    echo "missing required environment variable: $name" >&2
    exit 2
  }
done

for command_name in aws curl jq; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "required command not found: $command_name" >&2
    exit 2
  }
done

case "$TARGET_ENVIRONMENT" in
  aws-commercial-staging | aws-commercial-production) ;;
  *) echo "target is outside the ProofShape AWS commercial boundary" >&2; exit 2 ;;
esac
[[ "$AWS_COMMERCIAL_BOUNDARY" == proofshape-commercial ]] || {
  echo "AWS_COMMERCIAL_BOUNDARY must equal proofshape-commercial" >&2
  exit 2
}
[[ "$TARGET_ENVIRONMENT" != *arcus* && "$AWS_ECS_CLUSTER" != *arcus* && "$AWS_ECS_API_SERVICE" != *arcus* ]] || {
  echo "Arcus resources are outside this operational boundary" >&2
  exit 2
}
[[ "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || {
  echo "EXPECTED_AWS_ACCOUNT_ID must contain exactly 12 digits" >&2
  exit 2
}
[[ "$EXPECTED_RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "EXPECTED_RELEASE_SHA must be the exact lowercase 40-character live release SHA" >&2
  exit 2
}
[[ "$AWS_PUBLIC_API_ORIGIN" =~ ^https://[A-Za-z0-9.-]+$ ]] || {
  echo "AWS_PUBLIC_API_ORIGIN must be a canonical HTTPS origin without a path" >&2
  exit 2
}
if [[ "$action" == test && "$TARGET_ENVIRONMENT" != aws-commercial-staging ]]; then
  echo "the disruptive off/on kill-switch drill is restricted to staging" >&2
  exit 2
fi

account_id=$(aws sts get-caller-identity --query Account --output text)
[[ "$account_id" == "$EXPECTED_AWS_ACCOUNT_ID" ]] || {
  echo "AWS account mismatch; refusing kill-switch mutation" >&2
  exit 1
}

cluster_json=$(aws ecs describe-clusters --clusters "$AWS_ECS_CLUSTER" --output json)
cluster_arn=$(jq -r '.clusters[0].clusterArn // empty' <<<"$cluster_json")
cluster_status=$(jq -r '.clusters[0].status // empty' <<<"$cluster_json")
[[ "$cluster_status" == ACTIVE && "$cluster_arn" == "arn:aws:ecs:${AWS_REGION}:${account_id}:cluster/${AWS_ECS_CLUSTER}" ]] || {
  echo "ECS cluster is missing or outside the expected account/region" >&2
  exit 1
}

service_json=$(aws ecs describe-services \
  --cluster "$AWS_ECS_CLUSTER" \
  --services "$AWS_ECS_API_SERVICE" \
  --output json)
service_status=$(jq -r '.services[0].status // empty' <<<"$service_json")
desired_count=$(jq -r '.services[0].desiredCount // 0' <<<"$service_json")
previous_task_definition=$(jq -r '.services[0].taskDefinition // empty' <<<"$service_json")
[[ "$service_status" == ACTIVE && "$desired_count" =~ ^[1-9][0-9]*$ ]] || {
  echo "API service is not active with a positive desired count" >&2
  exit 1
}
expected_task_prefix="arn:aws:ecs:${AWS_REGION}:${account_id}:task-definition/${AWS_ECS_API_SERVICE}:"
[[ "$previous_task_definition" == "$expected_task_prefix"* ]] || {
  echo "API service task definition is outside the expected family/account/region" >&2
  exit 1
}

work_dir=$(mktemp -d)
cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT

previous_json="$work_dir/previous.json"
aws ecs describe-task-definition \
  --task-definition "$previous_task_definition" \
  --query taskDefinition \
  --output json >"$previous_json"

jq -e \
  --arg family "$AWS_ECS_API_SERVICE" \
  --arg expected_execution_role "arn:aws:iam::${account_id}:role/${AWS_ECS_API_SERVICE}-execution" \
  --arg expected_task_role "arn:aws:iam::${account_id}:role/${AWS_ECS_API_SERVICE}-task" '
    .family == $family
    and .networkMode == "awsvpc"
    and (.requiresCompatibilities | index("FARGATE") != null)
    and .executionRoleArn == $expected_execution_role
    and .taskRoleArn == $expected_task_role
    and ([.containerDefinitions[] | select(.name == "api")] | length == 1)
    and ([.containerDefinitions[] | select(.name == "api")][0].readonlyRootFilesystem == true)
    and ([.containerDefinitions[] | select(.name == "api")][0].linuxParameters.initProcessEnabled == true)
    and ([.containerDefinitions[] | select(.name == "api")][0].image | test("@sha256:[0-9a-f]{64}$"))
    and (([.containerDefinitions[] | select(.name == "api")][0].secrets // [] | map(.name) | sort)
      == ("API_KEY_PEPPER,AUTH_PROXY_SECRET,CONNECTOR_FINGERPRINT_KEY,CONNECTOR_SECRET_KEY,DASHBOARD_SESSION_SECRET,DATABASE_URL,DATABASE_URL_DIRECT,DEEP_HEALTH_TOKEN,MAGIC_LINK_SECRET,REDIS_URL,RESEND_API_KEY,RESEND_FROM,SENTRY_DSN,SESSION_SECRET,TURNSTILE_SECRET" | split(",") | sort))
    and ([.containerDefinitions[] | select(.name == "api")][0].environment // []
      | map(.name)
      | all(. != "AWS_ACCESS_KEY_ID" and . != "AWS_SECRET_ACCESS_KEY" and . != "AWS_SESSION_TOKEN"))
  ' "$previous_json" >/dev/null || {
    echo "current API task definition does not satisfy the reviewed Fargate security shape" >&2
    exit 1
  }

previous_state=$(jq -r '
  [.containerDefinitions[] | select(.name == "api")][0].environment // []
  | map(select(.name == "ACCEPTING_NEW_ANALYSES"))
  | if length == 0 then "true" elif length == 1 then .[0].value else "duplicate" end
' "$previous_json")
[[ "$previous_state" == true || "$previous_state" == false ]] || {
  echo "current API task definition has an ambiguous ACCEPTING_NEW_ANALYSES value" >&2
  exit 1
}
api_image=$(jq -r '[.containerDefinitions[] | select(.name == "api")][0].image' "$previous_json")
live_release=$(jq -r '
  [.containerDefinitions[] | select(.name == "api")][0].environment // []
  | map(select(.name == "RELEASE"))
  | if length == 1 then .[0].value else "" end
' "$previous_json")
[[ "$live_release" == "$EXPECTED_RELEASE_SHA" ]] || {
  echo "live API release does not match EXPECTED_RELEASE_SHA; refusing operational mutation" >&2
  exit 1
}

register_state() {
  local state=$1
  local request="$work_dir/register-${state}.json"
  jq --arg state "$state" '
    del(
      .compatibilities,
      .deregisteredAt,
      .registeredAt,
      .registeredBy,
      .requiresAttributes,
      .revision,
      .status,
      .taskDefinitionArn
    )
    | .containerDefinitions |= map(
        if .name == "api" then
          .environment = (
            ((.environment // []) | map(select(.name != "ACCEPTING_NEW_ANALYSES")))
            + [{"name":"ACCEPTING_NEW_ANALYSES", "value":$state}]
          )
        else . end
      )
  ' "$previous_json" >"$request"

  aws ecs register-task-definition \
    --cli-input-json "file://$request" \
    --query taskDefinition.taskDefinitionArn \
    --output text
}

deploy_revision() {
  local revision=$1
  aws ecs update-service \
    --cluster "$AWS_ECS_CLUSTER" \
    --service "$AWS_ECS_API_SERVICE" \
    --task-definition "$revision" \
    --force-new-deployment >/dev/null
  aws ecs wait services-stable \
    --cluster "$AWS_ECS_CLUSTER" \
    --services "$AWS_ECS_API_SERVICE"
  local actual
  actual=$(aws ecs describe-services \
    --cluster "$AWS_ECS_CLUSTER" \
    --services "$AWS_ECS_API_SERVICE" \
    --query 'services[0].taskDefinition' \
    --output text)
  [[ "$actual" == "$revision" ]] || {
    echo "API service stabilized on an unexpected task definition" >&2
    return 1
  }
}

probe_state() {
  local expected=$1
  local headers="$work_dir/probe-${expected}.headers"
  local body="$work_dir/probe-${expected}.json"
  local status
  status=$(curl --silent --show-error \
    --max-time 30 \
    --request POST \
    --header 'Content-Type: application/json' \
    --dump-header "$headers" \
    --output "$body" \
    --write-out '%{http_code}' \
    "${AWS_PUBLIC_API_ORIGIN}/api/v1/validate/demo")

  if [[ "$expected" == false ]]; then
    [[ "$status" == 503 ]] || {
      echo "kill switch off probe returned HTTP $status instead of 503" >&2
      return 1
    }
    jq -e '.code == "service_paused"' "$body" >/dev/null || {
      echo "kill switch off probe did not return service_paused" >&2
      return 1
    }
    grep -Eiq '^retry-after:[[:space:]]*3600\r?$' "$headers" || {
      echo "kill switch off probe did not return Retry-After: 3600" >&2
      return 1
    }
  else
    [[ "$status" == 422 ]] || {
      echo "kill switch on probe returned HTTP $status instead of the expected application 422" >&2
      return 1
    }
    if jq -e '.code == "service_paused"' "$body" >/dev/null 2>&1; then
      echo "kill switch on probe still returned service_paused" >&2
      return 1
    fi
  fi
}

rollback_required=false
rollback() {
  local rc=$?
  trap - ERR
  if [[ "$rollback_required" == true ]]; then
    set +e
    if [[ "$action" == off && -n "$off_revision" ]]; then
      echo "kill-switch off verification failed; failing closed on the off revision" >&2
      deploy_revision "$off_revision"
    else
      echo "kill-switch operation failed; restoring the original task definition" >&2
      deploy_revision "$previous_task_definition"
    fi
  fi
  exit "$rc"
}
trap rollback ERR

off_revision=""
on_revision=""
final_task_definition=""

case "$action" in
  off)
    rollback_required=true
    off_revision=$(register_state false)
    deploy_revision "$off_revision"
    probe_state false
    final_task_definition=$off_revision
    ;;
  on)
    rollback_required=true
    on_revision=$(register_state true)
    deploy_revision "$on_revision"
    probe_state true
    final_task_definition=$on_revision
    ;;
  test)
    rollback_required=true
    off_revision=$(register_state false)
    deploy_revision "$off_revision"
    probe_state false
    on_revision=$(register_state true)
    deploy_revision "$on_revision"
    probe_state true
    deploy_revision "$previous_task_definition"
    probe_state "$previous_state"
    final_task_definition=$previous_task_definition
    ;;
esac

rollback_required=false
trap - ERR

evidence_path=${AWS_KILL_SWITCH_EVIDENCE_PATH:-}
if [[ -n "$evidence_path" ]]; then
  mkdir -p "$(dirname "$evidence_path")"
  jq -n \
    --arg status PASS \
    --arg action "$action" \
    --arg environment "$TARGET_ENVIRONMENT" \
    --arg account_id "$account_id" \
    --arg cluster_arn "$cluster_arn" \
    --arg service "$AWS_ECS_API_SERVICE" \
    --arg image "$api_image" \
    --arg release_sha "$live_release" \
    --arg previous_state "$previous_state" \
    --arg previous_task_definition "$previous_task_definition" \
    --arg off_task_definition "$off_revision" \
    --arg on_task_definition "$on_revision" \
    --arg final_task_definition "$final_task_definition" \
    --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{
      schema: 1,
      status: $status,
      action: $action,
      environment: $environment,
      accountId: $account_id,
      clusterArn: $cluster_arn,
      service: $service,
      image: $image,
      releaseSha: $release_sha,
      previousState: $previous_state,
      previousTaskDefinition: $previous_task_definition,
      drillTaskDefinitions: {off: $off_task_definition, on: $on_task_definition},
      finalTaskDefinition: $final_task_definition,
      verifiedAt: $verified_at
    }' >"$evidence_path"
fi

echo "AWS-native kill switch '$action' passed for $TARGET_ENVIRONMENT; final task definition: $final_task_definition"
