import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./public-auth-verify-golden-matrix.mjs", import.meta.url),
  "utf8",
);

test("AUTH-03 captures the rejected login before valid recovery and AUTH-05", () => {
  const knownError = source.indexOf("const knownError =");
  const auth03Capture = source.indexOf('captureStage("AUTH-03", "invalid-credentials"', knownError);
  const validPassword = source.indexOf('getByLabel("Password").fill(password)', auth03Capture);
  const auth05Capture = source.indexOf('this.shot("AUTH-05")', validPassword);

  assert.ok(knownError >= 0, "known-account rejection was not asserted");
  assert.ok(auth03Capture > knownError, "AUTH-03 was not captured after the visible rejection");
  assert.ok(validPassword > auth03Capture, "valid login happened before AUTH-03 capture");
  assert.ok(auth05Capture > validPassword, "AUTH-05 was not captured after valid recovery");
  assert.match(source, /screenshot: auth03VisualStep\.screenshot,\s*visualSteps: \[auth03VisualStep\]/);
  assert.match(source, /requiredVisible: \["Log in to ProofShape", "Invalid email or password\."\]/);
});

test("public/auth report advertises the schema-v2 evidence envelope", () => {
  assert.match(source, /captureVisualStep/);
  assert.match(source, /releaseEvidence: \{ schemaVersion: 2, goldenPaths: this\.goldenPaths \}/);
});

test("only the signed-out AUTH-01 probe may use context.request", () => {
  const occurrences = [...source.matchAll(/context\.request/g)];
  const auth01 = source.indexOf('this.path("AUTH-01"');
  const auth02 = source.indexOf('this.path("AUTH-02"', auth01);

  assert.equal(occurrences.length, 1, "unexpected context.request traffic in public/auth runner");
  assert.ok(occurrences[0].index > auth01 && occurrences[0].index < auth02);
  assert.match(source.slice(auth01, auth02), /New cookie-free browser context/);
  assert.match(source.slice(auth01, auth02), /response\.status\(\) === 401/);
});

test("PUB-03 remains a genuinely public browser submission and retry", () => {
  const pub03 = source.indexOf('this.path("PUB-03"');
  const pub04 = source.indexOf('this.path("PUB-04"', pub03);
  assert.ok(pub03 >= 0 && pub04 > pub03, "PUB-03 block was not found");
  const block = source.slice(pub03, pub04);

  assert.match(block, /getByRole\("button", \{ name: "Send request" \}\)\.click\(\)/);
  assert.match(block, /this\.api\("\/api\/pilot\/request"/);
  assert.match(block, /pilot request returned \$\{response\.status\(\)\}/);
  assert.doesNotMatch(block, /context\.request|dash_session|["']authorization["']\s*:/i);
});
