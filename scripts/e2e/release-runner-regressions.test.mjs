import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [authRunner, manufacturingRunner, roleRunner, compareRunner, releaseRunner, mobileRunner, glassBox] = await Promise.all([
  readFile(new URL("./auth-role-lifecycle-golden-matrix.mjs", import.meta.url), "utf8"),
  readFile(new URL("./manufacturing-cad-adversarial.mjs", import.meta.url), "utf8"),
  readFile(new URL("./role-tenant-boundary-matrix.mjs", import.meta.url), "utf8"),
  readFile(new URL("./compare-rfq-key-golden-matrix.mjs", import.meta.url), "utf8"),
  readFile(new URL("./local-100-release.mjs", import.meta.url), "utf8"),
  readFile(new URL("./mobile-recovery-e2e.mjs", import.meta.url), "utf8"),
  readFile(new URL("../../frontend/src/components/workspace/GlassBoxView.tsx", import.meta.url), "utf8"),
]);

test("invitation runners follow the live accessible dialog and accept route", () => {
  assert.match(authRunner, /getByRole\("alertdialog"\)/);
  assert.doesNotMatch(authRunner, /const dialog = owner\.page\.getByRole\("dialog"\)/);
  assert.match(roleRunner, /acceptLink\.pathname, "\/orgs\/accept"/);
  assert.match(roleRunner, /acceptLink\.searchParams\.get\("token"\)/);
  assert.doesNotMatch(roleRunner, /\/invite\\\/accept/);
});

test("role evidence supplies the canonical generation timestamp", () => {
  assert.match(roleRunner, /generatedAt: new Date\(finishedAt\)\.toISOString\(\)/);
});

test("release build probes do not reuse stale sockets after synchronous suites", () => {
  assert.match(releaseRunner, /const BUILD_PROBE_ATTEMPTS = 4/);
  assert.match(releaseRunner, /"connection": "close"/);
  assert.match(releaseRunner, /AbortSignal\.timeout\(BUILD_PROBE_TIMEOUT_MS\)/);
  assert.match(releaseRunner, /attempt <= BUILD_PROBE_ATTEMPTS/);
  assert.match(releaseRunner, /after \$\{BUILD_PROBE_ATTEMPTS\} attempts/);
});

test("API-key mutations finish finite proxy responses before reload", () => {
  assert.match(
    compareRunner,
    /async beginDeveloperMutation\(\s*actor,\s*button,\s*label,/,
  );
  assert.match(compareRunner, /async finishDeveloperMutation\(actor, response, label\)/);
  assert.match(compareRunner, /response\.finished\(\)/);
  assert.match(compareRunner, /mutation response did not finish within 30 seconds/);
  assert.equal(compareRunner.match(/await this\.beginDeveloperMutation\(/g)?.length, 3);
  assert.equal(compareRunner.match(/await this\.finishDeveloperMutation\(/g)?.length, 3);
  assert.match(compareRunner, /expectedStatus: 204/);
  assert.match(compareRunner, /\/api\\\/proxy\\\/keys/);
  assert.doesNotMatch(compareRunner, /failure === "net::ERR_ABORTED".*api\/proxy\/keys/);

  assert.match(roleRunner, /async finishDeveloperMutation\(actor, response, label\)/);
  assert.match(roleRunner, /response\.finished\(\)/);
  assert.match(roleRunner, /mutation response did not finish within 30 seconds/);
  assert.match(roleRunner, /state: "detached"[\s\S]*await this\.finishDeveloperMutation\(owner, createActionResponse/);
  assert.doesNotMatch(roleRunner, /const createActionError = await createActionResponse\.finished\(\)/);
});

test("mobile history recovery finishes cost persistence before the next journey", () => {
  assert.match(mobileRunner, /async waitForSavedVerification\(\)/);
  assert.match(mobileRunner, /getByRole\("button", \{ name: \/\^Open the record\/ \}\)/);
  assert.equal(mobileRunner.match(/await this\.waitForSavedVerification\(\)/g)?.length, 2);
  assert.match(
    mobileRunner,
    /historyRecovery\(\)[\s\S]*goForward[\s\S]*await this\.waitForSavedVerification\(\)[\s\S]*expiredSessionRecovery\(\)/,
  );
  assert.doesNotMatch(mobileRunner, /ERR_ABORTED[^\n]*validate\/cost/);
});

test("mobile stale-cookie replay scopes its expected 401 through redirect settlement", () => {
  assert.match(
    mobileRunner,
    /expiredSessionRecovery\(\)[\s\S]*withExpectedHttpStatuses\(\[401\][\s\S]*goto\("\/designs"[\s\S]*waitForURL[\s\S]*pathname === "\/login"[\s\S]*waitForLoadState\("networkidle"/,
  );
  assert.equal(
    mobileRunner.match(/withExpectedHttpStatuses\(\[401\]/g)?.length,
    1,
  );
});

test("cost process controls expose and use one semantic accessible group", () => {
  assert.match(glassBox, /role="group" aria-label=\{label\}/);
  assert.match(manufacturingRunner, /getByRole\("tab", \{ name: "Glass Box", exact: true \}\)\.click\(\)/);
  assert.match(manufacturingRunner, /getByRole\("group", \{ name: "Process", exact: true \}\)/);
});

test("DFM evidence accepts structured citation fields without inventing prose", () => {
  assert.match(manufacturingRunner, /function hasStructuredCitation\(citation\)/);
  assert.match(manufacturingRunner, /\["text", "standard", "clause", "rule_id"\]/);
  assert.match(manufacturingRunner, /issues\.every\(isStructuredDfmIssue\)/);
  assert.doesNotMatch(manufacturingRunner, /!issue\.citation \|\| typeof issue\.citation\?\.text === "string"/);
});
