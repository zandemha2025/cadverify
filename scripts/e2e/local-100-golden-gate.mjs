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
  screenshotExists = existsSync,
}) {
  const problems = [];
  const candidates = new Map(LOCAL_100_IDS.map((id) => [id, []]));
  const namedReports = {};

  reports.forEach((report, index) => {
    const name = reportName(report, index);
    if (namedReports[name]) {
      problems.push(issue("duplicate_report_name", { report: name }));
      return;
    }
    namedReports[name] = { data: report.data };

    if (report.data?.status !== "PASS") {
      problems.push(issue("report_not_pass", {
        report: name,
        expected: "PASS",
        actual: report.data?.status ?? null,
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

    for (const [id, evidence] of Object.entries(goldenPaths)) {
      if (!candidates.has(id)) continue;
      candidates.get(id).push({ name, evidence });
    }
  });

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
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--output") {
      outputPath = argv[index + 1];
      index += 1;
    } else {
      reportPaths.push(token);
    }
  }
  return { reportPaths, outputPath };
}

function main() {
  const scriptPath = fileURLToPath(import.meta.url);
  const repoRoot = path.resolve(path.dirname(scriptPath), "../..");
  const { reportPaths, outputPath } = parseArguments(process.argv.slice(2));
  if (reportPaths.length === 0) {
    throw new Error(
      "Pass the explicit current-build JSON reports to the LOCAL_100 gate; automatic stale-report discovery is intentionally disabled."
    );
  }

  const reports = reportPaths.map((reportPath, index) => ({
    name: `${index + 1}:${path.basename(reportPath)}`,
    path: path.resolve(reportPath),
    data: JSON.parse(readFileSync(path.resolve(reportPath), "utf8")),
  }));
  const result = evaluateLocal100({
    reports,
    expectedIdentity: captureBuildIdentity(repoRoot),
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

