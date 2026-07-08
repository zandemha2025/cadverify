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
  json: path.join(outputRoot, `synthetic-enterprise-gauntlet-${runId}.json`),
  md: path.join(outputRoot, `qa-report-synthetic-enterprise-gauntlet-${runId}.md`),
};

const files = {
  human: path.join(outputRoot, `human-e2e-${runId}.json`),
  enterprise: path.join(outputRoot, `enterprise-domain-${runId}.json`),
  p7: path.join(outputRoot, `p7-role-failure-${runId}.json`),
  coverage: path.join(outputRoot, `human-sim-journey-coverage-${runId}.json`),
  integrationService: path.join(repoRoot, "backend/src/services/integration_service.py"),
  rfqService: path.join(repoRoot, "backend/src/services/rfq_package_service.py"),
  samlService: path.join(repoRoot, "backend/src/services/org_saml_service.py"),
  routeAuthCheck: path.join(repoRoot, "scripts/ci/check_route_auth.py"),
};

const syntheticOrg = {
  name: "MegaEnergy Synthetic Refining",
  archetype: "Exxon-style global energy manufacturing organization",
  operatingEnvelope: {
    annualVolume: 12000,
    plantCount: 4,
    materialClasses: ["stainless", "nickel alloy", "polymer"],
    serviceEnvironment: {
      pressureBar: 350,
      maxTempC: 120,
      sourService: true,
    },
    procurementThresholdsUsd: {
      engineerSelfServe: 25000,
      sourcingManager: 250000,
      capitalBoard: 1000000,
    },
  },
  personas: [
    "identity admin",
    "CAD engineer",
    "cost engineer",
    "sourcing manager",
    "supplier viewer",
    "security reviewer",
  ],
};

function assert(condition, detail) {
  if (!condition) throw new Error(detail);
}

async function readJson(filename) {
  return JSON.parse(await readFile(filename, "utf8"));
}

async function readText(filename) {
  return readFile(filename, "utf8");
}

function stepNames(report) {
  return new Set((report.steps || []).map((step) => step.name));
}

function hasStep(report, name) {
  return stepNames(report).has(name);
}

function reportIsClean(report, label) {
  const steps = report.steps || [];
  assert(report.status === "PASS", `${label} status is ${report.status}`);
  assert(steps.filter((step) => step.status === "fail").length === 0, `${label} has failed steps`);
  assert(steps.filter((step) => step.status === "skip").length === 0, `${label} has skipped steps`);
  assert((report.issues || []).length === 0, `${label} has issues`);
  assert((report.consoleErrors || []).length === 0, `${label} has console errors`);
  assert((report.requestFailures || []).length === 0, `${label} has request failures`);
}

function contains(text, ...needles) {
  return needles.every((needle) => text.includes(needle));
}

function pass(id, domain, simulation, evidence) {
  return { id, domain, status: "PASS", simulation, evidence };
}

function fail(id, domain, simulation, error) {
  return { id, domain, status: "FAIL", simulation, error: error.message || String(error) };
}

async function scenario(id, domain, simulation, fn) {
  try {
    return pass(id, domain, simulation, await fn());
  } catch (error) {
    return fail(id, domain, simulation, error);
  }
}

async function main() {
  const [human, enterprise, p7, coverage, integrationService, rfqService, samlService, routeAuthCheck] =
    await Promise.all([
      readJson(files.human),
      readJson(files.enterprise),
      readJson(files.p7),
      readJson(files.coverage),
      readText(files.integrationService),
      readText(files.rfqService),
      readText(files.samlService),
      readText(files.routeAuthCheck),
    ]);

  const scenarios = [
    await scenario(
      "SSO-SCIM-001",
      "Identity, SSO, and org provisioning",
      "Simulate Okta/AzureAD-style SAML group claims plus joiner/mover/viewer role pressure.",
      async () => {
        reportIsClean(human, "human web journey");
        reportIsClean(p7, "P7 role journey");
        assert(
          contains(
            samlService,
            "resolve_saml_group_assignment",
            "SamlGroupMappingAmbiguousError",
            "jit_group_assignment_no_demote_no_deprovision"
          ),
          "SAML group mapping service does not expose the expected enterprise assignment contract"
        );
        assert(
          enterprise.evidence?.member?.org_role === "admin",
          "enterprise signup did not produce an org-admin member"
        );
        assert(p7.evidence?.lowRoleAuth?.org_role === "viewer", "P7 low-role account was not a viewer");
        assert(
          p7.evidence?.lowRoleAdminUsers?.status === 403,
          "P7 low-role viewer was not denied admin/users"
        );
        return {
          ssoContract: "exact SAML group matching with ambiguity rejection",
          scimPressure: "joiner/mover/viewer role simulated through account creation, invite, accept, switch, and denial",
          adminOrgRole: enterprise.evidence.member.org_role,
          lowRoleOrgRole: p7.evidence.lowRoleAuth.org_role,
          lowRoleAdminStatus: p7.evidence.lowRoleAdminUsers.status,
        };
      }
    ),
    await scenario(
      "SAP-ERP-001",
      "SAP/ERP demand and cost feed",
      "Simulate SAP material/program/demand exports through the offline connector contract.",
      async () => {
        reportIsClean(enterprise, "enterprise CAD org journey");
        assert(
          contains(integrationService, "sap_manifest_csv", "SAP ERP", "MODE_DRY_RUN", "MODE_IMPORT"),
          "SAP manifest connector contract is missing"
        );
        assert(
          contains(integrationService, "raw_stored=False", "file_sha256"),
          "integration ledger must hash inputs without storing raw CSV"
        );
        assert(
          enterprise.evidence?.portfolio?.annual_volume === syntheticOrg.operatingEnvelope.annualVolume,
          "portfolio annual volume does not match the synthetic ERP demand profile"
        );
        assert(
          /Energy Valve Actuation/.test(enterprise.evidence?.portfolio?.program || ""),
          "portfolio program evidence did not survive enterprise journey"
        );
        return {
          connector: "sap_manifest_csv",
          ledger: "file hash and row counts, no raw CSV storage",
          annualVolume: enterprise.evidence.portfolio.annual_volume,
          program: enterprise.evidence.portfolio.program,
        };
      }
    ),
    await scenario(
      "PLM-BOM-001",
      "PLM/BOM and service environment",
      "Simulate PLM part registry, BOM context, material class, and severe service metadata.",
      async () => {
        assert(
          contains(integrationService, "plm_manifest_csv", "PLM", "Declared part registry export"),
          "PLM manifest connector contract is missing"
        );
        assert(hasStep(human, "Verify processes a real STEP file upload"), "real STEP upload branch is missing");
        assert(
          hasStep(enterprise, "CAD engineer verifies a real STEP file in a declared service world"),
          "enterprise declared service-world branch is missing"
        );
        assert(enterprise.evidence?.meshHash, "enterprise journey did not persist a mesh hash");
        assert(
          enterprise.evidence?.portfolio?.filename === "cube.step",
          "enterprise journey did not preserve the verified CAD filename"
        );
        return {
          connector: "plm_manifest_csv",
          cadFixture: enterprise.evidence.portfolio.filename,
          meshHash: enterprise.evidence.meshHash,
          serviceEnvironment: syntheticOrg.operatingEnvelope.serviceEnvironment,
        };
      }
    ),
    await scenario(
      "SUPPLIER-RFQ-001",
      "Supplier network and RFQ package",
      "Simulate supplier-network handoff without pretending a live supplier was contacted.",
      async () => {
        assert(
          contains(
            rfqService,
            "not live procurement",
            "Live supplier send",
            "Raw CAD included",
            "confidence_unvalidated"
          ),
          "RFQ package service does not preserve no-live-send and confidence warnings"
        );
        assert(hasStep(human, "authenticated app route /rfq-packages"), "RFQ package route branch missing");
        assert(hasStep(p7, "visible-copy sweep /rfq-packages"), "RFQ package final-copy sweep missing");
        return {
          supplierNetworkMode: "synthetic export package, no live supplier send",
          rawCadDefault: "not included unless explicitly requested and recoverable",
          uiBranches: ["/rfq-packages", "visible-copy sweep /rfq-packages"],
        };
      }
    ),
    await scenario(
      "PROCURE-APPROVAL-001",
      "Procurement approval and stale controls",
      "Simulate an enterprise approval matrix where governed assumptions can invalidate prior decisions.",
      async () => {
        assert(
          p7.evidence?.governanceInitial?.approval_status === "unreviewed",
          "governance fixture did not start unreviewed"
        );
        assert(
          p7.evidence?.governanceApproval?.reopened_status === "unreviewed",
          "governance approval did not reopen cleanly"
        );
        assert(
          /rate_library_published/.test(p7.evidence?.governanceStale?.stale_reason || ""),
          "governance stale reason did not reflect a governed rate publication"
        );
        assert(
          enterprise.evidence?.portfolio?.annualized_cost_usd >=
            syntheticOrg.operatingEnvelope.procurementThresholdsUsd.capitalBoard,
          "portfolio did not cross the synthetic capital-board procurement threshold"
        );
        return {
          initialStatus: p7.evidence.governanceInitial.approval_status,
          reopenedStatus: p7.evidence.governanceApproval.reopened_status,
          staleReason: p7.evidence.governanceStale.stale_reason,
          annualizedCostUsd: enterprise.evidence.portfolio.annualized_cost_usd,
          thresholdUsd: syntheticOrg.operatingEnvelope.procurementThresholdsUsd.capitalBoard,
        };
      }
    ),
    await scenario(
      "SECURITY-REVIEW-001",
      "Security review and least privilege",
      "Simulate security-review pressure: auth boundaries, API-key hygiene, role denial, and no hidden browser errors.",
      async () => {
        reportIsClean(human, "human web journey");
        reportIsClean(enterprise, "enterprise CAD org journey");
        reportIsClean(p7, "P7 role journey");
        assert(coverage.status === "PASS", "human-sim journey coverage did not pass");
        assert(coverage.requiredBranches === coverage.coveredBranches, "not all journey branches were covered");
        assert(
          contains(routeAuthCheck, "backend/src/api", "AUTH_DEPENDENCIES", "require_api_key", "PUBLIC_ALLOWLIST"),
          "route auth coverage checker is missing the all-router auth contract"
        );
        assert(
          p7.evidence?.["GET /api/proxy/admin/users"]?.status === 401,
          "unauthenticated admin/users was not denied"
        );
        assert(
          p7.evidence?.lowRoleAdminUsers?.status === 403,
          "low-role admin/users was not denied"
        );
        return {
          requiredBranches: coverage.requiredBranches,
          coveredBranches: coverage.coveredBranches,
          unauthAdminStatus: p7.evidence["GET /api/proxy/admin/users"].status,
          viewerAdminStatus: p7.evidence.lowRoleAdminUsers.status,
        };
      }
    ),
  ];

  const failed = scenarios.filter((item) => item.status !== "PASS");
  const data = {
    status: failed.length === 0 ? "PASS" : "NEEDS_FIXES",
    generatedAt: new Date().toISOString(),
    runId,
    syntheticOrg,
    simulationBoundary:
      "This is an educated, strenuous external-enterprise simulation. It is not a certification by Exxon, SAP, a PLM vendor, suppliers, or an auditor.",
    scenarios,
    failed,
  };

  await mkdir(outputRoot, { recursive: true });
  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));

  console.log(
    JSON.stringify(
      {
        status: data.status,
        org: syntheticOrg.name,
        scenarios: scenarios.length,
        passed: scenarios.length - failed.length,
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
  const scenarioRows = data.scenarios
    .map(
      (item) =>
        `| ${item.status} | ${item.id} | ${item.domain} | ${item.simulation} | ${
          item.error || "pass"
        } |`
    )
    .join("\n");
  return `# Synthetic Enterprise Gauntlet

- Date: ${data.runId}
- Status: ${data.status}
- Synthetic org: ${data.syntheticOrg.name}
- Archetype: ${data.syntheticOrg.archetype}
- Boundary: ${data.simulationBoundary}

## Scenarios

| Result | ID | Domain | Simulation | Evidence |
| --- | --- | --- | --- | --- |
${scenarioRows}

## Operating Envelope

\`\`\`json
${JSON.stringify(data.syntheticOrg.operatingEnvelope, null, 2)}
\`\`\`
`;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
