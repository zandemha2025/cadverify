import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  captureBuildIdentity,
  validateBuildIdentities,
} from "./human-sim-release-evidence.mjs";
import {
  validateGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";

export const LOCAL_BROWSER_IDS = [
  "PUB-01", "PUB-02", "PUB-03", "PUB-04",
  "AUTH-01", "AUTH-02", "AUTH-03", "AUTH-04", "AUTH-05", "AUTH-07", "AUTH-08",
  "VER-01", "VER-02", "VER-03", "VER-04", "VER-05", "VER-06", "VER-07", "VER-08", "VER-09",
  "DES-01", "DES-02", "DES-03", "DES-04", "DES-05", "DES-06", "DES-07", "DES-08", "DES-09", "DES-10", "DES-11", "DES-12", "DES-13",
  "WORK-01", "WORK-02", "WORK-03", "WORK-04", "WORK-05", "WORK-06", "WORK-07", "WORK-08", "WORK-09", "WORK-10", "WORK-11", "WORK-12",
  "ENT-01", "ENT-02", "ENT-03", "ENT-04", "ENT-05",
  "ROLE-01", "ROLE-02", "ROLE-03", "ROLE-04",
];

export const LOCAL_FAILURE_IDS = [
  "FAIL-01", "FAIL-02", "FAIL-03", "FAIL-04", "FAIL-05",
  "FAIL-06", "FAIL-07", "FAIL-08", "FAIL-09", "FAIL-10",
];

export const LOCAL_100_IDS = [...LOCAL_BROWSER_IDS, ...LOCAL_FAILURE_IDS];

export const CANONICAL_REPORT_CONTRACTS = Object.freeze([
  { suite: "public-auth-verify-golden-matrix", ids: [
    "PUB-01", "PUB-02", "PUB-03", "PUB-04",
    "AUTH-01", "AUTH-02", "AUTH-03", "AUTH-04", "AUTH-05",
    "VER-01", "VER-02", "VER-03",
  ] },
  { suite: "auth-role-lifecycle-golden-matrix", ids: ["AUTH-07", "AUTH-08", "ROLE-01"] },
  { suite: "manufacturing-cad-adversarial", ids: ["ENT-01", "VER-05", "WORK-01", "WORK-02", "FAIL-01", "FAIL-02"] },
  { suite: "notification-decision-golden-matrix", ids: ["VER-04", "VER-07", "WORK-05", "WORK-07", "ROLE-04", "FAIL-09"] },
  { suite: "role-tenant-boundary-matrix", ids: ["ROLE-02", "ROLE-03", "ROLE-04", "VER-04", "FAIL-09"] },
  { suite: "compare-rfq-key-golden-matrix", ids: ["WORK-06", "WORK-08", "WORK-12"] },
  { suite: "batch-design-recovery-golden-matrix", ids: ["WORK-03", "WORK-04", "FAIL-04", "FAIL-05", "FAIL-06", "FAIL-07"] },
  { suite: "design-studio-human-e2e", ids: [
    "DES-01", "DES-02", "DES-03", "DES-04", "DES-05", "DES-06",
    "DES-07", "DES-08", "DES-09", "DES-10", "DES-11", "DES-12",
  ] },
  { suite: "enterprise-domain-runner", ids: [
    "VER-06", "VER-08", "WORK-09", "WORK-10", "WORK-11",
    "ENT-02", "ENT-03", "ENT-04", "ENT-05",
  ] },
  { suite: "mobile-recovery-e2e", ids: ["DES-13", "VER-09", "FAIL-01", "FAIL-03", "FAIL-08", "FAIL-09", "FAIL-10"] },
]);

const CONTRACT_BY_SUITE = new Map(CANONICAL_REPORT_CONTRACTS.map((contract) => [contract.suite, contract]));
const MAX_REPORT_AGE_MS = 24 * 60 * 60 * 1000;

function issue(type, details = {}) {
  return { type, ...details };
}

function reportName(report, index) {
  return report.name || report.path || `report-${index + 1}`;
}

/**
 * Evaluate reports produced by real-browser matrices. Every included report is
 * part of the claim: a failing duplicate cannot be hidden behind a passing one.
 */
export function evaluateLocal100({
  reports,
  expectedIdentity,
  expectedRunId,
  screenshotExists = existsSync,
}) {
  const problems = [];
  const candidates = new Map(LOCAL_100_IDS.map((id) => [id, []]));
  const namedReports = {};
  const observedSuites = new Set();
  const gateTime = Date.parse(expectedIdentity?.capturedAt);

  if (reports.length !== CANONICAL_REPORT_CONTRACTS.length) {
    problems.push(issue("invalid_report_count", {
      expected: CANONICAL_REPORT_CONTRACTS.length,
      actual: reports.length,
    }));
  }
  if (typeof expectedRunId !== "string" || expectedRunId.trim() === "") {
    problems.push(issue("missing_expected_run_id", { field: "expectedRunId" }));
  }

  reports.forEach((report, index) => {
    const suppliedName = reportName(report, index);
    const suite = report.data?.suite;
    const contract = CONTRACT_BY_SUITE.get(suite);
    const name = typeof suite === "string" && suite ? suite : suppliedName;
    if (!contract) {
      problems.push(issue("unexpected_report_suite", {
        report: suppliedName,
        expected: CANONICAL_REPORT_CONTRACTS.map((item) => item.suite),
        actual: suite ?? null,
      }));
      return;
    }
    if (observedSuites.has(suite)) {
      problems.push(issue("duplicate_report_suite", { report: suppliedName, suite }));
      return;
    }
    observedSuites.add(suite);
    if (namedReports[name]) {
      problems.push(issue("duplicate_report_name", { report: name }));
      return;
    }
    namedReports[name] = { data: report.data };

    if (report.data?.runId !== expectedRunId) {
      problems.push(issue("run_id_mismatch", {
        report: name,
        expected: expectedRunId,
        actual: report.data?.runId ?? null,
      }));
    }
    const generatedAt = Date.parse(report.data?.generatedAt);
    if (!Number.isFinite(generatedAt)) {
      problems.push(issue("invalid_generated_at", { report: name, actual: report.data?.generatedAt ?? null }));
    } else if (Number.isFinite(gateTime) && (generatedAt > gateTime + 5 * 60 * 1000 || gateTime - generatedAt > MAX_REPORT_AGE_MS)) {
      problems.push(issue("stale_report", {
        report: name,
        generatedAt: report.data.generatedAt,
        gateCapturedAt: expectedIdentity.capturedAt,
        maximumAgeMs: MAX_REPORT_AGE_MS,
      }));
    }

    if (report.data?.status !== "PASS") {
      problems.push(issue("report_not_pass", {
        report: name,
        expected: "PASS",
        actual: report.data?.status ?? null,
      }));
    }

    if (report.data?.releaseEvidence?.schemaVersion !== 1) {
      problems.push(issue("invalid_release_evidence_schema", {
        report: name,
        expected: 1,
        actual: report.data?.releaseEvidence?.schemaVersion ?? null,
      }));
    }

    const goldenPaths = report.data?.releaseEvidence?.goldenPaths;
    if (!goldenPaths || typeof goldenPaths !== "object" || Array.isArray(goldenPaths)) {
      problems.push(issue("missing_golden_paths", {
        report: name,
        field: "releaseEvidence.goldenPaths",
      }));
      return;
    }

    const actualIds = Object.keys(goldenPaths).sort();
    const expectedIds = [...contract.ids].sort();
    if (JSON.stringify(actualIds) !== JSON.stringify(expectedIds)) {
      problems.push(issue("suite_path_ownership_mismatch", {
        report: name,
        expected: expectedIds,
        actual: actualIds,
        missing: expectedIds.filter((id) => !actualIds.includes(id)),
        unexpected: actualIds.filter((id) => !expectedIds.includes(id)),
      }));
    }

    for (const [id, evidence] of Object.entries(goldenPaths)) {
      if (!contract.ids.includes(id) || !candidates.has(id)) continue;
      candidates.get(id).push({ name, evidence });
    }
  });

  for (const contract of CANONICAL_REPORT_CONTRACTS) {
    if (!observedSuites.has(contract.suite)) {
      problems.push(issue("missing_report_suite", { suite: contract.suite }));
    }
  }

  problems.push(...validateBuildIdentities(namedReports, expectedIdentity));

  const merged = {};
  const sources = {};
  for (const id of LOCAL_100_IDS) {
    const entries = candidates.get(id);
    if (entries.length === 0) {
      problems.push(issue("missing_golden_path", { id }));
      continue;
    }

    sources[id] = entries.map(({ name }) => name);
    let firstValid = null;
    for (const { name, evidence } of entries) {
      const validation = validateGoldenPathEvidence(id, evidence);
      if (!validation.valid) {
        for (const failure of validation.failures) {
          problems.push(issue("invalid_golden_path", {
            id,
            report: name,
            field: failure.field,
            expected: failure.expected,
            actual: failure.actual ?? null,
          }));
        }
        continue;
      }
      if (!screenshotExists(evidence.screenshot)) {
        problems.push(issue("missing_screenshot_file", {
          id,
          report: name,
          screenshot: evidence.screenshot,
        }));
        continue;
      }
      firstValid ||= evidence;
    }
    if (firstValid) merged[id] = firstValid;
  }

  const validation = validateGoldenPathMap(LOCAL_100_IDS, merged);
  const status = problems.length === 0 && validation.valid === LOCAL_100_IDS.length
    ? "PASS"
    : "FAIL";

  return {
    schemaVersion: 1,
    status,
    claim: status === "PASS" ? "LOCAL_100" : null,
    buildIdentity: expectedIdentity,
    counts: {
      required: LOCAL_100_IDS.length,
      browser: LOCAL_BROWSER_IDS.length,
      failureRecovery: LOCAL_FAILURE_IDS.length,
      valid: validation.valid,
      problems: problems.length,
    },
    sources,
    validation,
    problems,
  };
}

function parseArguments(argv) {
  const reportPaths = [];
  let outputPath = null;
  let runId = null;
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--output") {
      outputPath = argv[index + 1];
      index += 1;
    } else if (token === "--run-id") {
      runId = argv[index + 1];
      index += 1;
    } else {
      reportPaths.push(token);
    }
  }
  return { reportPaths, outputPath, runId };
}

function main() {
  const scriptPath = fileURLToPath(import.meta.url);
  const repoRoot = path.resolve(path.dirname(scriptPath), "../..");
  const { reportPaths, outputPath, runId } = parseArguments(process.argv.slice(2));
  if (reportPaths.length === 0) {
    throw new Error(
      "Pass the explicit current-build JSON reports to the LOCAL_100 gate; automatic stale-report discovery is intentionally disabled."
    );
  }
  if (!runId) {
    throw new Error("Pass --run-id with the one shared identifier used by all ten canonical suites.");
  }

  const reports = reportPaths.map((reportPath, index) => ({
    name: `${index + 1}:${path.basename(reportPath)}`,
    path: path.resolve(reportPath),
    data: JSON.parse(readFileSync(path.resolve(reportPath), "utf8")),
  }));
  const result = evaluateLocal100({
    reports,
    expectedIdentity: captureBuildIdentity(repoRoot),
    expectedRunId: runId,
  });

  if (outputPath) {
    const absoluteOutput = path.resolve(outputPath);
    mkdirSync(path.dirname(absoluteOutput), { recursive: true });
    writeFileSync(absoluteOutput, `${JSON.stringify(result, null, 2)}\n`);
  }
  process.stdout.write(`${JSON.stringify({
    status: result.status,
    claim: result.claim,
    counts: result.counts,
    output: outputPath ? path.resolve(outputPath) : null,
  }, null, 2)}\n`);
  if (result.status !== "PASS") process.exitCode = 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
