#!/usr/bin/env bash
set -Eeuo pipefail

export AWS_PAGER=""

required=(
  AWS_REGION
  EXPECTED_AWS_ACCOUNT_ID
  AWS_COMMERCIAL_BOUNDARY
  AWS_ECR_BACKEND_REPOSITORY
  AWS_ECR_FRONTEND_REPOSITORY
  RELEASE_SHA
  AWS_RELEASE_IMAGE_ARCHIVE_DIR
)

for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "missing required environment variable: ${name}" >&2
    exit 2
  fi
done

for command_name in aws docker jq sha256sum; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: ${command_name}" >&2
    exit 2
  fi
done

[[ "$AWS_COMMERCIAL_BOUNDARY" == "proofshape-commercial" ]] || {
  echo "refusing image publication outside proofshape-commercial" >&2
  exit 2
}
[[ "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || {
  echo "EXPECTED_AWS_ACCOUNT_ID must contain exactly 12 digits" >&2
  exit 2
}
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "RELEASE_SHA must be a lowercase 40-character commit SHA" >&2
  exit 2
}

manifest="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/manifest.json"
backend_archive="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/backend.tar"
frontend_archive="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/frontend.tar"
backend_scan="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/backend.trivy.json"
frontend_scan="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/frontend.trivy.json"
backend_sbom="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/backend.cdx.json"
frontend_sbom="$AWS_RELEASE_IMAGE_ARCHIVE_DIR/frontend.cdx.json"

for path in \
  "$manifest" \
  "$backend_archive" \
  "$frontend_archive" \
  "$backend_scan" \
  "$frontend_scan" \
  "$backend_sbom" \
  "$frontend_sbom"; do
  [[ -f "$path" ]] || {
    echo "release image artifact is incomplete: $(basename "$path")" >&2
    exit 1
  }
done

jq -e --arg sha "$RELEASE_SHA" '
  .schema == 2
  and .releaseSha == $sha
  and .platform == "linux/amd64"
  and .images.backend.archive == "backend.tar"
  and .images.frontend.archive == "frontend.tar"
  and .images.backend.sourceTag == ("proofshape-release/backend:" + $sha)
  and .images.frontend.sourceTag == ("proofshape-release/frontend:" + $sha)
  and (.images.backend.localImageId | test("^sha256:[0-9a-f]{64}$"))
  and (.images.frontend.localImageId | test("^sha256:[0-9a-f]{64}$"))
  and .securityEvidence.scanner == "trivy"
  and .securityEvidence.policy == "HIGH,CRITICAL:fail"
  and .securityEvidence.backendScan.file == "backend.trivy.json"
  and .securityEvidence.frontendScan.file == "frontend.trivy.json"
  and .securityEvidence.backendSbom.file == "backend.cdx.json"
  and .securityEvidence.frontendSbom.file == "frontend.cdx.json"
' "$manifest" >/dev/null || {
  echo "release image manifest does not match the requested SHA/platform" >&2
  exit 1
}

verify_archive() {
  local component="$1"
  local path="$2"
  local expected actual
  expected="$(jq -r --arg component "$component" '.images[$component].sha256' "$manifest")"
  actual="$(sha256sum "$path" | awk '{print $1}')"
  [[ "$expected" =~ ^[0-9a-f]{64}$ && "$actual" == "$expected" ]] || {
    echo "${component} archive SHA-256 mismatch" >&2
    exit 1
  }
}

verify_archive backend "$backend_archive"
verify_archive frontend "$frontend_archive"

verify_scan() {
  local component="$1"
  local path="$2"
  local expected actual
  expected="$(jq -r --arg component "$component" '.securityEvidence[$component + "Scan"].sha256' "$manifest")"
  actual="$(sha256sum "$path" | awk '{print $1}')"
  [[ "$expected" =~ ^[0-9a-f]{64}$ && "$actual" == "$expected" ]] || {
    echo "${component} exact-image vulnerability report SHA-256 mismatch" >&2
    exit 1
  }
  jq -e '
    .SchemaVersion == 2
    and (.Results | type == "array")
    and ([.Results[]?.Vulnerabilities[]? | select(.Severity == "HIGH" or .Severity == "CRITICAL")] | length == 0)
  ' "$path" >/dev/null || {
    echo "${component} exact-image report is invalid or contains a HIGH/CRITICAL vulnerability" >&2
    exit 1
  }
}

verify_scan backend "$backend_scan"
verify_scan frontend "$frontend_scan"

verify_evidence() {
  local component="$1"
  local path="$2"
  local expected actual
  expected="$(jq -r --arg component "$component" '.securityEvidence[$component + "Sbom"].sha256' "$manifest")"
  actual="$(sha256sum "$path" | awk '{print $1}')"
  [[ "$expected" =~ ^[0-9a-f]{64}$ && "$actual" == "$expected" ]] || {
    echo "${component} exact-image SBOM SHA-256 mismatch" >&2
    exit 1
  }
  jq -e '.bomFormat == "CycloneDX"' "$path" >/dev/null || {
    echo "${component} exact-image SBOM is not CycloneDX JSON" >&2
    exit 1
  }
}

verify_evidence backend "$backend_sbom"
verify_evidence frontend "$frontend_sbom"

actual_account_id="$(aws sts get-caller-identity --query Account --output text)"
[[ "$actual_account_id" == "$EXPECTED_AWS_ACCOUNT_ID" ]] || {
  echo "OIDC role resolved to the wrong AWS account" >&2
  exit 1
}

repository_uri() {
  aws ecr describe-repositories \
    --repository-names "$1" \
    --query 'repositories[0].repositoryUri' \
    --output text
}

backend_repository_uri="$(repository_uri "$AWS_ECR_BACKEND_REPOSITORY")"
frontend_repository_uri="$(repository_uri "$AWS_ECR_FRONTEND_REPOSITORY")"
registry="${actual_account_id}.dkr.ecr.${AWS_REGION}.amazonaws.com"

[[ "$backend_repository_uri" == "$registry/$AWS_ECR_BACKEND_REPOSITORY" ]] || {
  echo "backend repository URI is outside the exact account/region/repository" >&2
  exit 1
}
[[ "$frontend_repository_uri" == "$registry/$AWS_ECR_FRONTEND_REPOSITORY" ]] || {
  echo "frontend repository URI is outside the exact account/region/repository" >&2
  exit 1
}

publication_boundary_fingerprint="$(
  printf '%s' "$actual_account_id|$AWS_REGION|$backend_repository_uri|$frontend_repository_uri" |
    sha256sum |
    awk '{print $1}'
)"
if [[ -n "${FORBIDDEN_IMAGE_PUBLICATION_BOUNDARY_FINGERPRINT:-}" && \
      "$publication_boundary_fingerprint" == "$FORBIDDEN_IMAGE_PUBLICATION_BOUNDARY_FINGERPRINT" ]]; then
  echo "production image publication resolved to the staging repository boundary" >&2
  exit 1
fi

aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$registry" >/dev/null

docker load --input "$backend_archive" >/dev/null
docker load --input "$frontend_archive" >/dev/null

backend_source_image="proofshape-release/backend:${RELEASE_SHA}"
frontend_source_image="proofshape-release/frontend:${RELEASE_SHA}"
backend_image_id="$(docker image inspect "$backend_source_image" --format '{{.Id}}')"
frontend_image_id="$(docker image inspect "$frontend_source_image" --format '{{.Id}}')"
[[ "$backend_image_id" == "$(jq -r '.images.backend.localImageId' "$manifest")" ]] || {
  echo "backend archive image ID differs from the scanned/sealed image" >&2
  exit 1
}
[[ "$frontend_image_id" == "$(jq -r '.images.frontend.localImageId' "$manifest")" ]] || {
  echo "frontend archive image ID differs from the scanned/sealed image" >&2
  exit 1
}

publish_component() {
  local component="$1"
  local repository_uri="$2"
  local repository_name="$3"
  local source_image="proofshape-release/${component}:${RELEASE_SHA}"
  local run_suffix="${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-1}"
  local immutable_tag="release-${RELEASE_SHA}-${run_suffix}"

  docker image inspect "$source_image" >/dev/null
  docker tag "$source_image" "${repository_uri}:${immutable_tag}"
  docker push "${repository_uri}:${immutable_tag}" >/dev/null

  aws ecr describe-images \
    --repository-name "$repository_name" \
    --image-ids "imageTag=${immutable_tag}" \
    --query 'imageDetails[0].imageDigest' \
    --output text
}

backend_digest="$(publish_component backend "$backend_repository_uri" "$AWS_ECR_BACKEND_REPOSITORY")"
frontend_digest="$(publish_component frontend "$frontend_repository_uri" "$AWS_ECR_FRONTEND_REPOSITORY")"

for digest in "$backend_digest" "$frontend_digest"; do
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "ECR returned an invalid image digest" >&2
    exit 1
  }
done

if [[ -n "${EXPECTED_BACKEND_DIGEST:-}" && "$backend_digest" != "$EXPECTED_BACKEND_DIGEST" ]]; then
  echo "backend digest differs from the staged exact artifact" >&2
  exit 1
fi
if [[ -n "${EXPECTED_FRONTEND_DIGEST:-}" && "$frontend_digest" != "$EXPECTED_FRONTEND_DIGEST" ]]; then
  echo "frontend digest differs from the staged exact artifact" >&2
  exit 1
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "account_id=${actual_account_id}"
    echo "backend_digest=${backend_digest}"
    echo "frontend_digest=${frontend_digest}"
    echo "publication_boundary_fingerprint=${publication_boundary_fingerprint}"
  } >>"$GITHUB_OUTPUT"
fi

if [[ -n "${AWS_IMAGE_PUBLICATION_EVIDENCE_PATH:-}" ]]; then
  mkdir -p "$(dirname "$AWS_IMAGE_PUBLICATION_EVIDENCE_PATH")"
  jq -n \
    --arg release_sha "$RELEASE_SHA" \
    --arg account_id "$actual_account_id" \
    --arg region "$AWS_REGION" \
    --arg backend "${backend_repository_uri}@${backend_digest}" \
    --arg frontend "${frontend_repository_uri}@${frontend_digest}" \
    --arg backend_scan_sha "$(jq -r '.securityEvidence.backendScan.sha256' "$manifest")" \
    --arg frontend_scan_sha "$(jq -r '.securityEvidence.frontendScan.sha256' "$manifest")" \
    --arg backend_sbom_sha "$(jq -r '.securityEvidence.backendSbom.sha256' "$manifest")" \
    --arg frontend_sbom_sha "$(jq -r '.securityEvidence.frontendSbom.sha256' "$manifest")" \
    --arg boundary_fingerprint "$publication_boundary_fingerprint" \
    '{schema:2, releaseSha:$release_sha, accountId:$account_id, region:$region, boundaryFingerprint:$boundary_fingerprint, images:{backend:$backend, frontend:$frontend}, exactImageSecurityEvidence:{policy:"HIGH,CRITICAL:fail", backendScanSha256:$backend_scan_sha, frontendScanSha256:$frontend_scan_sha, backendSbomSha256:$backend_sbom_sha, frontendSbomSha256:$frontend_sbom_sha}}' \
    >"$AWS_IMAGE_PUBLICATION_EVIDENCE_PATH"
fi

echo "Published exact release image artifacts for ${RELEASE_SHA}."
