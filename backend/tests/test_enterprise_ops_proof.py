from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_yaml(path: str) -> dict:
    return yaml.safe_load(read(path))


def workflow_triggers(workflow: dict) -> dict:
    # PyYAML follows YAML 1.1 and parses the GitHub Actions "on" key as True.
    return workflow.get("on") or workflow[True]


def service_env(service: dict) -> set[str]:
    env = service.get("environment", [])
    if isinstance(env, dict):
        return {f"{key}={value}" for key, value in env.items()}
    return set(env)


def healthcheck_command(service: dict) -> str:
    return "\n".join(service["healthcheck"]["test"])


def test_ci_build_proof_and_aws_promotion_use_one_exact_artifact_set():
    workflow = load_yaml(".github/workflows/ci.yml")
    promotion = load_yaml(".github/workflows/aws-commercial-promote.yml")
    triggers = workflow_triggers(workflow)
    promotion_inputs = workflow_triggers(promotion)["workflow_dispatch"]["inputs"]

    for event in ("push", "pull_request"):
        branches = triggers[event]["branches"]
        assert "dev" in branches
        assert "main" in branches

    docker_job = workflow["jobs"]["docker-build"]
    assert set(docker_job["needs"]) == {"backend", "frontend"}

    step_names = {step.get("name") for step in docker_job["steps"]}
    assert "Validate Compose deploy configs" in step_names
    assert "Lint and render Helm chart" in step_names
    assert "Build frontend production image" in step_names
    assert "Build backend production image" in step_names
    assert "Write source-bound container build manifest" in step_names

    ci_text = read(".github/workflows/ci.yml")
    assert "registry.fly.io" not in ci_text
    assert "flyctl" not in ci_text
    assert "push: false" in ci_text
    assert "CI_BUILD_PROOF" in ci_text

    assert "deploy" not in workflow["jobs"]
    assert not (ROOT / ".github/workflows/saas-promote.yml").exists()

    assert promotion_inputs["promotion_scope"]["default"] == "staging-only"
    assert promotion_inputs["promotion_scope"]["options"] == [
        "publish-staging-only",
        "publish-staging-and-production",
        "migrate-staging-only",
        "migrate-staging-and-production",
        "staging-only",
        "staging-and-production",
        "kill-switch-staging-off",
        "kill-switch-staging-on",
        "kill-switch-staging-test",
        "kill-switch-production-off",
        "kill-switch-production-on",
    ]
    assert promotion["concurrency"] == {
        "group": "aws-commercial-control-plane",
        "cancel-in-progress": False,
    }

    build = promotion["jobs"]["build-release-images"]
    staging = promotion["jobs"]["deploy-staging"]
    production = promotion["jobs"]["deploy-production"]
    staging_kill = promotion["jobs"]["kill-switch-staging"]
    production_kill = promotion["jobs"]["kill-switch-production"]

    assert build["if"] == (
        "github.ref == 'refs/heads/main' && "
        "!startsWith(inputs.promotion_scope, 'kill-switch-')"
    )
    assert staging["environment"] == "aws-commercial-staging"
    assert production["environment"] == "aws-commercial-production"
    assert staging["needs"] == "build-release-images"
    assert set(production["needs"]) == {"build-release-images", "deploy-staging"}
    for required_scope in (
        "staging-and-production",
        "publish-staging-and-production",
        "migrate-staging-and-production",
    ):
        assert required_scope in production["if"]
    assert staging["permissions"]["id-token"] == "write"
    assert production["permissions"]["id-token"] == "write"
    assert staging_kill["environment"] == "aws-commercial-staging"
    assert production_kill["environment"] == "aws-commercial-production"
    assert production["env"]["STAGING_AWS_ACCOUNT_ID"] == (
        "${{ needs.deploy-staging.outputs.account_id }}"
    )

    build_steps = {step.get("name") for step in build["steps"]}
    staging_steps = {step.get("name") for step in staging["steps"]}
    production_steps = {step.get("name") for step in production["steps"]}
    assert "Validate protected release source and exact protected-main CI" in build_steps
    assert "Validate release-invariant browser observability contract" in build_steps
    assert "Build backend release image archive" in build_steps
    assert "Build frontend release image archive" in build_steps
    assert "Seal archive hashes before any release test or scan" in build_steps
    assert "Exercise security and storage contracts from the exact archives" in build_steps
    assert "Scan exact backend archive image (high/critical vulnerabilities)" in build_steps
    assert "Scan exact frontend archive image (high/critical vulnerabilities)" in build_steps
    assert "Generate backend CycloneDX SBOM from the exact archive image" in build_steps
    assert "Generate frontend CycloneDX SBOM from the exact archive image" in build_steps
    assert "Bind exact image IDs and SBOM hashes into the sealed manifest" in build_steps
    assert "Upload immutable exact-image release, scan, and SBOM evidence" in build_steps
    assert "Validate exact-release supplier holdout before any staging mutation" in staging_steps
    assert "Download exact scanned release image artifacts" in staging_steps
    assert "Publish exact artifacts to immutable staging ECR" in staging_steps
    assert "Run release-bound migration and optional service promotion" in staging_steps
    assert "Drill and restore the AWS-native staging intake kill switch" in staging_steps
    assert "Recheck deep health after kill-switch restoration" in staging_steps
    assert "Revalidate isolated production contract" in production_steps
    assert "Independently validate exact-release production supplier holdout" in production_steps
    assert "Require production supplier holdout digest to equal staging" in production_steps
    assert "Download the staged exact scanned release image artifacts" in production_steps
    assert "Publish the exact staged artifacts to immutable production ECR" in production_steps
    assert "Run release-bound migration and optional production promotion" in production_steps

    staging_step_order = [step.get("name") for step in staging["steps"]]
    assert staging_step_order.index(
        "Validate exact-release supplier holdout before any staging mutation"
    ) < staging_step_order.index("Configure AWS credentials through environment-scoped OIDC")
    production_step_order = [step.get("name") for step in production["steps"]]
    assert production_step_order.index(
        "Independently validate exact-release production supplier holdout"
    ) < production_step_order.index(
        "Require production supplier holdout digest to equal staging"
    ) < production_step_order.index(
        "Configure AWS credentials through production-scoped OIDC"
    )
    production_holdout_match = next(
        step
        for step in production["steps"]
        if step.get("name") == "Require production supplier holdout digest to equal staging"
    )
    assert production_holdout_match["env"]["PRODUCTION_HOLDOUT_DIGEST"] == (
        "${{ steps.holdout.outputs.evidence_sha256 }}"
    )
    assert production_holdout_match["env"]["STAGING_HOLDOUT_DIGEST"] == (
        "${{ needs.deploy-staging.outputs.holdout_digest }}"
    )
    assert staging["outputs"]["holdout_digest"] == (
        "${{ steps.holdout.outputs.evidence_sha256 }}"
    )

    production_publish = next(
        step
        for step in production["steps"]
        if step.get("name") == "Publish the exact staged artifacts to immutable production ECR"
    )
    assert production_publish["env"]["EXPECTED_BACKEND_DIGEST"] == (
        "${{ needs.deploy-staging.outputs.backend_digest }}"
    )
    assert production_publish["env"]["EXPECTED_FRONTEND_DIGEST"] == (
        "${{ needs.deploy-staging.outputs.frontend_digest }}"
    )
    for job in (staging, production):
        assert not any(
            (step.get("name") or "").startswith("Build ") for step in job["steps"]
        )

    workflow_text = read(".github/workflows/aws-commercial-promote.yml")
    for contract in (
        "AWS_ECS_API_BASE_TASK_DEFINITION",
        "AWS_ECS_FRONTEND_BASE_TASK_DEFINITION",
        "AWS_ECS_MIGRATION_BASE_TASK_DEFINITION",
        "AWS_ECS_WORKER_BASE_TASK_DEFINITION",
        "CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64",
        "scripts/ops/aws-kill-switch.sh test",
        "EXPECTED_BACKEND_DIGEST",
        "EXPECTED_FRONTEND_DIGEST",
    ):
        assert contract in workflow_text
    assert "backend.trivy.json" in workflow_text
    assert "frontend.trivy.json" in workflow_text
    assert "staging and production must use separate AWS accounts" in workflow_text
    assert "AWS_COMMERCIAL_NEXT_PUBLIC_SENTRY_DSN is required" in workflow_text

    publisher = read("scripts/ops/aws-publish-images.sh")
    assert "verify_scan backend" in publisher
    assert "verify_scan frontend" in publisher
    assert 'select(.Severity == "HIGH" or .Severity == "CRITICAL")' in publisher
    assert "exact-image vulnerability report SHA-256 mismatch" in publisher

    kill_switch = read("scripts/ops/aws-kill-switch.sh")
    assert 'case "$action" in' in kill_switch
    assert "off | on | test" in kill_switch
    assert "the disruptive off/on kill-switch drill is restricted to staging" in kill_switch
    assert "failing closed on the off revision" in kill_switch
    assert "deploy_revision \"$previous_task_definition\"" in kill_switch
    assert '[[ "$status" == 503 ]]' in kill_switch
    assert '[[ "$status" == 422 ]]' in kill_switch
    assert "Retry-After: 3600" in kill_switch
    assert "'.code == \"service_paused\"'" in kill_switch
    assert ".detail.code" not in kill_switch
    assert "expected_execution_role" in kill_switch
    assert "expected_task_role" in kill_switch
    assert "TURNSTILE_SECRET" in kill_switch

    promotion_script = read("scripts/ops/aws-commercial-promote.sh")
    assert "expected_secret_names" in promotion_script
    assert "runtime_secret_arns" in promotion_script
    assert ".executionRoleArn == $expected_execution_role" in promotion_script
    assert ".taskRoleArn == $expected_task_role" in promotion_script
    assert "describe-subnets" in promotion_script
    assert "describe-security-groups" in promotion_script
    assert "span two physical AZs" in promotion_script

    backend_steps = {step.get("name") for step in workflow["jobs"]["backend"]["steps"]}
    assert "Postgres restore drill" in backend_steps

    browser_steps = {step.get("name") for step in workflow["jobs"]["browser-e2e"]["steps"]}
    assert "Run human and enterprise browser journeys" in browser_steps


def test_frontend_dockerfile_matches_current_next_runtime_mode():
    next_config = read("frontend/next.config.ts")
    dockerfile = read("frontend/Dockerfile")
    enabled_standalone_lines = [
        line for line in next_config.splitlines()
        if 'output: "standalone"' in line and not line.lstrip().startswith("//")
    ]

    assert enabled_standalone_lines == []
    assert ".next/standalone" not in dockerfile
    assert "RUN npm prune --omit=dev" in dockerfile
    assert "COPY --from=builder --chown=node:node /app/node_modules ./node_modules" in dockerfile
    assert "USER node" in dockerfile
    assert "COPY --from=builder --chown=node:node /app/.next ./.next" in dockerfile
    assert 'CMD ["npm", "run", "start"]' in dockerfile


def test_compose_configs_have_smokeable_frontend_and_backend():
    local = load_yaml("docker-compose.yml")
    enterprise = load_yaml("cadverify-enterprise/docker-compose.yml")

    assert local["services"]["backend"]["build"] == "./backend"
    assert local["services"]["frontend"]["build"] == "./frontend"
    assert enterprise["services"]["backend"]["image"] == "cadverify-backend:latest"
    assert enterprise["services"]["frontend"]["image"] == "cadverify-frontend:latest"

    for compose in (local, enterprise):
        backend = compose["services"]["backend"]
        frontend = compose["services"]["frontend"]

        assert "127.0.0.1:8000/health" in healthcheck_command(backend)
        assert "python -c" in healthcheck_command(backend)
        assert "127.0.0.1:3000" in healthcheck_command(frontend)
        assert "node -e" in healthcheck_command(frontend)
        assert "API_BASE=http://backend:8000" in service_env(frontend)
        assert not any(item.startswith("NEXT_PUBLIC_API_BASE=") for item in service_env(frontend))
        assert "postgres" in compose["services"]
        assert "redis" in compose["services"]
        assert "pgdata" in compose["volumes"]
        assert "RATE_LIBRARY_ENABLED=1" in service_env(backend)

    assert "blobs" in enterprise["volumes"]
    assert "redis-data" in enterprise["volumes"]
    assert "./saml:/app/saml:ro" in enterprise["services"]["backend"]["volumes"]
    assert "RATE_LIBRARY_ENABLED=1" in service_env(enterprise["services"]["worker"])


def test_aws_commercial_release_surface_and_fly_are_separated():
    ecs = read("infra/aws/ecs.tf")
    edge = read("infra/aws/edge.tf")
    networking = read("infra/aws/networking.tf")
    workflow = read(".github/workflows/aws-commercial-promote.yml")
    launch = read("docs/LAUNCH_RUNBOOK.md")

    assert 'requires_compatibilities = ["FARGATE"]' in ecs
    assert "readonlyRootFilesystem = true" in ecs
    assert 'AUTH_PROXY_CLIENT_IP_SOURCE         = "cloudfront"' in ecs
    assert 'resource "aws_cloudfront_vpc_origin" "alb"' in edge
    assert "internal           = true" in edge
    assert 'status_code  = "403"' in edge
    assert "CloudFront-VPCOrigins-Service-SG" in networking
    assert "scripts/ops/aws-publish-images.sh" in workflow
    assert "scripts/ops/aws-commercial-promote.sh" in workflow
    assert "flyctl" not in workflow.lower()
    assert "registry.fly.io" not in workflow
    assert not (ROOT / ".github/workflows/saas-promote.yml").exists()
    assert "legacy/non-release" in launch.lower()
    for stale_command in ("fly deploy", "fly apps create", "FLY_API_TOKEN"):
        assert stale_command not in launch


def test_worker_and_deploy_health_gate_require_arq_worker_heartbeat():
    worker = read("backend/src/jobs/worker.py")
    health = read("backend/src/api/health.py")
    ops = read("backend/src/services/ops_health_service.py")
    gate = read("scripts/ops/aws-deep-health.mjs")
    promotion = read("scripts/ops/aws-commercial-promote.sh")

    assert 'health_check_key = os.getenv("ARQ_HEALTH_KEY", "arq:queue:health-check")' in worker
    assert 'worker_strict = _flag("WORKER_STRICT_HEALTH", "0")' in health
    assert 'worker_degraded = worker_strict and async_expected and redis_ok and worker_state != "ok"' in health
    assert 'health_key = os.getenv("ARQ_HEALTH_KEY", "arq:queue:health-check")' in ops
    assert 'health.body?.async?.worker === "ok"' in gate
    assert 'health.body?.async?.worker_strict === true' in gate
    assert 'deep.body?.checks?.worker?.state === "ok"' in gate
    assert "AbortSignal.timeout(requestTimeoutMs)" in gate
    assert "CADVERIFY_DEEP_HEALTH_TOKEN" in gate
    assert "aws ecs wait services-stable" in promotion
    assert "trap rollback ERR" in promotion
    assert "node scripts/ops/aws-deep-health.mjs" in promotion
    ecs = read("infra/aws/ecs.tf")
    assert "arq src.jobs.worker.WorkerSettings --check" in ecs
    assert "r.statusCode >= 200 && r.statusCode < 400" in ecs


def test_helm_chart_gates_multi_replica_blob_and_worker_ops():
    values = load_yaml("charts/cadverify/values.yaml")
    worker = read("charts/cadverify/templates/deployment-worker.yaml")
    pvc = read("charts/cadverify/templates/pvc-blobs.yaml")
    workflow = read(".github/workflows/ci.yml")

    assert values["replicaCount"]["backend"] > 1
    assert values["replicaCount"]["worker"] > 1
    assert "ReadWriteMany" in values["persistence"]["blobs"]["accessModes"]
    assert ".Values.persistence.blobs.accessModes" in pvc
    assert "livenessProbe:" in worker
    assert "readinessProbe:" in worker
    assert "kill -0 1" in worker
    assert "readOnlyRootFilesystem" in read("charts/cadverify/values.yaml")
    assert "networkPolicy.enabled=true" in read("charts/cadverify/templates/_helpers.tpl")
    assert "runtimeSecret.existingSecret" in read("charts/cadverify/templates/_helpers.tpl")
    assert "helm lint charts/cadverify" in workflow
    assert "helm template cadverify charts/cadverify" in workflow


def test_regulated_secret_gate_validates_saml_security_profile_not_only_files():
    gate = read("scripts/ops/k8s-required-secrets-gate.sh")

    assert ".strict == true" in gate
    assert ".security.wantMessagesSigned == true" in gate
    assert ".security.wantAssertionsSigned == true" in gate
    assert 'keys - ["contactPerson", "organization", "security"]' in gate
    assert "rsa-sha256" in gate
    assert "xmlenc#sha256" in gate
    assert ".security.rejectDeprecatedAlgorithm == true" in gate
    assert ".idp.x509cert" in gate
    assert "base64 --decode | jq -e" in gate


def test_production_lock_gate_is_platform_neutral():
    workflow = read(".github/workflows/ci.yml")

    assert "--no-header --no-annotate" in workflow
    assert "diff -u requirements-prod.lock /tmp/requirements-prod.lock" in workflow


def test_protected_browser_gate_fails_required_journey_skips():
    workflow = read(".github/workflows/ci.yml")
    p7 = read("scripts/e2e/p7-role-failure-journey-runner.mjs")

    assert 'E2E_FAIL_ON_UNAVAILABLE: "1"' in workflow
    assert '!process.argv.includes("--allow-unavailable")' in p7
    assert "failOnUnavailable && skippedSteps > 0" in p7
    assert 'status === "SKIPPED_UNAVAILABLE" && failOnUnavailable' in p7


def test_pre_human_real_cad_and_ops_gates_are_in_full_e2e_chain():
    package = read("frontend/package.json")
    real_cad = read("scripts/prehuman/real_cad_corpus.py")
    restore = read("scripts/ops/postgres-restore-drill.sh")
    load = read("scripts/ops/api-load-smoke.mjs")
    readiness = read("scripts/e2e/enterprise-prehuman-readiness.mjs")
    scim_idp = read("scripts/e2e/scim-idp-lifecycle.mjs")
    connector_replay = read("scripts/e2e/connector-sandbox-fixture-replay.mjs")

    assert "test:e2e:scim-idp" in package
    assert "test:e2e:connector-fixtures" in package
    assert "test:e2e:real-cad-corpus" in package
    assert "test:e2e:ops-restore" in package
    assert "test:e2e:ops-load" in package
    assert "test:e2e:readiness" in package
    assert "npm run test:e2e:scim-idp" in package
    assert "npm run test:e2e:connector-fixtures" in package
    assert "NIST-PMI-STEP-Files.zip" in real_cad
    assert "NIST-MTC-Assembly.zip" in real_cad
    assert "block_network_sockets" in real_cad
    assert "SCIM protocol lifecycle simulation" in scim_idp
    assert "CADVERIFY_SCIM_TOKEN" in scim_idp
    assert "sap_s4hana_product_bom_readonly" in connector_replay
    assert "windchill_part_bom_readonly" in connector_replay
    assert "offline sandbox fixture replay, not live vendor certification" in connector_replay
    assert "pg_dump" in restore
    assert "pg_restore" in restore
    assert "/api/v1/validate/cost/demo" in load
    assert "enterprise-prehuman-readiness" in readiness


def test_admin_queue_health_surface_is_real_and_pii_safe():
    admin = read("backend/src/api/admin_routes.py")
    service = read("backend/src/services/ops_health_service.py")
    script = read("scripts/ops/check-queue-health.py")

    assert '@router.get("/ops/queue-health")' in admin
    assert "summarize_queue_health(session, org_id=org_filter)" in admin
    assert "require_admin = require_org_role(OrgRole.admin)" in admin
    assert "WebhookDelivery.payload_json" not in service
    assert "BatchItem.filename" not in service
    assert "User.email" not in service
    assert "CADVERIFY_API_KEY" in script
    assert "/api/v1/admin/ops/queue-health" in script
