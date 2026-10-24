/**
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/lib/api/part-upload-plan.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { RESUME_TTL_MS, backoffMs, freshRecord, partRange, partTarget, resumeKey, retryableStatus, type ResumeRecord } from "./part-upload-plan.ts";

test("a file is the same upload when its name, size and modified time match", () => {
  const a = resumeKey({ name: "frame.step", size: 1_500_000_000, lastModified: 1700000000000 });
  assert.equal(a, resumeKey({ name: "frame.step", size: 1_500_000_000, lastModified: 1700000000000 }));
  assert.notEqual(a, resumeKey({ name: "frame.step", size: 1_500_000_001, lastModified: 1700000000000 }));
  assert.notEqual(a, resumeKey({ name: "frame.step", size: 1_500_000_000, lastModified: 1700000000001 }));
});

test("parts cover the file exactly, the last one short", () => {
  const size = 16 * 1024 * 1024;
  const total = 2 * size + 123;
  assert.deepEqual(partRange(1, size, total), [0, size]);
  assert.deepEqual(partRange(2, size, total), [size, 2 * size]);
  assert.deepEqual(partRange(3, size, total), [2 * size, total]);
});

test("a relay part goes through the proxy; a presigned URL goes as is", () => {
  assert.equal(partTarget("/api/v1/uploads/01ABC/parts/3", "/api/proxy"), "/api/proxy/uploads/01ABC/parts/3");
  const s3 = "https://bucket.s3.us-east-1.amazonaws.com/x?X-Amz-Signature=abc";
  assert.equal(partTarget(s3, "/api/proxy"), s3);
});

test("retries back off and only on errors worth retrying", () => {
  assert.equal(backoffMs(1, () => 0.5), 1000);
  assert.equal(backoffMs(4, () => 0.5), 8000);
  assert.equal(backoffMs(10, () => 0.5), 20_000);
  for (const s of [0, 408, 429, 500, 502, 503]) assert.equal(retryableStatus(s), true, String(s));
  for (const s of [400, 401, 404, 409, 413, 422]) assert.equal(retryableStatus(s), false, String(s));
});

test("a remembered upload is forgotten after a day", () => {
  const r: ResumeRecord = { key: "k", idem: "part-1", sha256: "a".repeat(64), uploadId: "U", name: "a.step", size: 1, savedAt: 0 };
  assert.equal(freshRecord(r, RESUME_TTL_MS - 1), r);
  assert.equal(freshRecord(r, RESUME_TTL_MS + 1), null);
});
