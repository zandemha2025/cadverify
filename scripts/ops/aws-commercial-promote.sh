#!/usr/bin/env bash
set -Eeuo pipefail

export AWS_PAGER=""
PROMOTION_MODE=${PROMOTION_MODE:-promote}
case "$PROMOTION_MODE" in
  migrate-only | promote) ;;
  *) echo "PROMOTION_MODE must be migrate-only or promote" >&2; exit 2 ;;
esac

required=(
  TARGET_ENVIRONMENT
  AWS_REGION
  EXPECTED_AWS_ACCOUNT_ID
  AWS_COMMERCIAL_BOUNDARY
  AWS_ECS_CLUSTER
  AWS_ECS_MIGRATION_BASE_TASK_DEFINITION
  AWS_ECS_PUBLIC_SUBNET_IDS
  AWS_ECS_MIGRATION_SECURITY_GROUP
  AWS_ECS_PLATFORM_VERSION
  AWS_ECR_BACKEND_REPOSITORY
  AWS_ECR_FRONTEND_REPOSITORY
  AWS_RUNTIME_SECRET_ARNS
  CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_SHA256
  RELEASE_SHA
  BACKEND_DIGEST
  FRONTEND_DIGEST
)
if [[ "$PROMOTION_MODE" == promote ]]; then
  [[ "$AWS_ECS_API_SERVICE" == "${AWS_ECS_CLUSTER}-api" &&
     "$AWS_ECS_FRONTEND_SERVICE" == "${AWS_ECS_CLUSTER}-frontend" &&
     "$AWS_ECS_WORKER_SERVICE" == "${AWS_ECS_CLUSTER}-worker" ]] || {
    echo "ECS service names must belong to the exact configured cluster boundary" >&2
    exit 2
  }
  required+=(
    AWS_ECS_API_BASE_TASK_DEFINITION
    AWS_ECS_FRONTEND_BASE_TASK_DEFINITION
    AWS_ECS_WORKER_BASE_TASK_DEFINITION
    AWS_ECS_API_SERVICE
    AWS_ECS_FRONTEND_SERVICE
    AWS_ECS_WORKER_SERVICE
    AWS_PUBLIC_API_ORIGIN
    AWS_DASHBOARD_ORIGIN
    AWS_DIRECT_UPLOAD_ORIGIN
    CADVERIFY_DEEP_HEALTH_TOKEN
  )
fi

for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || {
    echo "$name is required" >&2
    exit 2
  }
done

for command_name in aws jq node; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "$command_name is required" >&2
    exit 2
  }
done

case "$TARGET_ENVIRONMENT" in
  aws-commercial-staging | aws-commercial-production) ;;
  *) echo "TARGET_ENVIRONMENT is outside the ProofShape AWS commercial boundary" >&2; exit 2 ;;
esac
[[ "$AWS_COMMERCIAL_BOUNDARY" == proofshape-commercial ]] || {
  echo "AWS_COMMERCIAL_BOUNDARY must equal proofshape-commercial" >&2
  exit 2
}
[[ "$TARGET_ENVIRONMENT" != *arcus* && "$AWS_ECS_CLUSTER" != *arcus* ]] || {
  echo "Arcus resources are outside this deployment boundary" >&2
  exit 2
}
[[ "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || {
  echo "EXPECTED_AWS_ACCOUNT_ID must contain 12 digits" >&2
  exit 2
}
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "RELEASE_SHA must be a lowercase 40-character Git commit SHA" >&2
  exit 2
}
[[ "$CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  echo "supplier holdout evidence must be an exact validated SHA-256 digest" >&2
  exit 2
}
[[ "$AWS_ECS_PLATFORM_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "AWS_ECS_PLATFORM_VERSION must be an explicit numeric version, never LATEST" >&2
  exit 2
}
for digest in "$BACKEND_DIGEST" "$FRONTEND_DIGEST"; do
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "image digests must be lowercase sha256 values" >&2
    exit 2
  }
done
if [[ "$PROMOTION_MODE" == promote ]]; then
  [[ "$AWS_PUBLIC_API_ORIGIN" == "$AWS_DASHBOARD_ORIGIN" ]] || {
    echo "AWS API and dashboard origins must be the same canonical CloudFront origin" >&2
    exit 2
  }
  [[ "$AWS_PUBLIC_API_ORIGIN" =~ ^https://[A-Za-z0-9.-]+$ ]] || {
    echo "AWS_PUBLIC_API_ORIGIN must be a canonical HTTPS origin" >&2
    exit 2
  }
  [[ "$AWS_DIRECT_UPLOAD_ORIGIN" =~ ^https://[A-Za-z0-9.-]+$ && "$AWS_DIRECT_UPLOAD_ORIGIN" != "$AWS_PUBLIC_API_ORIGIN" ]] || {
    echo "AWS_DIRECT_UPLOAD_ORIGIN must be a distinct canonical HTTPS origin" >&2
    exit 2
  }
fi

account_id=$(aws sts get-caller-identity --query Account --output text)
[[ "$account_id" == "$EXPECTED_AWS_ACCOUNT_ID" ]] || {
  echo "OIDC role resolved to the wrong AWS account" >&2
  exit 1
}

cluster_json=$(aws ecs describe-clusters --clusters "$AWS_ECS_CLUSTER" --output json)
cluster_arn=$(jq -r '.clusters[0].clusterArn // empty' <<<"$cluster_json")
cluster_status=$(jq -r '.clusters[0].status // empty' <<<"$cluster_json")
[[ "$cluster_status" == ACTIVE ]] || {
  echo "ECS cluster is missing or not ACTIVE" >&2
  exit 1
}
[[ "$cluster_arn" == "arn:aws:ecs:${AWS_REGION}:${account_id}:cluster/${AWS_ECS_CLUSTER}" ]] || {
  echo "ECS cluster is outside the expected commercial account/region" >&2
  exit 1
}

hash_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

boundary_fingerprint=$(printf '%s' "$account_id|$cluster_arn" | hash_stdin)
if [[ -n "${FORBIDDEN_BOUNDARY_FINGERPRINT:-}" && "$boundary_fingerprint" == "$FORBIDDEN_BOUNDARY_FINGERPRINT" ]]; then
  echo "production resolved to the same account/cluster boundary as staging" >&2
  exit 1
fi
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "boundary_fingerprint=$boundary_fingerprint" >>"$GITHUB_OUTPUT"
fi

repo_uri() {
  aws ecr describe-repositories \
    --repository-names "$1" \
    --query 'repositories[0].repositoryUri' \
    --output text
}

backend_repository_uri=$(repo_uri "$AWS_ECR_BACKEND_REPOSITORY")
frontend_repository_uri=$(repo_uri "$AWS_ECR_FRONTEND_REPOSITORY")
expected_registry_prefix="${account_id}.dkr.ecr.${AWS_REGION}.amazonaws.com/"
[[ "$backend_repository_uri" == "$expected_registry_prefix$AWS_ECR_BACKEND_REPOSITORY" ]] || {
  echo "backend ECR repository is outside the expected account/region" >&2
  exit 1
}
[[ "$frontend_repository_uri" == "$expected_registry_prefix$AWS_ECR_FRONTEND_REPOSITORY" ]] || {
  echo "frontend ECR repository is outside the expected account/region" >&2
  exit 1
}

aws ecr describe-images \
  --repository-name "$AWS_ECR_BACKEND_REPOSITORY" \
  --image-ids "imageDigest=$BACKEND_DIGEST" \
  --query 'imageDetails[0].imageDigest' \
  --output text | grep -Fx "$BACKEND_DIGEST" >/dev/null
aws ecr describe-images \
  --repository-name "$AWS_ECR_FRONTEND_REPOSITORY" \
  --image-ids "imageDigest=$FRONTEND_DIGEST" \
  --query 'imageDetails[0].imageDigest' \
  --output text | grep -Fx "$FRONTEND_DIGEST" >/dev/null

backend_image="${backend_repository_uri}@${BACKEND_DIGEST}"
frontend_image="${frontend_repository_uri}@${FRONTEND_DIGEST}"

IFS=',' read -r -a runtime_secret_arns <<<"$AWS_RUNTIME_SECRET_ARNS"
(( ${#runtime_secret_arns[@]} == 16 )) || {
  echo "AWS_RUNTIME_SECRET_ARNS does not contain the complete runtime contract" >&2
  exit 1
}
for secret_arn in "${runtime_secret_arns[@]}"; do
  [[ "$secret_arn" == arn:aws:secretsmanager:${AWS_REGION}:${account_id}:secret:* ]] || {
    echo "a runtime secret ARN is outside the expected account/region" >&2
    exit 1
  }
  current_version=$(aws secretsmanager list-secret-version-ids \
    --secret-id "$secret_arn" \
    --query "Versions[?contains(VersionStages, 'AWSCURRENT')].VersionId | [0]" \
    --output text)
  [[ -n "$current_version" && "$current_version" != None ]] || {
    echo "a required runtime secret has no AWSCURRENT version: $secret_arn" >&2
    exit 1
  }
done

work_dir=$(mktemp -d)
cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT

validate_base_task_definition() {
  local task_definition=$1
  local expected_family=$2
  local container_name=$3
  local output_name=$4
  local expected_secret_names
  case "$container_name" in
    api | worker)
      expected_secret_names="API_KEY_PEPPER,AUTH_PROXY_SECRET,CONNECTOR_FINGERPRINT_KEY,CONNECTOR_SECRET_KEY,DASHBOARD_SESSION_SECRET,DATABASE_URL,DATABASE_URL_DIRECT,DEEP_HEALTH_TOKEN,MAGIC_LINK_SECRET,REDIS_URL,RESEND_API_KEY,RESEND_FROM,SENTRY_DSN,SESSION_SECRET,TURNSTILE_SECRET"
      ;;
    frontend) expected_secret_names="AUTH_PROXY_SECRET,TURNSTILE_SITE_KEY" ;;
    migration) expected_secret_names="DATABASE_URL" ;;
    *) echo "unknown baseline container: $container_name" >&2; exit 1 ;;
  esac
  local expected_arn_prefix="arn:aws:ecs:${AWS_REGION}:${account_id}:task-definition/${expected_family}:"
  local expected_execution_role="arn:aws:iam::${account_id}:role/${expected_family}-execution"
  local expected_task_role="arn:aws:iam::${account_id}:role/${expected_family}-task"
  local described="$work_dir/${output_name}-base.json"

  [[ "$task_definition" == "$expected_arn_prefix"* ]] || {
    echo "$output_name baseline task definition is outside the expected family/account/region" >&2
    exit 1
  }
  aws ecs describe-task-definition \
    --task-definition "$task_definition" \
    --query taskDefinition \
    --output json >"$described"

  jq -e \
    --arg family "$expected_family" \
    --arg container "$container_name" \
    --arg expected_execution_role "$expected_execution_role" \
    --arg expected_task_role "$expected_task_role" \
    --arg expected_secret_names "$expected_secret_names" \
    --arg runtime_secret_arns "$AWS_RUNTIME_SECRET_ARNS" '
      .family == $family
      and .status == "ACTIVE"
      and .networkMode == "awsvpc"
      and (.requiresCompatibilities | index("FARGATE") != null)
      and .executionRoleArn == $expected_execution_role
      and .taskRoleArn == $expected_task_role
      and ([.containerDefinitions[] | select(.name == $container)] | length == 1)
      and ([.containerDefinitions[] | select(.name == $container)][0].readonlyRootFilesystem == true)
      and ([.containerDefinitions[] | select(.name == $container)][0].linuxParameters.initProcessEnabled == true)
      and (([.containerDefinitions[] | select(.name == $container)][0].secrets // [] | map(.name) | sort)
        == ($expected_secret_names | split(",") | sort))
      and ([.containerDefinitions[] | select(.name == $container)][0].secrets // []
        | all(.valueFrom as $arn | ($runtime_secret_arns | split(",") | index($arn)) != null))
      and ([.containerDefinitions[] | select(.name == $container)][0].environment // []
        | map(.name)
        | all(. != "AWS_ACCESS_KEY_ID" and . != "AWS_SECRET_ACCESS_KEY" and . != "AWS_SESSION_TOKEN"))
    ' "$described" >/dev/null || {
      echo "$output_name baseline task definition failed the reviewed Fargate security contract" >&2
      exit 1
    }

  if [[ "$container_name" == api || "$container_name" == worker ]]; then
    jq -e --arg container "$container_name" '
      ([.containerDefinitions[] | select(.name == $container)][0].environment
        | map({key:.name, value:.value}) | from_entries) as $env
      | ($env.OBJECT_STORE_BACKEND == "s3")
        and ($env.DIRECT_UPLOAD_S3_BUCKET | length > 0)
        and ($env.OBJECT_STORE_S3_BUCKET | length > 0)
        and ($env.DIRECT_UPLOAD_S3_BUCKET != $env.OBJECT_STORE_S3_BUCKET)
        and ($env.DIRECT_UPLOAD_S3_PREFIX | length > 0)
        and ($env.DIRECT_UPLOAD_S3_REGION | length > 0)
        and ($env.DIRECT_UPLOAD_S3_KMS_KEY_ID | startswith("arn:aws:kms:"))
    ' "$described" >/dev/null || {
      echo "$output_name baseline does not isolate transient uploads from durable evidence" >&2
      exit 1
    }
  fi

  if [[ "$container_name" == frontend ]]; then
    jq -e --arg direct_origin "$AWS_DIRECT_UPLOAD_ORIGIN" '
      ([.containerDefinitions[] | select(.name == "frontend")][0].environment
        | map({key:.name, value:.value}) | from_entries) as $env
      | $env.DIRECT_UPLOAD_ORIGIN == $direct_origin
        and $env.PRODUCTION_DIRECT_UPLOAD_REQUIRED == "1"
    ' "$described" >/dev/null || {
      echo "frontend baseline does not enforce the exact direct-upload CSP origin" >&2
      exit 1
    }
  fi

  printf '%s' "$described"
}

register_revision() {
  local source_json=$1
  local container_name=$2
  local image=$3
  local output_name=$4
  local accepting_state=${5:-}
  local request="$work_dir/${output_name}-register.json"

  jq --arg container "$container_name" \
    --arg image "$image" \
    --arg release "$RELEASE_SHA" \
    --arg accepting_state "$accepting_state" '
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
        if .name == $container then
          .image = $image
          | .environment = (
              ((.environment // []) | map(select(.name != "RELEASE" and .name != "PROOFSHAPE_BUILD_ID")))
              + [
                  {"name":"PROOFSHAPE_BUILD_ID", "value":$release},
                  {"name":"RELEASE", "value":$release}
                ]
            )
          | if $accepting_state != "" then
              .environment = (
                (.environment | map(select(.name != "ACCEPTING_NEW_ANALYSES")))
                + [{"name":"ACCEPTING_NEW_ANALYSES", "value":$accepting_state}]
              )
            else . end
        else . end
      )
  ' "$source_json" >"$request"

  aws ecs register-task-definition \
    --cli-input-json "file://$request" \
    --query taskDefinition.taskDefinitionArn \
    --output text
}

migration_family="${AWS_ECS_CLUSTER}-migration"
migration_base_json=$(validate_base_task_definition \
  "$AWS_ECS_MIGRATION_BASE_TASK_DEFINITION" \
  "$migration_family" \
  migration \
  migration)
new_migration=$(register_revision "$migration_base_json" migration "$backend_image" migration)

subnets_json=$(jq -cen --arg csv "$AWS_ECS_PUBLIC_SUBNET_IDS" '
  $csv | split(",") | map(select(test("^subnet-[0-9a-f]+$"))) | unique
')
[[ $(jq 'length' <<<"$subnets_json") -eq 2 ]] || {
  echo "AWS_ECS_PUBLIC_SUBNET_IDS must contain exactly two distinct valid subnet IDs" >&2
  exit 1
}
[[ "$AWS_ECS_MIGRATION_SECURITY_GROUP" =~ ^sg-[0-9a-f]+$ ]] || {
  echo "AWS_ECS_MIGRATION_SECURITY_GROUP must be a security-group ID" >&2
  exit 1
}
migration_subnet_one=$(jq -r '.[0]' <<<"$subnets_json")
migration_subnet_two=$(jq -r '.[1]' <<<"$subnets_json")
subnet_description=$(aws ec2 describe-subnets \
  --subnet-ids "$migration_subnet_one" "$migration_subnet_two" \
  --output json)
jq -e '
  (.Subnets | length == 2)
  and ([.Subnets[].SubnetId] | unique | length == 2)
  and ([.Subnets[].VpcId] | unique | length == 1)
  and ([.Subnets[].AvailabilityZoneId] | unique | length == 2)
  and all(.Subnets[]; .State == "available" and .AvailableIpAddressCount > 0)
' <<<"$subnet_description" >/dev/null || {
  echo "migration subnets must be available, nonempty, same-VPC, and span two physical AZs" >&2
  exit 1
}
migration_vpc_id=$(jq -r '.Subnets[0].VpcId' <<<"$subnet_description")
security_group_vpc_id=$(aws ec2 describe-security-groups \
  --group-ids "$AWS_ECS_MIGRATION_SECURITY_GROUP" \
  --query 'SecurityGroups[0].VpcId' \
  --output text)
[[ "$security_group_vpc_id" == "$migration_vpc_id" ]] || {
  echo "migration security group is not in the migration subnet VPC" >&2
  exit 1
}
network_configuration=$(jq -cen \
  --argjson subnets "$subnets_json" \
  --arg security_group "$AWS_ECS_MIGRATION_SECURITY_GROUP" \
  '{awsvpcConfiguration:{subnets:$subnets,securityGroups:[$security_group],assignPublicIp:"ENABLED"}}')
migration_overrides='{"containerOverrides":[{"name":"migration","command":["alembic","upgrade","head"]}]}'

migration_run=$(aws ecs run-task \
  --cluster "$AWS_ECS_CLUSTER" \
  --task-definition "$new_migration" \
  --launch-type FARGATE \
  --platform-version "$AWS_ECS_PLATFORM_VERSION" \
  --count 1 \
  --network-configuration "$network_configuration" \
  --overrides "$migration_overrides" \
  --started-by "proofshape-${GITHUB_RUN_ID:-manual}" \
  --output json)
jq -e '.failures | length == 0' <<<"$migration_run" >/dev/null || {
  jq -r '.failures[] | "ECS migration placement failure: \(.arn // "unknown") \(.reason // "unknown") \(.detail // "")"' <<<"$migration_run" >&2
  exit 1
}
migration_task=$(jq -r '.tasks[0].taskArn // empty' <<<"$migration_run")
[[ "$migration_task" == "arn:aws:ecs:${AWS_REGION}:${account_id}:task/${AWS_ECS_CLUSTER}/"* ||
   "$migration_task" == "arn:aws:ecs:${AWS_REGION}:${account_id}:task/"* ]] || {
  echo "ECS did not start the migration task in the expected cluster" >&2
  exit 1
}

aws ecs wait tasks-stopped --cluster "$AWS_ECS_CLUSTER" --tasks "$migration_task"
# The backticks below are JMESPath literals, not shell substitutions.
# shellcheck disable=SC2016
migration_result=$(aws ecs describe-tasks \
  --cluster "$AWS_ECS_CLUSTER" \
  --tasks "$migration_task" \
  --query 'tasks[0].[taskDefinitionArn,containers[?name==`migration`]|[0].exitCode,stopCode,stoppedReason]' \
  --output text)
read -r migration_task_definition migration_exit migration_stop_code migration_reason <<<"$migration_result"
[[ "$migration_task_definition" == "$new_migration" ]] || {
  echo "migration ran an unexpected task definition" >&2
  exit 1
}
[[ "$migration_exit" == 0 ]] || {
  echo "Alembic migration failed (exit=$migration_exit stop=$migration_stop_code reason=$migration_reason)" >&2
  exit 1
}

evidence_path=${AWS_PROMOTION_EVIDENCE_PATH:-"$work_dir/aws-promotion-evidence.json"}
mkdir -p "$(dirname "$evidence_path")"

if [[ "$PROMOTION_MODE" == migrate-only ]]; then
  jq -n \
    --arg status PASS \
    --arg mode "$PROMOTION_MODE" \
    --arg environment "$TARGET_ENVIRONMENT" \
    --arg account_id "$account_id" \
    --arg cluster_arn "$cluster_arn" \
    --arg boundary_fingerprint "$boundary_fingerprint" \
    --arg release_sha "$RELEASE_SHA" \
    --arg backend_image "$backend_image" \
    --arg frontend_image "$frontend_image" \
    --arg holdout_sha256 "$CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_SHA256" \
    --arg migration_task_definition "$new_migration" \
    --arg migration_task "$migration_task" \
    '{
      schema: 1,
      status: $status,
      mode: $mode,
      environment: $environment,
      accountId: $account_id,
      clusterArn: $cluster_arn,
      boundaryFingerprint: $boundary_fingerprint,
      releaseSha: $release_sha,
      images: {backend:$backend_image, frontend:$frontend_image},
      supplierHoldoutEvidenceSha256: $holdout_sha256,
      migration: {taskDefinition:$migration_task_definition, task:$migration_task, exitCode:0},
      servicesChanged: false
    }' >"$evidence_path"
  echo "ProofShape AWS migration-only gate passed: $TARGET_ENVIRONMENT $RELEASE_SHA"
  echo "Evidence: $evidence_path"
  exit 0
fi

service_task_definition() {
  local service=$1
  local result
  result=$(aws ecs describe-services \
    --cluster "$AWS_ECS_CLUSTER" \
    --services "$service" \
    --query 'services[0].[status,desiredCount,taskDefinition]' \
    --output text)
  local status desired task_definition
  read -r status desired task_definition <<<"$result"
  [[ "$status" == ACTIVE && "$desired" =~ ^[1-9][0-9]*$ && -n "$task_definition" ]] || {
    echo "ECS service $service is not active with a positive desired count" >&2
    exit 1
  }
  printf '%s' "$task_definition"
}

previous_api=$(service_task_definition "$AWS_ECS_API_SERVICE")
previous_frontend=$(service_task_definition "$AWS_ECS_FRONTEND_SERVICE")
previous_worker=$(service_task_definition "$AWS_ECS_WORKER_SERVICE")
current_api_accepting=$(aws ecs describe-task-definition \
  --task-definition "$previous_api" \
  --query taskDefinition \
  --output json | jq -r '
    [.containerDefinitions[] | select(.name == "api")][0].environment // []
    | map(select(.name == "ACCEPTING_NEW_ANALYSES"))
    | if length == 0 then "true" elif length == 1 then .[0].value else "duplicate" end
  ')
[[ "$current_api_accepting" == true || "$current_api_accepting" == false ]] || {
  echo "current API task definition has an ambiguous ACCEPTING_NEW_ANALYSES value" >&2
  exit 1
}

api_base_json=$(validate_base_task_definition \
  "$AWS_ECS_API_BASE_TASK_DEFINITION" "$AWS_ECS_API_SERVICE" api api)
frontend_base_json=$(validate_base_task_definition \
  "$AWS_ECS_FRONTEND_BASE_TASK_DEFINITION" "$AWS_ECS_FRONTEND_SERVICE" frontend frontend)
worker_base_json=$(validate_base_task_definition \
  "$AWS_ECS_WORKER_BASE_TASK_DEFINITION" "$AWS_ECS_WORKER_SERVICE" worker worker)

new_api=$(register_revision "$api_base_json" api "$backend_image" api "$current_api_accepting")
new_frontend=$(register_revision "$frontend_base_json" frontend "$frontend_image" frontend)
new_worker=$(register_revision "$worker_base_json" worker "$backend_image" worker)

declare -a updated_services=()
declare -A previous_by_service=(
  ["$AWS_ECS_API_SERVICE"]="$previous_api"
  ["$AWS_ECS_WORKER_SERVICE"]="$previous_worker"
  ["$AWS_ECS_FRONTEND_SERVICE"]="$previous_frontend"
)

rollback() {
  local rc=$?
  trap - ERR
  set +e
  if (( ${#updated_services[@]} > 0 )); then
    echo "promotion failed; restoring previous ECS service task definitions" >&2
    for service in "${updated_services[@]}"; do
      aws ecs update-service \
        --cluster "$AWS_ECS_CLUSTER" \
        --service "$service" \
        --task-definition "${previous_by_service[$service]}" \
        --force-new-deployment >/dev/null
    done
    aws ecs wait services-stable \
      --cluster "$AWS_ECS_CLUSTER" \
      --services "${updated_services[@]}"
  fi
  exit "$rc"
}
trap rollback ERR

update_service() {
  local service=$1
  local task_definition=$2
  aws ecs update-service \
    --cluster "$AWS_ECS_CLUSTER" \
    --service "$service" \
    --task-definition "$task_definition" \
    --force-new-deployment >/dev/null
  updated_services+=("$service")
}

update_service "$AWS_ECS_API_SERVICE" "$new_api"
update_service "$AWS_ECS_WORKER_SERVICE" "$new_worker"
update_service "$AWS_ECS_FRONTEND_SERVICE" "$new_frontend"

aws ecs wait services-stable \
  --cluster "$AWS_ECS_CLUSTER" \
  --services "$AWS_ECS_API_SERVICE" "$AWS_ECS_WORKER_SERVICE" "$AWS_ECS_FRONTEND_SERVICE"

verify_service_revision() {
  local service=$1
  local expected=$2
  local actual
  actual=$(aws ecs describe-services \
    --cluster "$AWS_ECS_CLUSTER" \
    --services "$service" \
    --query 'services[0].taskDefinition' \
    --output text)
  [[ "$actual" == "$expected" ]] || {
    echo "$service stabilized on an unexpected task definition" >&2
    return 1
  }
}

verify_service_revision "$AWS_ECS_API_SERVICE" "$new_api"
verify_service_revision "$AWS_ECS_WORKER_SERVICE" "$new_worker"
verify_service_revision "$AWS_ECS_FRONTEND_SERVICE" "$new_frontend"

AWS_PROMOTION_EVIDENCE_PATH="$evidence_path" \
AWS_DIRECT_UPLOAD_ORIGIN="$AWS_DIRECT_UPLOAD_ORIGIN" \
  node scripts/ops/aws-deep-health.mjs

jq -n \
  --arg status PASS \
  --arg mode "$PROMOTION_MODE" \
  --arg environment "$TARGET_ENVIRONMENT" \
  --arg account_id "$account_id" \
  --arg cluster_arn "$cluster_arn" \
  --arg boundary_fingerprint "$boundary_fingerprint" \
  --arg release_sha "$RELEASE_SHA" \
  --arg backend_image "$backend_image" \
  --arg frontend_image "$frontend_image" \
  --arg holdout_sha256 "$CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_SHA256" \
  --arg migration_task_definition "$new_migration" \
  --arg migration_task "$migration_task" \
  --arg api_task_definition "$new_api" \
  --arg worker_task_definition "$new_worker" \
  --arg frontend_task_definition "$new_frontend" \
  --arg canonical_origin "$AWS_PUBLIC_API_ORIGIN" \
  --arg direct_upload_origin "$AWS_DIRECT_UPLOAD_ORIGIN" \
  --arg intake_accepting "$current_api_accepting" \
  --slurpfile health "$evidence_path" \
  '{
    schema: 1,
    status: $status,
    mode: $mode,
    environment: $environment,
    accountId: $account_id,
    clusterArn: $cluster_arn,
    boundaryFingerprint: $boundary_fingerprint,
    releaseSha: $release_sha,
    images: {backend:$backend_image, frontend:$frontend_image},
    supplierHoldoutEvidenceSha256: $holdout_sha256,
    migration: {taskDefinition:$migration_task_definition, task:$migration_task, exitCode:0},
    services: {api:$api_task_definition, worker:$worker_task_definition, frontend:$frontend_task_definition},
    intakeAccepting: ($intake_accepting == "true"),
    canonicalOrigin: $canonical_origin,
    directUploadOrigin: $direct_upload_origin,
    health: $health[0]
  }' >"${evidence_path}.tmp"
mv "${evidence_path}.tmp" "$evidence_path"

trap - ERR
echo "ProofShape AWS promotion passed: $TARGET_ENVIRONMENT $RELEASE_SHA"
echo "Evidence: $evidence_path"
