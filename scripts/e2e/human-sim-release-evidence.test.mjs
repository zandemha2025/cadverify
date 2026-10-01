import { assertWeakPasswordRejection, isExpectedSignupConsoleError } from "./signup-rejection-validation.mjs";
import assert from "node:assert/strict";
import test from "node:test";
import { coverageFor, requirements } from "./human-sim-journey-coverage.mjs";
import {
  BUILD_IDENTITY_SCHEMA_VERSION,
  RELEASE_EVIDENCE_SCHEMA_VERSION,
  validateBuildIdentities,
  validateCriticalEvidence,
  hasProcessScopedConfidence,
} from "./human-sim-release-evidence.mjs";

const cubeSha = "76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a";
const artifactSha = "a".repeat(64);
const secondArtifactSha = "b".repeat(64);

function identity(overrides = {}) {
  return {
    schemaVersion: BUILD_IDENTITY_SCHEMA_VERSION,
    gitHead: "1".repeat(40),
    buildId: "build-123",
    buildIdSource: "E2E_BUILD_ID",
    gitDirty: false,
    capturedAt: "2026-07-12T12:00:00.000Z",
    ...overrides,
  };
}

function report(data = {}) {
  return { data: { status: "PASS", ...data }, steps: data.steps || [] };
}

function completeReports() {
  return {
    human: report({
      releaseEvidence: {
        schemaVersion: RELEASE_EVIDENCE_SCHEMA_VERSION,
        criticalPaths: {
          "PUB-03": {
            receiptId: "CV-123456789012",
            acknowledged: true,
            responseStatus: 200,
            responseReceiptMatches: true,
            screenshot: "/tmp/pilot.png",
          },
          "VER-05": {
            fixtureSha256: cubeSha,
            boundingBoxMm: [20, 15, 10],
            volumeMm3: 2717.3,
            surfaceAreaMm2: 1432,
            watertight: true,
            decisionId: "01TESTDECISION",
            validationStatus: 200,
            costStatus: 200,
            screenshot: "/tmp/verify.png",
          },
        },
      },
    }),
    design: report({
      releaseEvidence: {
        schemaVersion: RELEASE_EVIDENCE_SCHEMA_VERSION,
        criticalPaths: {
          "DES-05": {
            artifactSha256: artifactSha,
            responseHeaderSha256: artifactSha,
            hashesMatch: true,
            envelopeMm: [120, 70, 8],
            uiVolumeCm3: 64.69,
            previewMode: "interactive",
            screenshot: "/tmp/design.png",
          },
          "DES-10": {
            r1Sha256: artifactSha,
            r2Sha256: secondArtifactSha,
            hashesDiffer: true,
            r1RoundTripExact: true,
            r2EnvelopeMm: [130, 70, 8],
            r2UiVolumeCm3: 70.29,
          },
          "DES-11": {
            revision: 1,
            queryRevision: "1",
            artifactSha256: artifactSha,
            envelopeMm: [120, 70, 8],
            uiVolumeCm3: 64.69,
            watertight: true,
            shouldCostComputed: true,
          },
        },
      },
    }),
    enterprise: report({
      releaseEvidence: {
        schemaVersion: RELEASE_EVIDENCE_SCHEMA_VERSION,
        criticalPaths: {
          "ENT-01": {
            rateCardSource: "governed_rate_card",
            validated: false,
            machineRates: [
              { process: "mjf", rate: 48 },
              { process: "cnc_3axis", rate: 95 },
              { process: "cnc_5axis", rate: 142 },
              { process: "dmls", rate: 185 },
            ],
          },
          "ENT-02": {
            total: 4,
            nReal: 4,
            minimumReal: 8,
            recalibrationRefused: true,
            sourceBoundImported: 8,
            sourceBoundImportSkipped: 0,
            sourceSha256: cubeSha,
            calibrationValidated: true,
            calibrationFromReal: true,
            heldoutReal: 3,
            sourceBoundSkipped: 0,
            servedEstimateCount: 2,
            validatedProcesses: ["fdm"],
            servedConfidence: [
              { process: "fdm", confidence: { validated: true, method: "measured-residual", n_samples: 3 } },
              { process: "mjf", confidence: { validated: false, method: "assumption-band", n_samples: 0 } },
            ],
          },
          "ENT-04": {
            quantity: 12000,
            unitCostUsd: 3.44,
            annualExposureUsd: 41280,
            basis: "decision.recommendation",
            withheldBeforeExactQuantity: true,
          },
        },
      },
    }),
    p7: report({
      releaseEvidence: {
        schemaVersion: RELEASE_EVIDENCE_SCHEMA_VERSION,
        criticalPaths: {
          "WORK-05": {
            initialStatus: "unreviewed",
            approvedAt: "2026-07-12T12:00:00Z",
            reopenedStatus: "unreviewed",
            staleReason: "rate_library_published:v1",
          },
          "ROLE-01": {
            sessionSource: "self-seeded-invite",
            orgRole: "viewer",
            adminMutationStatus: 403,
          },
        },
      },
    }),
    assembly: report({
      releaseEvidence: {
        schemaVersion: RELEASE_EVIDENCE_SCHEMA_VERSION,
        criticalPaths: Object.fromEntries(
          ["DOOR-HANDLE-ASSEMBLY-FIDELITY-001", "VALVE-STEM-ASSEMBLY-FIDELITY-001"].map((id) => [
            id,
            {
              fixtureSha256: artifactSha,
              withinTransformTolerance: true,
              maxAnchorErrorMm: 0.1,
              toleranceMm: 0.5,
              changedSampledPixels: 100,
              seatedScreenshotBytes: 1024,
            },
          ])
        ),
      },
    }),
  };
}

test("matching a critical step name does not count without structured evidence", () => {
  const requirement = requirements.find((item) => item.id === "cad.real-step-upload");
  assert.ok(requirement);
  const reports = completeReports();
  reports.human.data.releaseEvidence.criticalPaths["VER-05"] = {};
  reports.human.steps = [{ name: "Verify processes a real STEP file upload", status: "pass" }];
  const critical = validateCriticalEvidence(reports);
  const coverage = coverageFor(requirement, reports, critical);

  assert.equal(coverage.stepMatched, true);
  assert.equal(coverage.covered, false);
  assert.equal(coverage.criticalEvidence.id, "VER-05");
  assert.ok(coverage.criticalEvidence.missingFields.includes("releaseEvidence.criticalPaths.VER-05.surfaceAreaMm2"));
});

test("complete structured critical evidence satisfies every hardened contract", () => {
  const result = validateCriticalEvidence(completeReports());
  assert.equal(result.problems.length, 0);
  assert.equal(result.valid, result.total);
});

test("calibration evidence rejects cross-process leakage, missing bands and insufficient real residuals", () => {
  const base = completeReports().enterprise.data.releaseEvidence.criticalPaths["ENT-02"];
  assert.equal(hasProcessScopedConfidence(base.servedConfidence, ["fdm"]), true);
  for (const mutate of [
    (entry) => { entry.servedConfidence[1].confidence = entry.servedConfidence[0].confidence; },
    (entry) => { entry.servedConfidence[0].confidence = entry.servedConfidence[1].confidence; },
    (entry) => { entry.servedConfidence[0].confidence.n_samples = 2; },
    (entry) => { entry.servedConfidence[0].confidence.method = "assumption-band"; },
    (entry) => { entry.servedConfidence = entry.servedConfidence.slice(0, 1); },
    (entry) => { entry.servedConfidence = entry.servedConfidence.slice(1); },
    (entry) => { entry.servedConfidence = []; },
    (entry) => { entry.validatedProcesses = ["mjf"]; },
    (entry) => { entry.servedEstimateCount += 1; },
  ]) {
    const reports = completeReports();
    mutate(reports.enterprise.data.releaseEvidence.criticalPaths["ENT-02"]);
    assert.ok(validateCriticalEvidence(reports).problems.some((item) => item.requirementId === "ENT-02"));
  }
});

test("critical evidence failures identify the exact missing field", () => {
  const reports = completeReports();
  delete reports.enterprise.data.releaseEvidence.criticalPaths["ENT-04"].annualExposureUsd;
  const result = validateCriticalEvidence(reports);
  const failure = result.problems.find((item) => item.requirementId === "ENT-04");

  assert.equal(failure.type, "missing_critical_evidence");
  assert.equal(failure.report, "enterprise");
  assert.equal(failure.field, "releaseEvidence.criticalPaths.ENT-04.annualExposureUsd");
  assert.equal(failure.actual, null);
});

test("report identity must match the current gate identity", () => {
  const expected = identity();
  const reports = Object.fromEntries(
    ["human", "design", "enterprise", "p7", "assembly"].map((name) => [
      name,
      report({ buildIdentity: identity() }),
    ])
  );
  reports.design.data.buildIdentity.gitHead = "2".repeat(40);
  delete reports.p7.data.buildIdentity.buildId;

  const problems = validateBuildIdentities(reports, expected);
  assert.ok(problems.some((item) => item.report === "design" && item.type === "build_identity_mismatch" && item.field === "buildIdentity.gitHead"));
  assert.ok(problems.some((item) => item.report === "p7" && item.type === "missing_build_identity" && item.field === "buildIdentity.buildId"));
});

test("a dirty release workspace cannot qualify as exact current HEAD", () => {
  const expected = identity({ gitDirty: true });
  const reports = Object.fromEntries(
    ["human", "design", "enterprise", "p7", "assembly"].map((name) => [
      name,
      report({ buildIdentity: identity({ gitDirty: true }) }),
    ])
  );
  const problems = validateBuildIdentities(reports, expected);
  assert.ok(problems.some((item) => item.type === "dirty_worktree" && item.report === "gate"));
});

test("only the verified weak-password rejection can classify its exact HTTP console error", () => {
  const body = { code: "weak_password", message: "Password must be at least 8 characters." };
  assertWeakPasswordRejection(400, body);
  for (const status of [200, 401, 422, 500, 503]) {
    assert.throws(() => assertWeakPasswordRejection(status, body));
  }
  assert.throws(() => assertWeakPasswordRejection(400, { ...body, code: "signup_disabled" }));
  assert.throws(() => assertWeakPasswordRejection(400, {}));
  const resourceUrl = "http://localhost:3000/api/auth/signup";
  const error = { sourceUrl: resourceUrl, text: "Failed to load resource: the server responded with a status of 400 (Bad Request)" };
  assert.equal(isExpectedSignupConsoleError(error, resourceUrl), true);
  for (const changed of [
    { sourceUrl: "http://localhost:3000/api/auth/login" },
    { sourceUrl: "http://localhost:3000/signup" },
    { sourceUrl: undefined },
    { text: "Failed to load resource: the server responded with a status of 500 (Internal Server Error)" },
    { text: "Uncaught TypeError" },
  ]) assert.equal(isExpectedSignupConsoleError({ ...error, ...changed }, resourceUrl), false);
});
