import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./direct-s3-batch-browser.mjs", import.meta.url), "utf8");

test("direct S3 browser gate owns success, isolation, and interrupted-upload branches", () => {
  for (const id of ["S3-01", "S3-02", "S3-03", "S3-04"]) {
    assert.match(source, new RegExp(`id: ["']${id}["']`));
  }
  assert.match(source, /part_count >= 2/);
  assert.match(source, /network\.refresh\.length >= 1/);
  assert.match(source, /foreignUpload\.status, 404/);
  assert.match(source, /rejectedPuts, 4/);
  assert.match(source, /body\?\.status, "aborted"/);
  assert.match(source, /body\?\.status, "consumed"/);
  assert.match(source, /terminalScreenshot, fullPage: false/);
  assert.match(source, /extraHTTPHeaders: \{ "x-real-ip": testClientIp\(\) \}/);
  assert.match(source, /credentials: "same-origin"/);
  assert.doesNotMatch(source, /context\.request/);
  assert.match(source, /frontendBuildId, binding\.identity\.buildId/);
  assert.match(source, /apiBuildId, binding\.identity\.buildId/);
});

test("direct S3 evidence rejects provider coordinates and browser-persisted credentials", () => {
  for (const key of ["bucket", "object_key", "multipart_upload_id"]) {
    assert.match(source, new RegExp(`["']${key}["']`));
  }
  assert.match(source, /AWS_ACCESS_KEY_ID\|AWS_SECRET_ACCESS_KEY/);
  assert.match(source, /expectedFaultConsoleErrors/);
  assert.match(source, /assert\.deepEqual\(unexpectedConsoleErrors, \[\]\)/);
  assert.match(source, /requestFailures, \[\]/);
});
