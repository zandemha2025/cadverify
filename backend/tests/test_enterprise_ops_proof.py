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


def assert_contains_all(text: str, expected: list[str]) -> None:
    missing = [needle for needle in expected if needle not in text]
    assert missing == []


def test_ci_releases_images_and_protected_workflow_promotes_staging_first():
    workflow = load_yaml(".github/workflows/ci.yml")
    promotion = load_yaml(".github/workflows/saas-promote.yml")
    triggers = workflow_triggers(workflow)

    for event in ("push", "pull_request"):
        branches = triggers[event]["branches"]
        assert "dev" in branches
        assert "main" in branches

    docker_job = workflow["jobs"]["docker-build"]
    assert set(docker_job["needs"]) == {"backend", "frontend"}

    step_names = {step.get("name") for step in docker_job["steps"]}
    assert "Validate Compose deploy configs" in step_names
    assert "Lint and render Helm chart" in step_names
    assert "Build frontend production image and push on main" in step_names
    assert "Build backend production image and push on main" in step_names

    assert "deploy" not in workflow["jobs"]
    staging = promotion["jobs"]["deploy-staging"]
    production = promotion["jobs"]["deploy-production"]
    assert staging["environment"] == "saas-staging"
    assert production["environment"] == "saas-production"
    assert production["needs"] == "deploy-staging"
    assert staging["if"] == "github.ref == 'refs/heads/main'"
    staging_steps = {step.get("name") for step in staging["steps"]}
    production_steps = {step.get("name") for step in production["steps"]}
    assert "Require a successful CI release for this exact SHA" in staging_steps
    assert "Download CI-owned immutable release manifest" in staging_steps
    assert "Deploy and verify staging" in staging_steps
    assert "Validate isolated production environment contract" in production_steps
    assert "Deploy and verify production" in production_steps

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


def test_fly_configs_describe_deploy_surface_without_external_proof_claims():
    backend = read("backend/fly.toml")
    frontend = read("frontend/fly.toml")
    workflow = read(".github/workflows/ci.yml")

    assert_contains_all(
        backend,
        [
            'app = "cadvrfy-api"',
            '[processes]',
            'web = "uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --no-server-header"',
            'worker = "arq src.jobs.worker.WorkerSettings"',
            '[http_service]',
            "internal_port = 8000",
            "force_https = true",
            'OBJECT_STORE_BACKEND = "s3"',
            'METRICS_ENABLED = "0"',
            'PDF_CACHE_DIR = "/tmp/cadverify/pdf-cache"',
            "ARQ_HEALTH_KEY = \"arq:queue:health-check\"",
            "WORKER_STRICT_HEALTH = \"1\"",
            "RATE_LIBRARY_ENABLED = \"1\"",
            "ANALYSIS_TIMEOUT_SEC = \"60\"",
            "[deploy]",
            "alembic upgrade head",
            'memory = "2gb"',
        ],
    )

    assert_contains_all(
        frontend,
        [
            'app = "cadvrfy-web"',
            "[env]",
            'PRODUCTION_PUBLIC_API_TLS_REQUIRED = "1"',
            "[http_service]",
            "internal_port = 3000",
            "force_https = true",
        ],
    )
    assert "registry.fly.io/cadvrfy-web:${{ github.sha }}" in workflow
    promotion = read("scripts/ops/promote-fly-release.sh")
    assert "--config frontend/fly.toml" in promotion
    assert 'flyctl scale count web=2 worker=2 --app "$FLY_API_APP" --yes' in promotion
    assert "node scripts/ops/fly-required-secrets-gate.mjs" in promotion
    assert "node scripts/ops/fly-live-health-gate.mjs" in promotion
    assert 'docker manifest inspect "$CADVERIFY_BACKEND_IMAGE"' in promotion


def test_worker_and_deploy_health_gate_require_arq_worker_heartbeat():
    worker = read("backend/src/jobs/worker.py")
    health = read("backend/src/api/health.py")
    ops = read("backend/src/services/ops_health_service.py")
    gate = read("scripts/ops/fly-live-health-gate.mjs")
    secrets_gate = read("scripts/ops/fly-required-secrets-gate.mjs")

    assert 'health_check_key = os.getenv("ARQ_HEALTH_KEY", "arq:queue:health-check")' in worker
    assert 'worker_strict = _flag("WORKER_STRICT_HEALTH", "0")' in health
    assert 'worker_degraded = worker_strict and async_expected and redis_ok and worker_state != "ok"' in health
    assert 'health_key = os.getenv("ARQ_HEALTH_KEY", "arq:queue:health-check")' in ops
    assert 'body?.async?.worker === "ok"' in gate
    assert 'body?.async?.worker_strict === true' in gate
    assert 'CADVERIFY_REQUIRE_WORKER_STRICT' in gate
    assert "AbortSignal.timeout(requestTimeoutMs)" in gate
    assert "API_KEY_PEPPER" in secrets_gate
    assert "CONNECTOR_SECRET_KEY" in secrets_gate
    assert "CONNECTOR_FINGERPRINT_KEY" in secrets_gate
    assert "DEEP_HEALTH_TOKEN" in secrets_gate
    assert "CADVERIFY_DEEP_HEALTH_TOKEN" in gate


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
