import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./mobile-recovery-e2e.mjs", import.meta.url),
  "utf8",
);

function method(name, nextName) {
  const start = source.indexOf(`async ${name}(`);
  assert.ok(start >= 0, `${name} method is missing`);
  const end = nextName ? source.indexOf(`async ${nextName}(`, start + 1) : source.length;
  assert.ok(end > start, `${name} method boundary is missing`);
  return source.slice(start, end);
}

function ordered(text, needles) {
  let cursor = -1;
  for (const needle of needles) {
    const next = text.indexOf(needle, cursor + 1);
    assert.ok(next > cursor, `${needle} was missing or out of order`);
    cursor = next;
  }
}

test("authenticated recovery reads use the signed-in page and live proxy", () => {
  const body = method("json", "designList");
  assert.match(body, /targetUrl\.pathname\.startsWith\("\/api\/proxy\/"\)/);
  assert.match(body, /this\.page\.evaluate/);
  assert.match(body, /await fetch\(target/);
  assert.match(body, /credentials: "same-origin"/);
  assert.match(body, /GET \$\{pathname\} returned \$\{result\.status\}/);
  assert.doesNotMatch(source, /context\.request|request\.newContext|pw\.request/);
});

test("multipart abort diagnostics require an exact matching 2xx response", () => {
  assert.match(source, /function recoverableSuccessAbortKey\(request\)/);
  assert.match(source, /url\.pathname\.includes\("\/direct-uploads\/"\)/);
  assert.ok(
    source.includes('/^\\/api\\/proxy\\/uploads\\/[A-Z0-9]+\\/complete$/i'),
    "multipart completion matcher is missing",
  );
  assert.match(source, /this\.successfulAbortableResponses\.set\(key, status\)/);
  assert.match(source, /pending\.recoveredStatus = status/);
  assert.match(source, /without a matching successful HTTP response/);
  assert.match(source, /this\.reconcileSuccessfulAborts\(id\)/);
});

test("saved verification waits for the overlay to detach and all visual blockers to clear", () => {
  const body = method("waitForSavedVerification", "waitForTerminalVisualState");
  assert.match(body, /state: "detached"/);
  assert.match(body, /Open the record/);
  assert.match(body, /waitForTerminalVisualState/);
  assert.match(source, /aria-busy="true"[\s\S]*skeleton[\s\S]*data-state="loading"/);
});

test("VER-09 selects the durable Records artifact at all three settled viewports", () => {
  const body = method("responsiveKeyboardContract", "invalidCadRecovery");
  assert.match(body, /getByRole\("button", \{ name: new RegExp\(escapeRegExp\(expectedRecordName\)/);
  assert.match(body, /getByTestId\("record-disposition-summary"\)/);
  assert.match(body, /getByText\("Open governance"/);
  for (const stage of ["records-375x812", "records-768x1024", "records-1440x900"]) {
    assert.ok(body.includes("`records-${key}`"), `dynamic stage source missing for ${stage}`);
  }
  assert.match(body, /visualSteps\.push\(visualStep\)/);
  assert.match(body, /requiredVisible: \[expectedRecordName, "Open governance"\]/);
  assert.match(body, /forbiddenVisible: \["Verification is running\."\]/);
});

test("FAIL-01 and FAIL-03 capture visible failures before recovery", () => {
  const invalid = method("invalidCadRecovery", "verifyCapacityRecovery");
  ordered(invalid, [
    'captureStage("FAIL-01", "failure"',
    "setInputFiles(trackedCubeFixture)",
    "waitForSavedVerification()",
    'captureStage("FAIL-01", "recovery"',
  ]);
  const capacity = method("verifyCapacityRecovery", "costHistoryRecovery");
  ordered(capacity, [
    'captureStage("FAIL-03", "failure"',
    'getByRole("button", { name: "Retry verification →" }).click()',
    "waitForSavedVerification()",
    'captureStage("FAIL-03", "recovery"',
  ]);
});

test("FAIL-08 removes the outage alert before recovered evidence", () => {
  const body = method("costHistoryRecovery", "workerStatusRecovery");
  ordered(body, [
    'captureStage("FAIL-08", "failure"',
    'getByRole("button", { name: "Try again" }).click()',
    'outageAlert.waitFor({ state: "hidden"',
    'captureStage("FAIL-08", "recovery"',
  ]);
  assert.match(body, /forbiddenVisible: \["Cost history is temporarily unavailable\. Retry shortly\."\]/);
});

test("FAIL-10 captures degradation, then requires terminal counters and enabled CSV", () => {
  const body = method("workerStatusRecovery", "apiFailureMatrix");
  ordered(body, [
    'captureStage("FAIL-10", "failure"',
    "page.unroute",
    'getByRole("button", { name: "Try again" }).first().click()',
    'getByText(/1 \\/ 1/)',
    "downloadCsv.isEnabled()",
    'captureStage("FAIL-10", "recovery"',
  ]);
  assert.match(body, /forbiddenVisible: \["Could not load progress"\]/);
  assert.match(source, /releaseEvidence: \{\s*schemaVersion: 2,/);
});
