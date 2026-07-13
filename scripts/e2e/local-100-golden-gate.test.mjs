import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { makeGoldenPathEvidence } from "./golden-path-evidence.mjs";
import {
  evaluateLocal100,
  LOCAL_100_IDS,
  LOCAL_BROWSER_IDS,
  LOCAL_FAILURE_IDS,
} from "./local-100-golden-gate.mjs";

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

function completeReport(overrides = {}) {
  return {
    name: "complete",
    data: {
      status: "PASS",
      buildIdentity: identity(),
      releaseEvidence: {
        schemaVersion: 1,
        goldenPaths: Object.fromEntries(LOCAL_100_IDS.map((id) => [id, evidence(id)])),
      },
      ...overrides,
    },
  };
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
    reports: [completeReport()],
    expectedIdentity: identity(),
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
  const report = completeReport({ steps: [{ name: "AUTH-07", status: "PASS" }] });
  delete report.data.releaseEvidence.goldenPaths["AUTH-07"];
  const result = evaluateLocal100({
    reports: [report],
    expectedIdentity: identity(),
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.equal(result.claim, null);
  assert.ok(result.problems.some((problem) => problem.type === "missing_golden_path" && problem.id === "AUTH-07"));
});

test("failing duplicate evidence cannot be hidden behind a passing report", () => {
  const passing = completeReport();
  const failing = {
    name: "duplicate",
    data: {
      status: "PASS",
      buildIdentity: identity(),
      releaseEvidence: {
        schemaVersion: 1,
        goldenPaths: {
          "ROLE-04": evidence("ROLE-04", { status: "FAIL" }),
        },
      },
    },
  };
  const result = evaluateLocal100({
    reports: [passing, failing],
    expectedIdentity: identity(),
    screenshotExists: () => true,
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "invalid_golden_path" && problem.id === "ROLE-04"));
});

test("missing screenshot bytes and dirty HEAD both block the claim", () => {
  const report = completeReport();
  report.data.buildIdentity.gitDirty = true;
  const result = evaluateLocal100({
    reports: [report],
    expectedIdentity: identity({ gitDirty: true }),
    screenshotExists: (screenshot) => !screenshot.endsWith("FAIL-10.png"),
  });
  assert.equal(result.status, "FAIL");
  assert.ok(result.problems.some((problem) => problem.type === "dirty_worktree"));
  assert.ok(result.problems.some((problem) => problem.type === "missing_screenshot_file" && problem.id === "FAIL-10"));
});
