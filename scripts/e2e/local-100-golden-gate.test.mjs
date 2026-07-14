import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  makeGoldenPathEvidence,
  REQUIRED_VISUAL_STAGE_FORBIDDEN_TEXT,
  REQUIRED_VISUAL_STAGE_TEXT,
  REQUIRED_VISUAL_STAGES,
  TERMINAL_FORBIDDEN_VISIBLE,
} from "./golden-path-evidence.mjs";
import {
  CANONICAL_REPORT_CONTRACTS,
  evaluateLocal100,
  LOCAL_100_IDS,
  LOCAL_BROWSER_IDS,
  LOCAL_FAILURE_IDS,
  REQUIRED_SCREENSHOT_ORACLES,
} from "./local-100-golden-gate.mjs";

const RUN_ID = "release-2026-07-13T12-00-00Z";

function identity(overrides = {}) {
  return {
    schemaVersion: 1,
    gitHead: "1".repeat(40),
    buildId: "1".repeat(40),
    buildIdSource: "git-head-fallback",
    gitDirty: false,
    capturedAt: "2026-07-13T12:00:00.000Z",
    ...overrides,
  };
}

function evidence(id, overrides = {}, namespace = "fixture") {
  const requiredStages = REQUIRED_VISUAL_STAGES[id] ?? [];
  const visualSteps = requiredStages.map((stage) => ({
    id,
    stage,
    terminal: true,
    screenshot: `/tmp/${namespace}-${id}-${stage}.png`,
    capturedAt: "2026-07-13T12:00:00.000Z",
    url: "http://localhost:3000/verify",
    requiredVisible: REQUIRED_VISUAL_STAGE_TEXT[id]?.[stage] ?? ["Expected state is visible"],
    forbiddenVisible: [
      ...TERMINAL_FORBIDDEN_VISIBLE,
      ...(REQUIRED_VISUAL_STAGE_FORBIDDEN_TEXT[id]?.[stage] ?? []),
    ],
    capture: {
      text: (REQUIRED_VISUAL_STAGE_TEXT[id]?.[stage] ?? ["Expected state is visible"]).join(" "),
      ariaBusyCount: 0,
      skeletonCount: 0,
      loadingIndicatorCount: 0,
    },
  }));
  const screenshot = requiredStages.length > 0
    ? visualSteps.at(-1).screenshot
    : `/tmp/${namespace}-${id}.png`;
  return makeGoldenPathEvidence({
    id,
    status: "PASS",
    persona: `Persona for ${id}`,
    preconditions: ["Fresh isolated organization"],
    actions: ["Complete the exact browser path"],
    observed: {
      url: "http://localhost:3000/verify",
      visible: ["Expected state is visible"],
      persisted: { id: `${id}-record` },
      numeric: { exact: 1 },
      authorization: "Expected role boundary observed",
      recovery: "Returned to a usable state",
    },
    screenshot,
    ...(visualSteps.length > 0 ? { visualSteps } : {}),
    consoleErrors: [],
    requestFailures: [],
    assertions: [
      { name: "outcome", expected: true, actual: true, pass: true },
      ...(REQUIRED_SCREENSHOT_ORACLES[id]
        ? [{ name: REQUIRED_SCREENSHOT_ORACLES[id], expected: "terminal UI", actual: "terminal UI", pass: true }]
        : []),
    ],
    ...overrides,
  });
}

function completeReports() {
  return CANONICAL_REPORT_CONTRACTS.map((contract) => ({
    name: contract.suite,
    data: {
      status: "PASS",
      suite: contract.suite,
      runId: RUN_ID,
      generatedAt: "2026-07-13T12:00:00.000Z",
      buildIdentity: identity(),
      releaseEvidence: {
        schemaVersion: 2,
        goldenPaths: Object.fromEntries(contract.ids.map((id) => [id, evidence(id, {}, contract.suite)])),
      },
    },
  }));
}

test("inventory contains 54 browser and 10 recovery paths", () => {
  assert.equal(LOCAL_BROWSER_IDS.length, 54);
  assert.equal(LOCAL_FAILURE_IDS.length, 10);
  assert.equal(LOCAL_100_IDS.length, 64);
  assert.equal(new Set(LOCAL_100_IDS).size, 64);
});

test("release orchestration requires the production auth, async, worker, and governed-rate posture", () => {
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const source = readFileSync(path.join(repoRoot, "scripts/e2e/local-100-release.mjs"), "utf8");
  for (const required of [
    '["PRODUCTION_AUTH_PROXY_REQUIRED", "1"]',
    '["WORKER_STRICT_HEALTH", "1"]',
    '["ASYNC_STRICT_HEALTH", "1"]',
    '["RATE_LIBRARY_ENABLED", "1"]',
  ]) {
    assert.match(source, new RegExp(required.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("gate inventory exactly matches the documented local contract", () => {
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const contract = readFileSync(path.join(repoRoot, "docs/HUMAN_SIMULATION_GOLDEN_PATHS.md"), "utf8");
  const documentedBrowserIds = [...contract.matchAll(/^\| ([A-Z]+-\d+) \|.*\| browser \|$/gm)]
    .map((match) => match[1]);
  const documentedFailureIds = [...contract.matchAll(/^\| (FAIL-\d+) \|/gm)]
    .map((match) => match[1]);

  assert.deepEqual([...LOCAL_BROWSER_IDS].sort(), documentedBrowserIds.sort());
  assert.deepEqual([...LOCAL_FAILURE_IDS].sort(), documentedFailureIds.sort());
});

test("complete clean current-build evidence earns the bounded local gate claim", () => {
  const result = evaluateLocal100({
    reports: completeReports(),
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "PASS");
  assert.equal(result.claim, "LOCAL_GATE_PASS");
  assert.deepEqual(result.counts, {
    required: 64,
    browser: 54,
    failureRecovery: 10,
    valid: 64,
    problems: 0,
  });
});

test("a critical screenshot without its same-moment DOM oracle blocks the gate", () => {
  const reports = completeReports();
  const report = reports.find((item) => item.data.suite === "manufacturing-cad-adversarial");
  report.data.releaseEvidence.goldenPaths["VER-05"].assertions = [
    { name: "API result", expected: 200, actual: 200, pass: true },
  ];
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) =>
    problem.type === "missing_screenshot_oracle" && problem.id === "VER-05"
  ));
});

test("a required v2 path cannot fall back to one legacy screenshot", () => {
  const reports = completeReports();
  const report = reports.find((item) => item.data.suite === "public-auth-verify-golden-matrix");
  const current = report.data.releaseEvidence.goldenPaths["AUTH-03"];
  report.data.releaseEvidence.goldenPaths["AUTH-03"] = makeGoldenPathEvidence({
    ...current,
    screenshot: "/tmp/public-auth-AUTH-03.png",
    visualSteps: undefined,
  });
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) =>
    problem.type === "invalid_golden_path" && problem.id === "AUTH-03" && problem.field === "visualProof"
  ));
  assert.ok(result.problems.some((problem) =>
    problem.type === "invalid_golden_path" && problem.id === "AUTH-03" && problem.field === "visualSteps"
  ));
});

test("missing one required failure/recovery stage blocks the gate", () => {
  const reports = completeReports();
  const report = reports.find((item) => item.data.suite === "mobile-recovery-e2e");
  const entry = report.data.releaseEvidence.goldenPaths["FAIL-03"];
  entry.visualSteps = entry.visualSteps.filter((step) => step.stage !== "failure");
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) =>
    problem.type === "invalid_golden_path" && problem.id === "FAIL-03" && problem.field === "visualSteps.required.failure"
  ));
});

test("terminal COMPUTING and visible busy placeholders block the gate", () => {
  const reports = completeReports();
  const report = reports.find((item) => item.data.suite === "manufacturing-cad-adversarial");
  const step = report.data.releaseEvidence.goldenPaths["VER-05"].visualSteps[0];
  step.capture.text = "Expected state is visible THE VERDICT COMPUTING";
  step.capture.skeletonCount = 1;
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) =>
    problem.type === "invalid_golden_path" && problem.id === "VER-05" && problem.field.includes("terminal")
  ));
});

test("every v2 stage screenshot must exist", () => {
  const reports = completeReports();
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: (screenshot) => !screenshot.endsWith("FAIL-03-failure.png"),
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) =>
    problem.type === "missing_screenshot_file" && problem.id === "FAIL-03" && problem.stage === "failure"
  ));
});

test("screenshot paths must be unique across reports and associated with their path ID", () => {
  const reports = completeReports();
  const notification = reports.find((item) => item.data.suite === "notification-decision-golden-matrix");
  const boundary = reports.find((item) => item.data.suite === "role-tenant-boundary-matrix");
  notification.data.releaseEvidence.goldenPaths["ROLE-04"].screenshot = "/tmp/shared-ROLE-04.png";
  boundary.data.releaseEvidence.goldenPaths["ROLE-04"].screenshot = "/tmp/shared-ROLE-04.png";
  reports[0].data.releaseEvidence.goldenPaths["AUTH-02"].screenshot = "/tmp/wrong-AUTH-05.png";
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "duplicate_screenshot_path"));
  assert.ok(result.problems.some((problem) =>
    problem.type === "screenshot_id_mismatch" && problem.id === "AUTH-02"
  ));
});

test("a passing step name cannot replace a missing structured path", () => {
  const reports = completeReports();
  const report = reports.find((item) => item.data.suite === "auth-role-lifecycle-golden-matrix");
  report.data.steps = [{ name: "AUTH-07", status: "PASS" }];
  delete report.data.releaseEvidence.goldenPaths["AUTH-07"];
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.equal(result.claim, null);
  assert.ok(result.problems.some((problem) => problem.type === "missing_golden_path" && problem.id === "AUTH-07"));
});

test("failing duplicate evidence cannot be hidden behind a passing report", () => {
  const reports = completeReports();
  const roleReport = reports.find((item) => item.data.suite === "role-tenant-boundary-matrix");
  roleReport.data.releaseEvidence.goldenPaths["ROLE-04"] = evidence("ROLE-04", { status: "FAIL" });
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "invalid_golden_path" && problem.id === "ROLE-04"));
});

test("missing screenshot bytes and dirty HEAD both block the claim", () => {
  const reports = completeReports();
  for (const report of reports) report.data.buildIdentity.gitDirty = true;
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity({ gitDirty: true }),
    expectedRunId: RUN_ID,
    screenshotExists: (screenshot) => !screenshot.endsWith("FAIL-10-recovery.png"),
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "dirty_worktree"));
  assert.ok(result.problems.some((problem) => problem.type === "missing_screenshot_file" && problem.id === "FAIL-10"));
});

test("an unrelated or unversioned report cannot enter the release set", () => {
  const reports = completeReports();
  reports[0].data.releaseEvidence.schemaVersion = 3;
  const unrelated = {
    name: "unrelated",
    data: {
      status: "PASS",
      suite: "synthetic-all-paths",
      runId: RUN_ID,
      generatedAt: "2026-07-13T12:00:00.000Z",
      buildIdentity: identity(),
      releaseEvidence: { schemaVersion: 1, goldenPaths: { "EXTERNAL-01": evidence("EXTERNAL-01") } },
    },
  };
  const result = evaluateLocal100({
    reports: [...reports, unrelated],
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "invalid_release_evidence_schema"));
  assert.ok(result.problems.some((problem) => problem.type === "unexpected_report_suite"));
});

test("one generic report containing all 64 IDs cannot impersonate the canonical suites", () => {
  const synthetic = {
    name: "synthetic-complete",
    data: {
      status: "PASS",
      suite: "public-auth-verify-golden-matrix",
      runId: RUN_ID,
      generatedAt: "2026-07-13T12:00:00.000Z",
      buildIdentity: identity(),
      releaseEvidence: {
        schemaVersion: 2,
        goldenPaths: Object.fromEntries(LOCAL_100_IDS.map((id) => [id, evidence(id)])),
      },
    },
  };
  const result = evaluateLocal100({
    reports: [synthetic],
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "invalid_report_count"));
  assert.ok(result.problems.some((problem) => problem.type === "suite_path_ownership_mismatch"));
  assert.ok(result.problems.some((problem) => problem.type === "missing_report_suite"));
});

test("foreign path ownership and mismatched run IDs block certification", () => {
  const reports = completeReports();
  reports[0].data.releaseEvidence.goldenPaths["AUTH-07"] = evidence("AUTH-07");
  reports[1].data.runId = "different-run";
  const result = evaluateLocal100({
    reports,
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "suite_path_ownership_mismatch"));
  assert.ok(result.problems.some((problem) => problem.type === "run_id_mismatch"));
});
