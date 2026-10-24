/**
 * The sample part never uses a check because the server knows its exact bytes
 * (SAMPLE_PART_SHA256 in backend/src/auth/validation_caps.py). This pins the
 * generator to that hash: change the sample and this fails until the backend
 * constant (and its twin test) change with it.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { sampleBracketFile } from "./sample-cad.ts";

const SAMPLE_PART_SHA256 = "d36d3e945b5f12779dc6d930663ccced8ad90b68579b2380b21f919c0fbee17a";

test("the sample bracket is byte for byte the file the server never counts", async () => {
  const file = sampleBracketFile();
  const bytes = Buffer.from(await file.arrayBuffer());
  assert.equal(file.name, "sample-routing-bracket.stl");
  assert.equal(bytes.length, 2463);
  assert.equal(createHash("sha256").update(bytes).digest("hex"), SAMPLE_PART_SHA256);
});

test("two calls make the same bytes", async () => {
  const a = Buffer.from(await sampleBracketFile().arrayBuffer());
  const b = Buffer.from(await sampleBracketFile().arrayBuffer());
  assert.ok(a.equals(b));
});
