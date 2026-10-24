import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./manufacturing-cad-adversarial.mjs", import.meta.url),
  "utf8",
);

function stringArray(name) {
  const match = source.match(new RegExp(`const ${name} = \\[(.*?)\\];`, "s"));
  assert.ok(match, `${name} declaration is missing`);
  return [...match[1].matchAll(/"([A-Z]+-\d+)"/g)].map((item) => item[1]);
}

function functionSource(name, nextName) {
  const start = source.indexOf(`async function ${name}(`);
  const end = source.indexOf(`async function ${nextName}(`, start + 1);
  assert.ok(start >= 0, `${name} declaration is missing`);
  assert.ok(end > start, `${nextName} must follow ${name}`);
  return source.slice(start, end);
}

function recordPathSource(id) {
  const suiteStart = source.indexOf("async function runSuite(");
  const start = source.indexOf(`id: "${id}"`, suiteStart);
  const next = source.indexOf("\n  await recordPath(page, {", start + 1);
  assert.ok(start >= suiteStart, `${id} recordPath is missing`);
  return source.slice(start, next === -1 ? source.length : next);
}

function ordered(text, tokens, label) {
  let cursor = -1;
  for (const token of tokens) {
    const next = text.indexOf(token, cursor + 1);
    assert.ok(next > cursor, `${label} is missing ordered token: ${token}`);
    cursor = next;
  }
}

test("manufacturing and adversarial CAD paths use disjoint release evidence maps", () => {
  assert.deepEqual(stringArray("EXACT_GOLDEN_IDS"), [
    "ENT-01",
    "VER-05",
    "WORK-01",
    "WORK-02",
    "FAIL-01",
    "FAIL-02",
  ]);
  assert.deepEqual(stringArray("MANUFACTURING_SUBPATH_IDS"), [
    "MFG-01",
    "MFG-02",
    "MFG-03",
    "MFG-04",
    "MFG-05",
    "MFG-06",
  ]);
  assert.deepEqual(stringArray("SUPPLEMENTAL_CAD_IDS"), [
    "CAD-01",
    "CAD-02",
    "CAD-03",
    "CAD-04",
    "CAD-05",
    "CAD-06",
    "CAD-07",
    "CAD-08",
    "CAD-09",
  ]);
  assert.match(source, /Object\.fromEntries\(EXACT_GOLDEN_IDS\.map/);
  assert.match(source, /Object\.fromEntries\(SUPPLEMENTAL_CAD_IDS\.map/);
  assert.doesNotMatch(source, /PUBLISHED_GOLDEN_IDS/);
});

test("every owned browser path emits the common evidence envelope", () => {
  const expected = [
    ...stringArray("MANUFACTURING_SUBPATH_IDS"),
    ...stringArray("EXACT_GOLDEN_IDS"),
    ...stringArray("SUPPLEMENTAL_CAD_IDS"),
  ].sort();
  const authored = [...source.matchAll(/await recordPath\(page, \{\s*id: "([A-Z]+-\d+)"/g)]
    .map((item) => item[1])
    .sort();

  assert.deepEqual(authored, expected);
  assert.match(source, /makeGoldenPathEvidence\(\{/);
  assert.match(source, /const buildIdentity = captureBuildIdentity\(repoRoot\)/);
  assert.match(source, /consoleErrors: pathConsoleErrors/);
  assert.match(source, /requestFailures: pathRequestFailures/);
});

test("CAD evidence detects remote lighting and proves rendered assembly bytes and summary", () => {
  assert.match(source, /raw\\\.githack\\\.com\|drei-assets/);
  assert.match(source, /forbiddenCadAssetRequests\.push/);
  assert.match(source, /"remote CAD lighting requests"/);
  assert.match(source, /glbResponse\.headers\(\)\["x-assembly-glb-bytes"\]/);
  assert.match(source, /data-render-state/);
  assert.match(source, /PER-PART ANALYSIS — REAL/);
  assert.match(source, /analysisBody\?\.analysis\?\.analysis_summary/);
  assert.match(source, /"combined assembly GLB is non-empty"/);
});

test("expected HTTP rejections are captured separately from JavaScript errors", () => {
  assert.match(source, /isNetworkStatusConsoleMessage\(entry\.text\)/);
  assert.match(source, /if \(response\.status\(\) >= 400\)/);
  assert.match(source, /"HTTP error response count"/);
  assert.match(source, /expectedHttpErrorCount: 1,[\s\S]*id: "CAD-08"/);
});

test("highest-risk Verify evidence captures settled schema-v2 stages", () => {
  assert.match(source, /captureVisualStep/);
  assert.match(source, /waitForVerificationPipelineDetached/);
  assert.match(source, /waitFor\(\{ state: "detached", timeout \}\)/);
  assert.match(source, /captureStage\(page, "VER-05", "terminal"/);
  assert.match(source, /captureStage\(page, "FAIL-01", "failure"[\s\S]*uploadAnalyze\(page, goldenStep[\s\S]*captureStage\(page, "FAIL-01", "recovery"/);
  assert.match(source, /captureStage\(page, "FAIL-02", "failure"[\s\S]*uploadAnalyze\(page, goldenStep[\s\S]*captureStage\(page, "FAIL-02", "recovery"/);
  assert.match(source, /visualSteps: \[failureStep, recoveryStep\]/);
  assert.match(source, /forbiddenVisible: \["We couldn’t read this file\."\]/);
  assert.match(source, /forbiddenVisible: \["This part couldn’t be tessellated\."\]/);
  assert.match(source, /releaseEvidence: \{\s*schemaVersion: 2,/);
});

test("authenticated setup and read calls stay inside the credentialed Chromium page", () => {
  const helper = functionSource("browserApi", "bodyText");

  for (const snippet of [
    "return page.evaluate(",
    "new URL(target, window.location.href)",
    "requestUrl.origin !== window.location.origin",
    'credentials: "same-origin"',
    "window.fetch(requestUrl.href, normalized)",
  ]) {
    assert.ok(helper.includes(snippet), `browserApi is missing ${snippet}`);
  }
  assert.equal(source.split("fetch(").length - 1, 1);
  for (const forbidden of ["context.request", "page.request"]) {
    assert.equal(source.includes(forbidden), false, `${forbidden} bypasses the authenticated page`);
  }

  assert.equal(source.split("await browserApi(page,").length - 1, 6);
  for (const call of [
    'await browserApi(page, "/api/proxy/orgs")',
    'await browserApi(page, "/api/proxy/machine-inventory")',
    'await browserApi(page, "/api/proxy/rate-library", {',
    'await browserApi(page, `/api/proxy/rate-library/${draft.body.id}/publish`',
    'await browserApi(page, "/api/proxy/rate-library/effective")',
    'await browserApi(page, `/api/proxy/cost-decisions/${decisionId}`',
  ]) {
    assert.ok(source.includes(call), `protected call must use browserApi: ${call}`);
  }
});

test("terminal visual stages tolerate responsive duplicate actions without weakening CAD or HTTP oracles", () => {
  const helper = functionSource("waitForTerminalRecordAction", "captureStage");
  assert.ok(helper.includes('getByRole("button", { name: /^Open the record/ })'));
  assert.ok(helper.includes(".first()"));
  assert.ok(helper.includes('waitFor({ state: "visible", timeout })'));
  assert.equal(source.split("await waitForTerminalRecordAction(page)").length - 1, 3);

  const verify = recordPathSource("VER-05");
  const fail01 = recordPathSource("FAIL-01");
  const fail02 = recordPathSource("FAIL-02");
  ordered(verify, [
    "waitForVerificationPipelineDetached(page)",
    "waitForTerminalRecordAction(page)",
    'captureStage(page, "VER-05", "terminal"',
  ], "VER-05 terminal capture");
  ordered(fail01, [
    'Buffer.from("not a STEP exchange file")',
    'captureStage(page, "FAIL-01", "failure"',
    "uploadAnalyze(page, goldenStep",
    "waitForTerminalRecordAction(page)",
    'captureStage(page, "FAIL-01", "recovery"',
  ], "FAIL-01 real rejection and recovery");
  ordered(fail02, [
    "uploadAnalyze(page, wireOnlyStep",
    'captureStage(page, "FAIL-02", "failure"',
    "uploadAnalyze(page, goldenStep",
    "waitForTerminalRecordAction(page)",
    'captureStage(page, "FAIL-02", "recovery"',
  ], "FAIL-02 real rejection and recovery");

  assert.ok(fail01.includes("expectedHttpErrorCount: 4"));
  assert.ok(fail02.includes("expectedHttpErrorCount: 4"));
  assert.equal(source.includes("page.route("), false);
  assert.equal(source.includes("route.fulfill("), false);
});
