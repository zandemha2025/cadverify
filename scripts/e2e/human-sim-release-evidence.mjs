import { execFileSync } from "node:child_process";

export const BUILD_IDENTITY_SCHEMA_VERSION = 1;
export const RELEASE_EVIDENCE_SCHEMA_VERSION = 1;

const BUILD_ID_ENV_KEYS = [
  "E2E_BUILD_ID",
  "PROOFSHAPE_BUILD_ID",
  "VERCEL_GIT_COMMIT_SHA",
  "GITHUB_SHA",
  "CI_COMMIT_SHA",
  "NEXT_PUBLIC_BUILD_SHA",
];

const CUBE_SHA256 = "76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a";

function gitHead(repoRoot) {
  return execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  }).trim();
}

function gitDirty(repoRoot) {
  return execFileSync("git", ["status", "--porcelain", "--untracked-files=normal"], {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  }).trim().length > 0;
}

export function captureBuildIdentity(repoRoot, env = process.env) {
  const currentGitHead = gitHead(repoRoot);
  const buildIdKey = BUILD_ID_ENV_KEYS.find((key) => String(env[key] || "").trim());
  const buildId = buildIdKey ? String(env[buildIdKey]).trim() : currentGitHead;
  return {
    schemaVersion: BUILD_IDENTITY_SCHEMA_VERSION,
    gitHead: currentGitHead,
    buildId,
    buildIdSource: buildIdKey || "git-head-fallback",
    gitDirty: gitDirty(repoRoot),
    capturedAt: new Date().toISOString(),
  };
}

export function makeReleaseEvidence(criticalPaths) {
  return {
    schemaVersion: RELEASE_EVIDENCE_SCHEMA_VERSION,
    criticalPaths,
  };
}

function missing(value) {
  return value === undefined || value === null || value === "";
}

function valueAt(root, field) {
  return field.split(".").reduce((value, key) => value?.[key], root);
}

function sameNumber(actual, expected, tolerance = 0) {
  return typeof actual === "number" && Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance;
}

function sameVector(actual, expected, tolerance = 0) {
  return (
    Array.isArray(actual) &&
    actual.length === expected.length &&
    actual.every((value, index) => sameNumber(value, expected[index], tolerance))
  );
}

function nonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function sha256(value) {
  return typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
}

function screenshot(value) {
  return typeof value === "string" && /\.png$/i.test(value);
}

function machineRates(value) {
  if (!Array.isArray(value)) return false;
  const expected = new Map([
    ["mjf", 48],
    ["cnc_3axis", 95],
    ["cnc_5axis", 142],
    ["dmls", 185],
  ]);
  return [...expected].every(([process, rate]) =>
    value.some((machine) => machine?.process === process && sameNumber(machine?.rate, rate))
  );
}

const definitions = [
  {
    id: "PUB-03",
    report: "human",
    fields: [
      ["releaseEvidence.criticalPaths.PUB-03.receiptId", (value) => /^CV-[A-Za-z0-9-]{12,}$/.test(value), "durable CV-* receipt id"],
      ["releaseEvidence.criticalPaths.PUB-03.acknowledged", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.PUB-03.responseStatus", (value) => value === 200, "HTTP 200"],
      ["releaseEvidence.criticalPaths.PUB-03.responseReceiptMatches", (value) => value === true, "response receipt equals visible receipt"],
      ["releaseEvidence.criticalPaths.PUB-03.screenshot", screenshot, "PNG screenshot path"],
    ],
  },
  {
    id: "VER-05",
    report: "human",
    fields: [
      ["releaseEvidence.criticalPaths.VER-05.fixtureSha256", (value) => value === CUBE_SHA256, CUBE_SHA256],
      ["releaseEvidence.criticalPaths.VER-05.boundingBoxMm", (value) => sameVector(value, [20, 15, 10], 0.1), "20 × 15 × 10 mm ±0.1"],
      ["releaseEvidence.criticalPaths.VER-05.volumeMm3", (value) => sameNumber(value, 2717.3, 1), "2717.3 mm³ ±1"],
      ["releaseEvidence.criticalPaths.VER-05.surfaceAreaMm2", (value) => sameNumber(value, 1432, 2), "1432 mm² ±2"],
      ["releaseEvidence.criticalPaths.VER-05.watertight", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.VER-05.decisionId", nonEmptyString, "persisted cost-decision id"],
      ["releaseEvidence.criticalPaths.VER-05.validationStatus", (value) => value === 200, "POST /validate HTTP 200"],
      ["releaseEvidence.criticalPaths.VER-05.costStatus", (value) => value === 200, "POST /validate/cost HTTP 200"],
      ["releaseEvidence.criticalPaths.VER-05.screenshot", screenshot, "PNG screenshot path"],
    ],
  },
  {
    id: "DES-05",
    report: "design",
    fields: [
      ["releaseEvidence.criticalPaths.DES-05.artifactSha256", sha256, "64-character SHA-256"],
      ["releaseEvidence.criticalPaths.DES-05.responseHeaderSha256", sha256, "64-character response-header SHA-256"],
      ["releaseEvidence.criticalPaths.DES-05.hashesMatch", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.DES-05", (value) => value?.artifactSha256 === value?.responseHeaderSha256, "artifact SHA equals response-header SHA"],
      ["releaseEvidence.criticalPaths.DES-05.envelopeMm", (value) => sameVector(value, [120, 70, 8]), "120 × 70 × 8 mm"],
      ["releaseEvidence.criticalPaths.DES-05.uiVolumeCm3", (value) => sameNumber(value, 64.69, 0.01), "64.69 cm³ ±0.01"],
      ["releaseEvidence.criticalPaths.DES-05.previewMode", (value) => ["interactive", "explicit-fallback"].includes(value), "interactive or explicit-fallback"],
      ["releaseEvidence.criticalPaths.DES-05.screenshot", screenshot, "PNG screenshot path"],
    ],
  },
  {
    id: "DES-10",
    report: "design",
    fields: [
      ["releaseEvidence.criticalPaths.DES-10.r1Sha256", sha256, "64-character R1 SHA-256"],
      ["releaseEvidence.criticalPaths.DES-10.r2Sha256", sha256, "64-character R2 SHA-256"],
      ["releaseEvidence.criticalPaths.DES-10.hashesDiffer", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.DES-10", (value) => value?.r1Sha256 !== value?.r2Sha256, "R1 SHA differs from R2 SHA"],
      ["releaseEvidence.criticalPaths.DES-10.r1RoundTripExact", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.DES-10.r2EnvelopeMm", (value) => sameVector(value, [130, 70, 8]), "130 × 70 × 8 mm"],
      ["releaseEvidence.criticalPaths.DES-10.r2UiVolumeCm3", (value) => sameNumber(value, 70.29, 0.01), "70.29 cm³ ±0.01"],
    ],
  },
  {
    id: "DES-11",
    report: "design",
    fields: [
      ["releaseEvidence.criticalPaths.DES-11.revision", (value) => value === 1, "revision 1"],
      ["releaseEvidence.criticalPaths.DES-11.queryRevision", (value) => value === "1", "query revision=1"],
      ["releaseEvidence.criticalPaths.DES-11.artifactSha256", sha256, "R1 artifact SHA-256"],
      ["releaseEvidence.criticalPaths.DES-11.envelopeMm", (value) => sameVector(value, [120, 70, 8]), "120 × 70 × 8 mm"],
      ["releaseEvidence.criticalPaths.DES-11.uiVolumeCm3", (value) => sameNumber(value, 64.69, 0.01), "64.69 cm³ ±0.01"],
      ["releaseEvidence.criticalPaths.DES-11.watertight", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.DES-11.shouldCostComputed", (value) => value === true, "true"],
    ],
  },
  {
    id: "ENT-01",
    report: "enterprise",
    fields: [
      ["releaseEvidence.criticalPaths.ENT-01.rateCardSource", (value) => value === "governed_rate_card", "governed_rate_card"],
      ["releaseEvidence.criticalPaths.ENT-01.validated", (value) => value === false, "false"],
      ["releaseEvidence.criticalPaths.ENT-01.machineRates", machineRates, "MJF 48, CNC 3-axis 95, CNC 5-axis 142, DMLS 185 USD/hr"],
    ],
  },
  {
    id: "ENT-02",
    report: "enterprise",
    fields: [
      ["releaseEvidence.criticalPaths.ENT-02.total", (value) => value === 4, "4 real actuals"],
      ["releaseEvidence.criticalPaths.ENT-02.nReal", (value) => value === 4, "n_real=4"],
      ["releaseEvidence.criticalPaths.ENT-02.minimumReal", (value) => value === 8, "minimum real floor=8"],
      ["releaseEvidence.criticalPaths.ENT-02.recalibrationRefused", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.ENT-02.sourceBoundImported", (value) => value === 8, "8 source-bound actuals"],
      ["releaseEvidence.criticalPaths.ENT-02.sourceBoundImportSkipped", (value) => value === 0, "0 import skips"],
      ["releaseEvidence.criticalPaths.ENT-02.sourceSha256", sha256, "source artifact SHA-256"],
      ["releaseEvidence.criticalPaths.ENT-02.calibrationValidated", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.ENT-02.calibrationFromReal", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.ENT-02.heldoutReal", (value) => typeof value === "number" && value >= 3, ">= 3 costable held-out residuals"],
      ["releaseEvidence.criticalPaths.ENT-02.sourceBoundSkipped", (value) => value === 0, "0 source-bound skips"],
      ["releaseEvidence.criticalPaths.ENT-02.servedEstimateCount", (value) => typeof value === "number" && value > 0, "positive estimate count"],
      ["releaseEvidence.criticalPaths.ENT-02.servedValidatedAll", (value) => value === true, "true"],
    ],
  },
  {
    id: "ENT-04",
    report: "enterprise",
    fields: [
      ["releaseEvidence.criticalPaths.ENT-04.quantity", (value) => value === 12000, "12,000 units"],
      ["releaseEvidence.criticalPaths.ENT-04.unitCostUsd", (value) => sameNumber(value, 10.08, 0.001), "$10.08"],
      ["releaseEvidence.criticalPaths.ENT-04.annualExposureUsd", (value) => sameNumber(value, 120960, 0.01), "$120,960"],
      ["releaseEvidence.criticalPaths.ENT-04.basis", (value) => value === "decision.recommendation", "decision.recommendation"],
      ["releaseEvidence.criticalPaths.ENT-04.withheldBeforeExactQuantity", (value) => value === true, "true"],
      ["releaseEvidence.criticalPaths.ENT-04", (value) => sameNumber(value?.unitCostUsd * value?.quantity, value?.annualExposureUsd, 0.01), "unit cost × quantity equals annual exposure"],
    ],
  },
  {
    id: "WORK-05",
    report: "p7",
    fields: [
      ["releaseEvidence.criticalPaths.WORK-05.initialStatus", (value) => value === "unreviewed", "unreviewed"],
      ["releaseEvidence.criticalPaths.WORK-05.approvedAt", nonEmptyString, "approval timestamp"],
      ["releaseEvidence.criticalPaths.WORK-05.reopenedStatus", (value) => value === "unreviewed", "unreviewed after reopen"],
      ["releaseEvidence.criticalPaths.WORK-05.staleReason", (value) => /^rate_library_published:/.test(value), "rate_library_published:*"],
    ],
  },
  {
    id: "ROLE-01",
    report: "p7",
    fields: [
      ["releaseEvidence.criticalPaths.ROLE-01.sessionSource", nonEmptyString, "viewer session source"],
      ["releaseEvidence.criticalPaths.ROLE-01.orgRole", (value) => value === "viewer", "viewer"],
      ["releaseEvidence.criticalPaths.ROLE-01.adminMutationStatus", (value) => value === 403, "HTTP 403"],
    ],
  },
  ...["DOOR-HANDLE-ASSEMBLY-FIDELITY-001", "VALVE-STEM-ASSEMBLY-FIDELITY-001"].map((id) => ({
    id,
    report: "assembly",
    fields: [
      [`releaseEvidence.criticalPaths.${id}.fixtureSha256`, sha256, "64-character fixture SHA-256"],
      [`releaseEvidence.criticalPaths.${id}.withinTransformTolerance`, (value) => value === true, "true"],
      [`releaseEvidence.criticalPaths.${id}`, (value) => sameNumber(value?.maxAnchorErrorMm, value?.maxAnchorErrorMm) && typeof value?.toleranceMm === "number" && value.maxAnchorErrorMm <= value.toleranceMm, "max anchor error ≤ tolerance"],
      [`releaseEvidence.criticalPaths.${id}.changedSampledPixels`, (value) => typeof value === "number" && value > 0, "positive visual pixel delta"],
      [`releaseEvidence.criticalPaths.${id}.seatedScreenshotBytes`, (value) => typeof value === "number" && value > 0, "non-empty seated screenshot"],
    ],
  })),
];

export const criticalEvidenceDefinitions = definitions.map(({ id, report, fields }) => ({
  id,
  report,
  fields: fields.map(([field, , expected]) => ({ field, expected })),
}));

function problem({ type, report, requirementId = null, field, expected, actual, message }) {
  return { type, report, requirementId, field, expected, actual, message };
}

export function validateBuildIdentities(reports, expectedIdentity) {
  const problems = [];
  if (expectedIdentity.gitDirty === true) {
    problems.push(
      problem({
        type: "dirty_worktree",
        report: "gate",
        field: "buildIdentity.gitDirty",
        expected: "false",
        actual: true,
        message: "release gate working tree is dirty; reports cannot be bound to the exact current Git HEAD",
      })
    );
  }
  for (const [reportName, report] of Object.entries(reports)) {
    const identity = report?.data?.buildIdentity;
    const checks = [
      ["buildIdentity.schemaVersion", identity?.schemaVersion, (value) => value === BUILD_IDENTITY_SCHEMA_VERSION, String(BUILD_IDENTITY_SCHEMA_VERSION)],
      ["buildIdentity.gitHead", identity?.gitHead, (value) => value === expectedIdentity.gitHead, expectedIdentity.gitHead],
      ["buildIdentity.buildId", identity?.buildId, (value) => value === expectedIdentity.buildId, expectedIdentity.buildId],
      ["buildIdentity.buildIdSource", identity?.buildIdSource, (value) => value === expectedIdentity.buildIdSource, expectedIdentity.buildIdSource],
      ["buildIdentity.gitDirty", identity?.gitDirty, (value) => value === expectedIdentity.gitDirty, String(expectedIdentity.gitDirty)],
      ["buildIdentity.capturedAt", identity?.capturedAt, (value) => !Number.isNaN(Date.parse(value)), "ISO-8601 timestamp"],
    ];
    for (const [field, actual, valid, expected] of checks) {
      if (valid(actual)) continue;
      const isMissing = missing(actual);
      problems.push(
        problem({
          type: isMissing ? "missing_build_identity" : "build_identity_mismatch",
          report: reportName,
          field,
          expected,
          actual: isMissing ? null : actual,
          message: `${reportName} ${isMissing ? "is missing" : "has invalid"} ${field}; expected ${expected}`,
        })
      );
    }
  }
  return problems;
}

export function validateCriticalEvidence(reports) {
  const problems = [];
  const byRequirement = {};
  for (const reportName of new Set(definitions.map((definition) => definition.report))) {
    const actual = reports[reportName]?.data?.releaseEvidence?.schemaVersion;
    if (actual === RELEASE_EVIDENCE_SCHEMA_VERSION) continue;
    const isMissing = missing(actual);
    problems.push(
      problem({
        type: isMissing ? "missing_critical_evidence" : "invalid_critical_evidence",
        report: reportName,
        requirementId: "RELEASE-EVIDENCE-SCHEMA",
        field: "releaseEvidence.schemaVersion",
        expected: String(RELEASE_EVIDENCE_SCHEMA_VERSION),
        actual: isMissing ? null : actual,
        message: `RELEASE-EVIDENCE-SCHEMA [${reportName}] ${isMissing ? "is missing" : "has invalid"} evidence field releaseEvidence.schemaVersion; expected ${RELEASE_EVIDENCE_SCHEMA_VERSION}`,
      })
    );
  }
  for (const definition of definitions) {
    const report = reports[definition.report]?.data;
    const failures = [];
    for (const [field, valid, expected] of definition.fields) {
      const actual = valueAt(report, field);
      if (valid(actual, report)) continue;
      const isMissing = missing(actual);
      const item = problem({
        type: isMissing ? "missing_critical_evidence" : "invalid_critical_evidence",
        report: definition.report,
        requirementId: definition.id,
        field,
        expected,
        actual: isMissing ? null : actual,
        message: `${definition.id} [${definition.report}] ${isMissing ? "is missing" : "has invalid"} evidence field ${field}; expected ${expected}`,
      });
      failures.push(item);
      problems.push(item);
    }
    byRequirement[definition.id] = {
      report: definition.report,
      valid: failures.length === 0,
      failures,
    };
  }
  return {
    total: definitions.length,
    valid: Object.values(byRequirement).filter((item) => item.valid).length,
    problems,
    byRequirement,
  };
}
