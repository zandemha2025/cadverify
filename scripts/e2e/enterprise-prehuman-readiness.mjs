import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);

const artifacts = {
  json: path.join(outputRoot, `enterprise-prehuman-readiness-${runId}.json`),
  md: path.join(outputRoot, `qa-report-enterprise-prehuman-readiness-${runId}.md`),
};

const reports = {
  human: path.join(outputRoot, `human-e2e-${runId}.json`),
  enterprise: path.join(outputRoot, `enterprise-domain-${runId}.json`),
  p7: path.join(outputRoot, `p7-role-failure-${runId}.json`),
  coverage: path.join(outputRoot, `human-sim-journey-coverage-${runId}.json`),
  gauntlet: path.join(outputRoot, `synthetic-enterprise-gauntlet-${runId}.json`),
  fidelity: path.join(outputRoot, `enterprise-answer-fidelity-${runId}.json`),
  realCad: path.join(outputRoot, `prehuman-real-cad-corpus-${runId}.json`),
  loadSmoke: path.join(outputRoot, `api-load-smoke-${runId}.json`),
  restoreDrill: path.join(outputRoot, `postgres-restore-drill-${runId}.json`),
};

const files = {
  workflow: path.join(repoRoot, ".github/workflows/ci.yml"),
  frontendPackage: path.join(repoRoot, "frontend/package.json"),
  routeAuth: path.join(repoRoot, "scripts/ci/check_route_auth.py"),
  rfqService: path.join(repoRoot, "backend/src/services/rfq_package_service.py"),
  integrationService: path.join(repoRoot, "backend/src/services/integration_service.py"),
  samlService: path.join(repoRoot, "backend/src/services/org_saml_service.py"),
  helmValues: path.join(repoRoot, "charts/cadverify/values.yaml"),
  helmWorker: path.join(repoRoot, "charts/cadverify/templates/deployment-worker.yaml"),
  helmPvc: path.join(repoRoot, "charts/cadverify/templates/pvc-blobs.yaml"),
  backendFly: path.join(repoRoot, "backend/fly.toml"),
  frontendFly: path.join(repoRoot, "frontend/fly.toml"),
  restoreScript: path.join(repoRoot, "scripts/ops/postgres-restore-drill.sh"),
  loadScript: path.join(repoRoot, "scripts/ops/api-load-smoke.mjs"),
  realCadScript: path.join(repoRoot, "scripts/prehuman/real_cad_corpus.py"),
  enterpriseOpsTest: path.join(repoRoot, "backend/tests/test_enterprise_ops_proof.py"),
};

function assert(condition, detail) {
  if (!condition) throw new Error(detail);
}

async function readJson(filename) {
  assert(existsSync(filename), `missing artifact: ${filename}`);
  return JSON.parse(await readFile(filename, "utf8"));
}

async function readText(filename) {
  assert(existsSync(filename), `missing file: ${filename}`);
  return readFile(filename, "utf8");
}

function contains(text, ...needles) {
  const missing = needles.filter((needle) => !text.includes(needle));
  assert(missing.length === 0, `missing text: ${missing.join(", ")}`);
}

function reportIsClean(report, label) {
  assert(report.status === "PASS", `${label} status is ${report.status}`);
  assert((report.steps || []).filter((step) => step.status === "fail").length === 0, `${label} has failed steps`);
  assert((report.steps || []).filter((step) => step.status === "skip").length === 0, `${label} has skipped steps`);
  assert((report.issues || []).length === 0, `${label} has issues`);
  assert((report.consoleErrors || []).length === 0, `${label} has console errors`);
  assert((report.requestFailures || []).length === 0, `${label} has request failures`);
}

async function check(id, domain, fn) {
  try {
    return { id, domain, status: "PASS", evidence: await fn() };
  } catch (error) {
    return { id, domain, status: "FAIL", error: error instanceof Error ? error.message : String(error) };
  }
}

function allPass(items) {
  return (items || []).every((item) => item.status === "PASS");
}

async function main() {
  const [
    human,
    enterprise,
    p7,
    coverage,
    gauntlet,
    fidelity,
    realCad,
    loadSmoke,
    restoreDrill,
    workflow,
    frontendPackage,
    routeAuth,
    rfqService,
    integrationService,
    samlService,
    helmValues,
    helmWorker,
    helmPvc,
    backendFly,
    frontendFly,
    restoreScript,
    loadScript,
    realCadScript,
    enterpriseOpsTest,
  ] = await Promise.all([
    readJson(reports.human),
    readJson(reports.enterprise),
    readJson(reports.p7),
    readJson(reports.coverage),
    readJson(reports.gauntlet),
    readJson(reports.fidelity),
    readJson(reports.realCad),
    readJson(reports.loadSmoke),
    readJson(reports.restoreDrill),
    readText(files.workflow),
    readText(files.frontendPackage),
    readText(files.routeAuth),
    readText(files.rfqService),
    readText(files.integrationService),
    readText(files.samlService),
    readText(files.helmValues),
    readText(files.helmWorker),
    readText(files.helmPvc),
    readText(files.backendFly),
    readText(files.frontendFly),
    readText(files.restoreScript),
    readText(files.loadScript),
    readText(files.realCadScript),
    readText(files.enterpriseOpsTest),
  ]);

  const checks = [
    await check("BROWSER-SURFACE-001", "Human-simulated web app surface", async () => {
      reportIsClean(human, "human journey");
      reportIsClean(enterprise, "enterprise journey");
      reportIsClean(p7, "role/failure journey");
      assert(coverage.status === "PASS", "journey coverage failed");
      assert(coverage.requiredBranches === coverage.coveredBranches, "journey branch tree incomplete");
      assert(gauntlet.status === "PASS", "synthetic enterprise gauntlet failed");
      return {
        humanSteps: human.steps.length,
        enterpriseSteps: enterprise.steps.length,
        p7Steps: p7.steps.length,
        coveredBranches: coverage.coveredBranches,
        gauntletScenarios: gauntlet.scenarios.length,
      };
    }),

    await check("REAL-CAD-001", "Real public CAD corpus before humans", async () => {
      assert(realCad.status === "PASS", `real CAD corpus status ${realCad.status}`);
      assert(Object.values(realCad.acceptance || {}).every(Boolean), "real CAD acceptance gates incomplete");
      assert(realCad.cases.length >= 10, "real CAD corpus has too few cases");
      assert(realCad.cases.some((item) => item.schema === "AP242" && item.status === "PASS"), "missing AP242 pass");
      assert(realCad.cases.some((item) => item.family === "STC" && item.status === "PASS"), "missing STC pass");
      assert(realCad.cases.some((item) => item.expected_outcome === "UNSUPPORTED_SUFFIX" && item.status === "PASS"), "missing native-CAD unsupported control");
      assert(/skipped unless OCP XDE is available/.test(realCad.truth_boundary), "PMI/XDE boundary is not explicit");
      contains(realCadScript, "block_network_sockets", "NIST-PMI-STEP-Files.zip", "NIST-MTC-Assembly.zip");
      return {
        cases: realCad.cases.length,
        acceptance: realCad.acceptance,
        pmiStatus: [...new Set(realCad.cases.map((item) => item.pmi_check?.status).filter(Boolean))],
      };
    }),

    await check("ANSWER-FIDELITY-001", "Enterprise answer fidelity", async () => {
      assert(fidelity.status === "PASS", `answer fidelity status ${fidelity.status}`);
      assert(allPass(fidelity.checks), "answer fidelity has failed checks");
      assert(/does not certify a live Exxon/.test(fidelity.boundary), "external certification boundary drifted");
      const ids = new Set((fidelity.checks || []).map((item) => item.id));
      for (const id of [
        "INPUT-INTEGRITY-001",
        "METHODOLOGY-HONESTY-001",
        "CALCULATION-FIDELITY-001",
        "DISPLAY-FIDELITY-001",
      ]) {
        assert(ids.has(id), `missing answer fidelity check ${id}`);
      }
      return { checks: fidelity.checks.length };
    }),

    await check("DEPLOY-PIPELINE-001", "Production deploy and release gates", async () => {
      contains(
        workflow,
        "Build frontend production image and push on main",
        "Deploy frontend (pre-built image)",
        "Deploy backend (pre-built image)",
        "Lint and render Helm chart",
        "Postgres restore drill",
        "Run human and enterprise browser journeys"
      );
      contains(frontendPackage, "test:e2e:real-cad-corpus", "test:e2e:ops-load", "test:e2e:ops-restore", "test:e2e:readiness");
      contains(backendFly, 'app = "cadvrfy-api"', "alembic upgrade head");
      contains(frontendFly, 'app = "cadverify-web"', "force_https = true");
      return {
        deployTargets: ["backend Fly app", "frontend Fly app", "Helm render", "Docker images"],
      };
    }),

    await check("SECURITY-POSTURE-001", "Security and least privilege gates", async () => {
      contains(routeAuth, "require_api_key", "PUBLIC_ALLOWLIST", "backend/src/api");
      contains(
        workflow,
        "Every /api/v1 route calls require_api_key",
        "cv_live_ never appears in captured Sentry payload"
      );
      contains(
        enterpriseOpsTest,
        "test_admin_queue_health_surface_is_real_and_pii_safe",
        "test_fly_configs_describe_deploy_surface_without_external_proof_claims"
      );
      assert(p7.evidence?.lowRoleAdminUsers?.status === 403, "viewer admin denial did not pass");
      return {
        viewerAdminStatus: p7.evidence.lowRoleAdminUsers.status,
        routeAuthGate: true,
        sentryLeakGate: true,
      };
    }),

    await check("RFQ-PROCUREMENT-001", "RFQ and procurement honesty", async () => {
      contains(rfqService, "not live procurement", "Live supplier send", "Raw CAD included", "confidence_unvalidated");
      assert(gauntlet.scenarios.some((item) => item.id === "SUPPLIER-RFQ-001" && item.status === "PASS"), "RFQ gauntlet missing");
      assert(gauntlet.scenarios.some((item) => item.id === "PROCURE-APPROVAL-001" && item.status === "PASS"), "procurement approval gauntlet missing");
      return {
        mode: "RFQ package/export proof, no live supplier-send claim",
      };
    }),

    await check("LOAD-RESTORE-001", "Load, restore, and reliability proof", async () => {
      assert(loadSmoke.status === "PASS", `load smoke status ${loadSmoke.status}`);
      assert(loadSmoke.summary?.failed === 0, "load smoke had failed requests");
      assert(loadSmoke.summary?.p95Ms <= loadSmoke.threshold?.maxP95Ms, "load smoke p95 exceeded threshold");
      assert(restoreDrill.status === "PASS", `restore drill status ${restoreDrill.status}`);
      assert(restoreDrill.public_table_count > 0, "restore drill restored no tables");
      assert(restoreDrill.alembic_version_rows > 0, "restore drill did not restore alembic_version");
      contains(restoreScript, "pg_dump", "pg_restore", "DROP DATABASE IF EXISTS");
      contains(loadScript, "/api/v1/validate/cost/demo", "CADVERIFY_LOAD_MAX_P95_MS");
      return {
        load: loadSmoke.summary,
        restore: {
          dumpBytes: restoreDrill.dump_bytes,
          publicTableCount: restoreDrill.public_table_count,
        },
      };
    }),

    await check("HELM-OPS-001", "Kubernetes operational assumptions", async () => {
      contains(helmValues, "accessModes:", "ReadWriteMany");
      contains(helmPvc, ".Values.persistence.blobs.accessModes");
      contains(helmWorker, "livenessProbe:", "readinessProbe:", "import src.jobs.worker");
      contains(workflow, "helm lint charts/cadverify", "helm template cadverify charts/cadverify");
      return {
        blobPvcMode: "ReadWriteMany configurable",
        workerProbe: "import probe rendered",
      };
    }),

    await check("CONNECTOR-ORG-SIM-001", "Enterprise connector and org simulation", async () => {
      contains(integrationService, "sap_manifest_csv", "plm_manifest_csv", "file_sha256", "raw_stored=False");
      contains(samlService, "resolve_saml_group_assignment", "SamlGroupMappingAmbiguousError");
      assert(gauntlet.scenarios.some((item) => item.id === "SSO-SCIM-001" && item.status === "PASS"), "SSO/SCIM simulation missing");
      assert(gauntlet.scenarios.some((item) => item.id === "SAP-ERP-001" && item.status === "PASS"), "SAP/ERP simulation missing");
      assert(gauntlet.scenarios.some((item) => item.id === "PLM-BOM-001" && item.status === "PASS"), "PLM/BOM simulation missing");
      return {
        connectorMode: "offline hashed manifests, no live SAP/PLM certification claim",
      };
    }),
  ];

  const failed = checks.filter((item) => item.status !== "PASS");
  const data = {
    status: failed.length === 0 ? "PASS" : "NEEDS_FIXES",
    generatedAt: new Date().toISOString(),
    runId,
    boundary:
      "This is a pre-human enterprise readiness gate. It proves the app, simulated organization, real public CAD corpus, load/restore, deploy config, and answer fidelity before customer testing. It is not a live customer certification, formal security audit, SOC2, or vendor connector certification.",
    checks,
    failed,
  };

  await mkdir(outputRoot, { recursive: true });
  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));
  console.log(
    JSON.stringify(
      {
        status: data.status,
        checks: checks.length,
        passed: checks.length - failed.length,
        failed: failed.map((item) => ({ id: item.id, error: item.error })),
        report: artifacts.md,
      },
      null,
      2
    )
  );
  if (data.status !== "PASS") process.exitCode = 1;
}

function markdown(data) {
  const rows = data.checks
    .map((item) => `| ${item.status} | ${item.id} | ${item.domain} | ${item.error || "pass"} |`)
    .join("\n");
  return `# Enterprise Pre-Human Readiness

- Run: ${data.runId}
- Status: ${data.status}
- Boundary: ${data.boundary}

| Result | ID | Domain | Evidence |
| --- | --- | --- | --- |
${rows}

## Failed

\`\`\`json
${JSON.stringify(data.failed, null, 2)}
\`\`\`
`;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
