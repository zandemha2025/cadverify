import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./enterprise-domain-runner.mjs", import.meta.url),
  "utf8",
);

const ownedIds = [
  "VER-06",
  "VER-08",
  "WORK-09",
  "WORK-10",
  "WORK-11",
  "ENT-02",
  "ENT-03",
  "ENT-04",
  "ENT-05",
];

function structuredIds() {
  const match = source.match(/const structuredGoldenIds = \[(.*?)\];/s);
  assert.ok(match, "structuredGoldenIds declaration is missing");
  return [...match[1].matchAll(/"([A-Z]+-\d+)"/g)].map((item) => item[1]);
}

test("enterprise evidence includes every owned exact golden ID while allowing companion IDs", () => {
  const ids = structuredIds();
  for (const id of ownedIds) assert.ok(ids.includes(id), `${id} is missing`);
  for (const id of ownedIds) {
    assert.match(source, new RegExp(`"${id}": this\\.structuredPath\\(\\{`));
  }
});

test("structured paths use the common envelope, explicit assertions, and build identity", () => {
  assert.match(source, /makeGoldenPathEvidence\(\{/);
  assert.match(source, /validateGoldenPathMap\(structuredGoldenIds, goldenPaths\)/);
  assert.match(source, /captureBuildIdentity\(repoRoot\)/);
  assert.match(source, /releaseEvidence = \{[\s\S]*goldenPaths,[\s\S]*validation,/);
  assert.match(source, /unexpected browser console errors/);
  assert.match(source, /unexpected browser request failures/);
  assert.match(source, /unexpected HTTP error responses/);
  assert.match(source, /this\.httpErrorResponses\.filter\(\(entry\) => !isExpectedHttpErrorResponse\(entry\)\)/);
  assert.match(source, /if \(entry\.status === 422 && entry\.path === "\/api\/proxy\/ground-truth\/recalibrate"\)/);
  assert.doesNotMatch(source, /return method === "GET" && \/\\\/_next\\\/static\\\/chunks/);
  assert.doesNotMatch(source, /status\s*=\s*this\.steps/);
  assert.doesNotMatch(source, /goldenPaths\[[^\]]+\]\s*=\s*this\.steps/);
});

test("browser orchestration executes all owned journeys before finish", () => {
  const calls = [
    "verifyIntegrationDryRunImport",
    "runCadVerification",
    "verifyInterruptedVerification",
    "declarePortfolioContext",
    "verifyDeclaredContextInProductStage",
    "assertExactQuantityPortfolioCorrectness",
    "verifyHistoryAnalysisDetail",
    "verifyProgramUiAndHistory",
    "verifyReconstructionRecovery",
  ];
  let previous = -1;
  for (const method of calls) {
    const index = source.lastIndexOf(`await runner.${method}();`);
    assert.ok(index > previous, `${method} is missing or out of order`);
    previous = index;
  }
});

test("VER-06 and enterprise economics retain exact quantity and cost oracles", () => {
  assert.match(source, /const baseQuantityLadder = \[1, 100, 1000, 2000, 5000, 10000\]/);
  assert.match(source, /const annualQuantityLadder = \[1, 100, 1000, 2000, 10000, 12000\]/);
  assert.match(source, /"annual recommendation reconciles to portfolio basis"/);
  assert.match(source, /"single-part headline", 133\.58/);
  assert.match(source, /"exact annual unit cost", 10\.08/);
  assert.match(source, /"annual exposure", 120960/);
  assert.match(source, /"single-part headline is not annualized"/);
});

test("integration, history, reconstruction, and interruption assert persisted outcomes", () => {
  assert.match(source, /fileSha256 = createHash\("sha256"\)/);
  assert.match(source, /exactJson\(importedRows, expectedRows\)/);
  assert.match(source, /retried\.imported_count === 0 && retried\.updated_count === 2/);
  assert.match(source, /detail\.analysis_time_ms === row\.analysis_time_ms/);
  assert.match(source, /sameArray\(linkedDecisionIds, expectedDecisionIds\)/);
  assert.match(source, /beforeAnalysisRows\[0\]\.id === afterAnalysisRows\[0\]\.id|afterAnalysisRows\[0\]\.id === beforeAnalysisRows\[0\]\.id/);
  assert.match(source, /responseObservedAt == null/);
  assert.match(source, /"navigation began while cost response was pending"/);
  assert.match(source, /terminalJob\?\.status === "done"/);
  assert.match(source, /terminalJob\?\.status === "failed"/);
  assert.match(source, /mesh\.status === 200 && mesh\.bytes > 0/);
  assert.match(source, /failure displayed a fake preview/);
});

test("severe-service and program rollup are checked across visible and persisted state", () => {
  assert.match(source, /max_temp_c === 120/);
  assert.match(source, /pressure_bar === 350/);
  assert.match(source, /sour_service === true/);
  assert.match(source, /NACE\|HDT\|ASME\|ASTM\|ISO/);
  assert.match(source, /Programs source decision did not equal the newest Records decision/);
  assert.match(source, /program\.row\.cost_decision\.id === program\.records_selected_decision_id/);
  assert.match(source, /\$120,960\\\/yr/);
});
