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
  json: path.join(outputRoot, `human-sim-journey-coverage-${runId}.json`),
  md: path.join(outputRoot, `qa-report-human-sim-journey-coverage-${runId}.md`),
};

const reportSpecs = {
  human: {
    title: "Human Web App Journey",
    file: `human-e2e-${runId}.json`,
  },
  enterprise: {
    title: "Enterprise CAD Organization Journey",
    file: `enterprise-domain-${runId}.json`,
  },
  p7: {
    title: "P7 Role and Failure Journey",
    file: `p7-role-failure-${runId}.json`,
  },
  assembly: {
    title: "Assembly Context Visual Fidelity",
    file: `assembly-visual-fidelity-${runId}.json`,
  },
};

const publicRoutes = [
  "/",
  "/platform",
  "/developers",
  "/api-reference",
  "/docs",
  "/teams",
  "/teams/cost-engineering",
  "/teams/design-engineering",
  "/teams/sourcing",
  "/teams/in-house-manufacturing",
  "/teams/shop-owners",
  "/method",
  "/security",
  "/status",
  "/company",
  "/pilot-report",
  "/privacy",
  "/terms",
  "/dpa",
];

const verifyRailSurfaces = [
  "Home",
  "Verify",
  "Parts",
  "Records",
  "Programs",
  "Your machines",
  "Triage",
  "Calibration & truth",
];

const authenticatedRoutes = [
  "/cost",
  "/analyze",
  "/batch",
  "/cost-decisions",
  "/cost-decisions/compare",
  "/rfq-packages",
  "/integrations",
  "/history",
  "/reconstruct",
  "/label",
  "/design-system",
  "/settings/developer",
  "/notifications",
];

const enterpriseSteps = [
  "enterprise engineer signs up and receives an org",
  "machine inventory rejects an unauthenticated organization",
  "org admin publishes a governed rate card",
  "CAD organization declares owned machines with rates and envelopes",
  "historical actuals ingest but recalibration refuses below floor",
  "Verify UI shows declared machines and governed truth honestly",
  "Developer settings creates and reveals an API key exactly once",
  "CAD engineer verifies a real STEP file in a declared service world",
  "portfolio withholds exposure until declared volume is re-verified at its exact quantity",
  "Verify stage renders declared parent context in product UI",
  "portfolio computes exact server-side exposure after declared-volume re-verification",
  "Programs UI and cost history show the verified enterprise part",
];

const protectedRoutes = [
  "/cost",
  "/cost-decisions",
  "/batch",
  "/history",
  "/integrations",
  "/notifications",
  "/rfq-packages",
  "/settings/developer",
  "/verify",
];

const unauthApiChecks = [
  "GET /api/proxy/admin/users",
  "GET /api/proxy/machine-inventory",
  "GET /api/proxy/cost-decisions?limit=1",
];

const p7FailureBranches = [
  "invalid credentials show a bounded login error",
  "network failure on login renders explicit recovery copy",
  "primary authenticated session is available",
  "unsupported batch upload renders a file-format failure",
  "cost history renders injected API failure",
  "cost-decision governance fixture is saved",
  "cost-decision detail approves and reopens from UI",
  "cost-decision detail shows stale warning after governed rate publish",
  "low-role viewer session is available",
  "low-role admin API is denied",
  "low-role Verify members panel shows gated copy when mounted",
];

const visibleCopyRoutes = [
  "/login",
  "/signup",
  "/cost",
  "/batch",
  "/cost-decisions",
  "/integrations",
  "/notifications",
  "/rfq-packages",
];

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function exactStep(name) {
  return `^${escapeRegExp(name)}$`;
}

function req(id, report, step, persona, surface, branch, options = {}) {
  return {
    id,
    report,
    stepPattern: exactStep(step),
    persona,
    surface,
    branch,
    alternatives: options.alternatives || [],
  };
}

const requirements = [
  ...publicRoutes.map((route) =>
    req(
      `public${route === "/" ? ".home" : route.replaceAll("/", ".")}`,
      "human",
      `public route ${route}`,
      "Public evaluator",
      "Public web",
      `Open ${route} and verify final copy, page signal, console health, and screenshot evidence.`
    )
  ),
  req(
    "auth.verify-redirect",
    "human",
    "unauthenticated /verify redirects to login",
    "Unauthenticated visitor",
    "Auth boundary",
    "Try protected Verify without a session and preserve the login boundary."
  ),
  req(
    "auth.weak-password",
    "human",
    "signup rejects weak password",
    "New user",
    "Signup",
    "Submit an invalid password and verify bounded validation feedback."
  ),
  req(
    "auth.signup-success",
    "human",
    "signup creates real account and lands in app",
    "New user",
    "Signup",
    "Create a real local account and land in authenticated product UI.",
    {
      alternatives: [
        {
          report: "enterprise",
          stepPattern: exactStep("enterprise engineer signs up and receives an org"),
        },
      ],
    }
  ),
  req(
    "verify.shell-authenticated",
    "human",
    "authenticated /verify loads Verify shell",
    "CAD engineer",
    "Verify",
    "Enter the authenticated verification workspace."
  ),
  ...verifyRailSurfaces.map((surface) =>
    req(
      `verify.rail.${surface.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`,
      "human",
      `Verify rail surface: ${surface}`,
      "CAD engineer",
      "Verify rail",
      `Navigate to the ${surface} rail branch and verify mounted UI state.`
    )
  ),
  req(
    "verify.command-palette-triage",
    "human",
    "command palette jumps to Triage",
    "CAD engineer",
    "Verify command palette",
    "Use the command palette path instead of direct rail navigation."
  ),
  req(
    "notifications.panel-derived-state",
    "human",
    "notifications panel opens and derives state",
    "Authenticated user",
    "Notifications",
    "Open notification UI and verify its derived state."
  ),
  ...authenticatedRoutes.map((route) =>
    req(
      `app${route.replaceAll("/", ".")}`,
      "human",
      `authenticated app route ${route}`,
      "Authenticated user",
      "Protected app",
      `Navigate to ${route} as a signed-in user and verify page signal, console health, and screenshot evidence.`
    )
  ),
  req(
    "responsive.public-home-mobile",
    "human",
    "mobile public home loads without non-final copy",
    "Mobile public evaluator",
    "Responsive web",
    "Load the public home surface at mobile width."
  ),
  req(
    "responsive.verify-mobile-auth",
    "human",
    "mobile Verify shell loads authenticated",
    "Mobile CAD engineer",
    "Responsive Verify",
    "Load authenticated Verify at mobile width."
  ),
  req(
    "cad.real-step-upload",
    "human",
    "Verify processes a real STEP file upload",
    "CAD engineer",
    "CAD analysis",
    "Upload and process a real STEP fixture through the browser."
  ),
  req(
    "assembly-context.automotive",
    "assembly",
    "DOOR-HANDLE-ASSEMBLY-FIDELITY-001: part seats into parent assembly within transform tolerance",
    "CAD engineer",
    "Populated assembly context",
    "Render a part inside its parent assembly with declared automotive service environment, then seat it and verify transform/pixel evidence."
  ),
  req(
    "assembly-context.oil-gas",
    "assembly",
    "VALVE-STEM-ASSEMBLY-FIDELITY-001: part seats into parent assembly within transform tolerance",
    "CAD engineer",
    "Populated assembly context",
    "Render a part inside its parent assembly with declared severe-service environment, then seat it and verify transform/pixel evidence."
  ),
  ...enterpriseSteps.map((step, index) =>
    req(
      `enterprise.${String(index + 1).padStart(2, "0")}`,
      "enterprise",
      step,
      "Enterprise CAD organization",
      "Enterprise operating model",
      "Run the enterprise CAD/procurement branch with governed data and organization context."
    )
  ),
  ...protectedRoutes.map((route) =>
    req(
      `p7.unauth${route.replaceAll("/", ".")}`,
      "p7",
      `unauthenticated ${route} does not render protected UI`,
      "Unauthenticated visitor",
      "Role and auth failure",
      `Attempt ${route} without a session and prove protected UI does not leak.`
    )
  ),
  ...unauthApiChecks.map((check) =>
    req(
      `p7.api.${check.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      "p7",
      `unauthenticated API ${check} rejects`,
      "Unauthenticated API caller",
      "API auth failure",
      `Call ${check} through the same-origin proxy without credentials and expect rejection.`
    )
  ),
  ...p7FailureBranches.map((step, index) =>
    req(
      `p7.failure.${String(index + 1).padStart(2, "0")}`,
      "p7",
      step,
      "Failure-path user",
      "Failure and recovery",
      "Drive a non-happy-path branch and verify bounded, production-grade behavior."
    )
  ),
  ...visibleCopyRoutes.map((route) =>
    req(
      `p7.copy${route.replaceAll("/", ".")}`,
      "p7",
      `visible-copy sweep ${route}`,
      "Copy reviewer",
      "Finality sweep",
      `Scan visible copy on ${route} for non-final language.`
    )
  ),
];

function countStatus(steps, status) {
  return steps.filter((step) => step.status === status).length;
}

async function readJson(filename) {
  return JSON.parse(await readFile(filename, "utf8"));
}

async function loadReports() {
  const out = {};
  for (const [key, spec] of Object.entries(reportSpecs)) {
    const filename = path.join(outputRoot, spec.file);
    const data = await readJson(filename);
    const steps = Array.isArray(data.steps) ? data.steps : [];
    out[key] = {
      key,
      title: spec.title,
      filename,
      data,
      steps,
      passed: countStatus(steps, "pass"),
      skipped: countStatus(steps, "skip"),
      failed: countStatus(steps, "fail"),
      issues: Array.isArray(data.issues) ? data.issues.length : Number(data.issues || 0),
      consoleErrors: Array.isArray(data.consoleErrors) ? data.consoleErrors.length : 0,
      requestFailures: Array.isArray(data.requestFailures) ? data.requestFailures.length : 0,
    };
  }
  return out;
}

function reportProblems(reports) {
  const problems = [];
  for (const report of Object.values(reports)) {
    if (report.data.status !== "PASS") {
      problems.push(`${report.title} status is ${report.data.status}, expected PASS`);
    }
    if (report.failed !== 0) {
      problems.push(`${report.title} has ${report.failed} failed step(s)`);
    }
    if (report.skipped !== 0) {
      problems.push(`${report.title} has ${report.skipped} skipped step(s)`);
    }
    if (report.issues !== 0) {
      problems.push(`${report.title} has ${report.issues} issue(s)`);
    }
    if (report.consoleErrors !== 0) {
      problems.push(`${report.title} has ${report.consoleErrors} browser console error(s)`);
    }
    if (report.requestFailures !== 0) {
      problems.push(`${report.title} has ${report.requestFailures} request failure(s)`);
    }
  }
  return problems;
}

function coverageFor(requirement, reports) {
  const candidates = [
    { report: requirement.report, stepPattern: requirement.stepPattern },
    ...(requirement.alternatives || []),
  ];
  const matches = [];
  for (const candidate of candidates) {
    const report = reports[candidate.report];
    if (!report) continue;
    const pattern = new RegExp(candidate.stepPattern);
    for (const step of report.steps) {
      if (step.status === "pass" && pattern.test(step.name)) {
        matches.push({
          report: candidate.report,
          name: step.name,
          url: step.url || "",
          screenshot: step.screenshot || null,
        });
      }
    }
  }
  return {
    ...requirement,
    covered: matches.length > 0,
    matches,
  };
}

function viewerHooksPresent() {
  return Boolean(
    process.env.E2E_VIEWER_STORAGE_STATE ||
      process.env.E2E_VIEWER_SESSION_COOKIE ||
      process.env.E2E_VIEWER_EMAIL
  );
}

function evidenceProblems(reports) {
  const problems = [];
  const p7 = reports.p7?.data;
  if (!p7) return ["P7 report was not loaded"];

  const lowRole = p7.evidence?.lowRoleAuth || {};
  if (!viewerHooksPresent() && lowRole.source !== "self-seeded-invite") {
    problems.push(`P7 low-role session source is ${lowRole.source || "missing"}, expected self-seeded-invite`);
  }
  if (lowRole.org_role !== "viewer") {
    problems.push(`P7 low-role org role is ${lowRole.org_role || "missing"}, expected viewer`);
  }
  const adminStatus = p7.evidence?.lowRoleAdminUsers?.status;
  if (![401, 403].includes(adminStatus)) {
    problems.push(`P7 low-role admin/users status is ${adminStatus || "missing"}, expected 401/403`);
  }
  return problems;
}

function bySurface(rows) {
  const groups = new Map();
  for (const row of rows) {
    if (!groups.has(row.surface)) groups.set(row.surface, []);
    groups.get(row.surface).push(row);
  }
  return [...groups.entries()].map(([surface, items]) => ({
    surface,
    total: items.length,
    covered: items.filter((item) => item.covered).length,
  }));
}

function markdown(data) {
  const reportRows = Object.values(data.reports)
    .map(
      (report) =>
        `| ${report.title} | ${report.status} | ${report.passed} | ${report.skipped} | ${report.failed} | ${report.issues} | ${report.consoleErrors} | ${report.requestFailures} |`
    )
    .join("\n");
  const surfaceRows = data.bySurface
    .map((group) => `| ${group.surface} | ${group.covered}/${group.total} |`)
    .join("\n");
  const missingRows = data.missing.length
    ? data.missing
        .map((item) => `| ${item.id} | ${item.report} | ${item.surface} | ${item.branch} |`)
        .join("\n")
    : "| none |  |  |  |";

  return `# Human-Simulated E2E Journey Coverage

- Date: ${runId}
- Status: ${data.status}
- Required branches: ${data.coveredBranches}/${data.requiredBranches}
- Output root: ${outputRoot}

## Report Gates

| Report | Status | Passed | Skipped | Failed | Issues | Console Errors | Request Failures |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
${reportRows}

## Surface Coverage

| Surface | Covered |
| --- | ---: |
${surfaceRows}

## Missing Branches

| ID | Report | Surface | Branch |
| --- | --- | --- | --- |
${missingRows}

## Problems

${data.problems.length ? data.problems.map((problem) => `- ${problem}`).join("\n") : "No problems found."}
`;
}

async function main() {
  const reports = await loadReports();
  const coverage = requirements.map((requirement) => coverageFor(requirement, reports));
  const missing = coverage.filter((item) => !item.covered);
  const problems = [...reportProblems(reports), ...evidenceProblems(reports)];

  const reportSummaries = Object.fromEntries(
    Object.entries(reports).map(([key, report]) => [
      key,
      {
        title: report.title,
        file: path.relative(repoRoot, report.filename),
        status: report.data.status,
        passed: report.passed,
        skipped: report.skipped,
        failed: report.failed,
        issues: report.issues,
        consoleErrors: report.consoleErrors,
        requestFailures: report.requestFailures,
      },
    ])
  );

  const data = {
    status: missing.length === 0 && problems.length === 0 ? "PASS" : "NEEDS_FIXES",
    generatedAt: new Date().toISOString(),
    runId,
    outputRoot,
    requiredBranches: requirements.length,
    coveredBranches: coverage.filter((item) => item.covered).length,
    reports: reportSummaries,
    bySurface: bySurface(coverage),
    coverage,
    missing,
    problems,
  };

  await mkdir(outputRoot, { recursive: true });
  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));

  console.log(
    JSON.stringify(
      {
        status: data.status,
        requiredBranches: data.requiredBranches,
        coveredBranches: data.coveredBranches,
        reports: reportSummaries,
        missing: missing.map((item) => item.id),
        problems,
        report: artifacts.md,
      },
      null,
      2
    )
  );

  if (data.status !== "PASS") {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
