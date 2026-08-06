import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { makeGoldenPathEvidence } from "./golden-path-evidence.mjs";
import {
  GROUND_TRUTH_CSV_HEADER,
  MACHINE_CSV_HEADER,
  MANIFEST_CSV_HEADER,
  MANUFACTURING_FORM_IMPORT_CASE_IDS,
  REQUIRED_RESPONSE_STATUSES,
  assertDurableCount,
  assertExactImportSummary,
  assertNoEmptyStateLie,
  isExpectedNextRscPrefetchAbort,
  validateManufacturingFormsReport,
} from "./manufacturing-forms-import-browser.mjs";

const source = await readFile(
  new URL("./manufacturing-forms-import-browser.mjs", import.meta.url),
  "utf8",
);

function visualStep(id, stage = "outcome") {
  return {
    id,
    stage,
    terminal: true,
    screenshot: `/tmp/${id}-${stage}.png`,
    capturedAt: "2026-07-14T12:00:00.000Z",
    url: "http://localhost:3000/verify",
    requiredVisible: ["Persisted manufacturing outcome"],
    forbiddenVisible: ["COMPUTING", "Loading"],
    capture: {
      text: "Persisted manufacturing outcome",
      ariaBusyCount: 0,
      skeletonCount: 0,
      loadingIndicatorCount: 0,
    },
  };
}

function validEvidence(id) {
  const step = visualStep(id);
  return makeGoldenPathEvidence({
    id,
    status: "PASS",
    persona: "Authenticated manufacturing operator",
    preconditions: ["A real organization-scoped backend is available."],
    actions: ["Drive the visible UI and refresh the resulting surface."],
    observed: {
      url: "http://localhost:3000/verify",
      visible: ["Persisted manufacturing outcome"],
      persisted: { durable: true },
      numeric: { count: 1 },
      authorization: "Authenticated same-origin proxy",
      recovery: "Full refresh retained the outcome.",
    },
    screenshot: step.screenshot,
    visualSteps: [step],
    consoleErrors: [],
    requestFailures: [],
    assertions: [
      { name: "durable result", expected: true, actual: true, pass: true },
    ],
  });
}

function validReport() {
  const identity = {
    schemaVersion: 1,
    gitHead: "a".repeat(40),
    buildId: "release-2026-07-14",
    buildIdSource: "E2E_BUILD_ID",
    gitDirty: true,
    capturedAt: "2026-07-14T12:00:00.000Z",
  };
  return {
    schemaVersion: 2,
    execution: {
      attemptedCaseIds: [...MANUFACTURING_FORM_IMPORT_CASE_IDS],
      omittedCaseIds: [],
    },
    responseStatuses: { ...REQUIRED_RESPONSE_STATUSES },
    diagnostics: {
      unexpectedConsoleErrors: [],
      unexpectedRequestFailures: [],
      unexpectedHttpErrors: [],
    },
    buildIdentity: { start: identity, end: { ...identity } },
    releaseEvidence: {
      schemaVersion: 2,
      cases: Object.fromEntries(
        MANUFACTURING_FORM_IMPORT_CASE_IDS.map((id) => [id, validEvidence(id)]),
      ),
    },
  };
}

test("the manufacturing suite has exact, exhaustive local branches and canonical CSV headers", () => {
  assert.deepEqual(MANUFACTURING_FORM_IMPORT_CASE_IDS, [
    "MFI-01",
    "MFI-02",
    "MFI-03",
    "MFI-04",
    "MFI-05",
    "MFI-06",
    "MFI-07",
  ]);
  assert.deepEqual(MACHINE_CSV_HEADER, [
    "process",
    "name",
    "count",
    "max_workpiece_kg",
    "hourly_rate_usd",
    "capital_frac",
    "materials",
    "material_thickness_map",
    "capabilities",
    "notes",
  ]);
  assert.deepEqual(MANIFEST_CSV_HEADER, [
    "part_id",
    "description",
    "material_class",
    "program",
    "parent_assembly",
    "units_per_parent",
    "annual_volume",
    "quantity",
    "region",
    "source",
    "notes",
  ]);
  assert.deepEqual(GROUND_TRUTH_CSV_HEADER, [
    "part_id",
    "process",
    "quantity",
    "actual_unit_cost_usd",
  ]);
});

test("exact-count oracle accepts honest import receipts and rejects approximate claims", () => {
  const mixed = {
    imported: 1,
    skipped: 1,
    total: 2,
    errors: [{ line: 3, reason: "count not an integer ('2x')" }],
  };
  assert.deepEqual(
    assertExactImportSummary(
      mixed,
      { imported: 1, skipped: 1, total: 2, errorCount: 1 },
      "mixed machines",
    ),
    mixed,
  );
  assert.throws(
    () => assertExactImportSummary(mixed, { imported: 1, skipped: 0, total: 2, errorCount: 1 }),
    /skipped/,
  );
  assert.throws(
    () => assertExactImportSummary({ ...mixed, errors: [] }, { imported: 1, skipped: 1, total: 2, errorCount: 1 }),
    /error count/,
  );

  const manifest = { imported: 2, updated: 0, skipped: 0, total: 2, errors: [] };
  assert.equal(
    assertExactImportSummary(
      manifest,
      { imported: 2, updated: 0, skipped: 0, total: 2, errorCount: 0 },
    ).updated,
    0,
  );
  assert.throws(
    () => assertExactImportSummary({ ...manifest, updated: 1 }, { imported: 2, updated: 0, skipped: 0, total: 2, errorCount: 0 }),
    /updated/,
  );
});

test("durable-count and empty-state oracles fail closed", () => {
  assert.deepEqual(
    assertDurableCount({ before: 4, imported: 3, after: 7, label: "actuals" }),
    { before: 4, imported: 3, after: 7 },
  );
  assert.throws(
    () => assertDurableCount({ before: 4, imported: 3, after: 6, label: "actuals" }),
    /durable row count/,
  );
  assert.throws(
    () => assertDurableCount({ before: 4.5, imported: 1, after: 5.5, label: "actuals" }),
    /non-negative integer/,
  );

  assert.deepEqual(
    assertNoEmptyStateLie({
      surface: "machines",
      persistedCount: 3,
      uiText: "3 machines owned · all rates declared",
      emptyCopy: ["No machines declared", "Declare your floor."],
    }),
    { surface: "machines", persistedCount: 3, emptyCopyAbsent: true },
  );
  assert.throws(
    () => assertNoEmptyStateLie({
      surface: "actuals",
      persistedCount: 3,
      uiText: "n=0 · every band still hatched",
      emptyCopy: ["n=0 · every band still hatched"],
    }),
    /showed empty-state copy/,
  );
});

test("request-failure filter ignores only same-origin Next RSC GET prefetch aborts", () => {
  const appUrl = "http://localhost:3000";
  const expected = {
    method: "GET",
    url: "http://localhost:3000/verify?_rsc=abc123",
    resourceType: "fetch",
    error: "net::ERR_ABORTED",
  };
  assert.equal(isExpectedNextRscPrefetchAbort(expected, appUrl), true);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, method: "POST" }, appUrl), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, resourceType: "document" }, appUrl), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, error: "net::ERR_CONNECTION_RESET" }, appUrl), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, url: "http://localhost:3000/verify" }, appUrl), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, url: "https://other.example/verify?_rsc=abc" }, appUrl), false);
});

test("schemaVersion 2 report oracle requires every case, exact statuses, diagnostics, and build binding", () => {
  const valid = validateManufacturingFormsReport(validReport());
  assert.equal(valid.valid, true);
  assert.deepEqual(valid.problems, []);

  const missing = validReport();
  delete missing.releaseEvidence.cases["MFI-05"];
  assert.equal(validateManufacturingFormsReport(missing).valid, false);
  assert.ok(
    validateManufacturingFormsReport(missing).problems.some(
      (problem) => problem.field === "releaseEvidence.caseIds" || problem.field === "MFI-05.status",
    ),
  );

  const wrongStatus = validReport();
  wrongStatus.responseStatuses.machineDelete = 204;
  assert.ok(
    validateManufacturingFormsReport(wrongStatus).problems.some(
      (problem) => problem.field === "responseStatuses.machineDelete",
    ),
  );

  const noisy = validReport();
  noisy.diagnostics.unexpectedHttpErrors.push({ status: 500, path: "/api/proxy/manifest" });
  assert.ok(
    validateManufacturingFormsReport(noisy).problems.some(
      (problem) => problem.field === "diagnostics.unexpectedHttpErrors",
    ),
  );

  const drifted = validReport();
  drifted.buildIdentity.end.gitHead = "b".repeat(40);
  assert.ok(
    validateManufacturingFormsReport(drifted).problems.some(
      (problem) => problem.field === "buildIdentity.end.gitHead",
    ),
  );

  const unproven = validReport();
  unproven.releaseEvidence.cases["MFI-06"].visualSteps = [];
  unproven.releaseEvidence.cases["MFI-06"].visualProof = "NOT_VISUALLY_PROVABLE";
  assert.ok(
    validateManufacturingFormsReport(unproven).problems.some(
      (problem) => problem.field === "MFI-06.visualProof",
    ),
  );
});

test("runner drives the real UI for every mutation and records exact backend receipts", () => {
  assert.match(source, /require\("playwright-core"\)/);
  assert.match(source, /chromium\.launch/);
  assert.match(source, /page\.getByRole\("button", \{ name: "Declare machine", exact: true \}\)\.click\(\)/);
  assert.match(source, /page\.getByRole\("button", \{ name: "Save changes", exact: true \}\)\.click\(\)/);
  assert.match(source, /page\.getByRole\("button", \{ name: "Delete machine", exact: true \}\)\.click\(\)/);
  assert.match(source, /page\.waitForEvent\("filechooser"/);
  assert.match(source, /manifest\/BOM onboarding button on Triage/);
  assert.match(source, /ground-truth\/actuals CSV import button/);
  assert.match(source, /machine create HTTP[\s\S]*201/);
  assert.match(source, /machine edit HTTP[\s\S]*200/);
  assert.match(source, /machine delete HTTP[\s\S]*200/);
  assert.match(source, /valid machine import HTTP[\s\S]*200/);
  assert.match(source, /mixed machine import HTTP[\s\S]*200/);
  assert.match(source, /manifest import HTTP[\s\S]*200/);
  assert.match(source, /ground-truth import HTTP[\s\S]*200/);

  // Backend requests in this runner are read-only persistence oracles. Every
  // write must originate from a visible form/button/file chooser.
  assert.doesNotMatch(source, /context\.request\.(?:post|put|patch|delete)\s*\(/i);
  assert.doesNotMatch(source, /page\.evaluate\([\s\S]{0,400}fetch\([^)]*\{[\s\S]{0,200}method:\s*["'](?:POST|PUT|PATCH|DELETE)/i);
});

test("machine form coverage proves refusal-before-request and accepted lower boundaries", () => {
  assert.match(source, /count: "1\.5"/);
  assert.match(source, /rate: "95\/hr"/);
  assert.match(source, /maxKg: "0"/);
  assert.match(source, /z: "Infinity"/);
  assert.match(source, /mutationsAfter === mutationsBefore/);
  assert.match(source, /Count must be a whole number\./);
  assert.match(source, /Hourly rate must be a complete number\./);
  assert.match(source, /Max workpiece must be greater than 0\./);
  assert.match(source, /Envelope X must be greater than 0\./);

  assert.match(source, /rate: "0"/);
  assert.match(source, /maxKg: "0\.001"/);
  assert.match(source, /x: "0\.001"/);
  assert.match(source, /created\.hourly_rate_usd, 0/);
  assert.match(source, /created\.max_workpiece_kg, 0\.001/);
  assert.match(source, /edited-after-refresh/);
  assert.match(source, /deleted-after-refresh/);
});

test("runner cannot omit local branches or turn absent UI into invented success", () => {
  for (const id of MANUFACTURING_FORM_IMPORT_CASE_IDS) {
    assert.match(source, new RegExp(`id: ["']${id}["']`));
  }
  for (const caseFunction of [
    "caseMachineBoundaries",
    "caseMachineCrud",
    "caseValidMachineImport",
    "caseMixedMachineImport",
    "caseManifestOnboarding",
    "caseGroundTruthImport",
    "caseRefreshTruth",
  ]) {
    assert.match(source, new RegExp(`execute: \\(\\) => ${caseFunction}\\(shared\\)`));
  }
  assert.match(source, /Required UI flow absent or defective:/);
  assert.match(source, /A failing evidence entry was emitted instead of treating the omitted branch as success/);
  assert.match(source, /omittedCaseIds/);
  assert.doesNotMatch(source, /(?:test\.)?skip\s*\(/i);
  assert.doesNotMatch(source, /SkipStep/);
  assert.doesNotMatch(source, /localhost[\s\S]{0,100}(?:omit|bypass)/i);
});

test("runner binds screenshots, schemaVersion 2, build identity, and zero unexpected errors", () => {
  assert.match(source, /captureVisualStep/);
  assert.match(source, /await stat\(screenshot\)/);
  assert.match(source, /await assertScreenshotFiles\(evidence\)/);
  assert.match(source, /const buildIdentityStart = captureBuildIdentity\(repoRoot\)/);
  assert.match(source, /const buildIdentityEnd = captureBuildIdentity\(repoRoot\)/);
  assert.match(source, /ownedSources = await sourceIdentity\(\)/);
  assert.match(source, /schemaVersion: 2,[\s\S]*releaseEvidence: \{[\s\S]*schemaVersion: 2/);
  assert.match(source, /unexpectedConsoleErrors/);
  assert.match(source, /unexpectedRequestFailures/);
  assert.match(source, /unexpectedHttpErrors/);
  assert.match(source, /if \(receipt\.status >= 400\) diagnostics\.unexpectedHttpErrors\.push\(receipt\)/);
  assert.match(source, /validateManufacturingFormsReport\(report\)/);
});
