import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { makeGoldenPathEvidence } from "./golden-path-evidence.mjs";
import {
  CANONICAL_REPORT_CONTRACTS,
  evaluateLocal100,
  LOCAL_100_IDS,
  LOCAL_BROWSER_IDS,
  LOCAL_FAILURE_IDS,
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

function evidence(id, overrides = {}) {
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
    screenshot: `/tmp/${id}.png`,
    consoleErrors: [],
    requestFailures: [],
    assertions: [{ name: "outcome", expected: true, actual: true, pass: true }],
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
        schemaVersion: 1,
        goldenPaths: Object.fromEntries(contract.ids.map((id) => [id, evidence(id)])),
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

test("complete clean current-build evidence earns LOCAL_100", () => {
  const result = evaluateLocal100({
    reports: completeReports(),
    expectedIdentity: identity(),
    expectedRunId: RUN_ID,
    screenshotExists: () => true,
  });
  assert.equal(result.status, "PASS");
  assert.equal(result.claim, "LOCAL_100");
  assert.deepEqual(result.counts, {
    required: 64,
    browser: 54,
    failureRecovery: 10,
    valid: 64,
    problems: 0,
  });
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
    screenshotExists: (screenshot) => !screenshot.endsWith("FAIL-10.png"),
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "dirty_worktree"));
  assert.ok(result.problems.some((problem) => problem.type === "missing_screenshot_file" && problem.id === "FAIL-10"));
});

test("an unrelated or unversioned report cannot enter the release set", () => {
  const reports = completeReports();
  reports[0].data.releaseEvidence.schemaVersion = 2;
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
        schemaVersion: 1,
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
