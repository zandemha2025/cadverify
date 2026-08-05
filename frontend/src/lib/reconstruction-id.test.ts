import assert from "node:assert/strict";
import test from "node:test";

import { createReconstructionSubmissionId } from "./reconstruction-id.ts";

test("reconstruction submission IDs are valid 26-character Crockford ULIDs", () => {
  const id = createReconstructionSubmissionId(1_700_000_000_000, (bytes) => {
    bytes.fill(0xab);
  });

  assert.equal(id.length, 26);
  assert.match(id, /^[0-9A-HJKMNP-TV-Z]{26}$/);
  assert.doesNotMatch(id, /[ILOU]/);
});

test("time and entropy both contribute to reconstruction submission identity", () => {
  const zeroes = (bytes: Uint8Array) => bytes.fill(0);
  const ones = (bytes: Uint8Array) => bytes.fill(1);

  const first = createReconstructionSubmissionId(1_700_000_000_000, zeroes);
  const later = createReconstructionSubmissionId(1_700_000_000_001, zeroes);
  const random = createReconstructionSubmissionId(1_700_000_000_000, ones);

  assert.notEqual(first, later);
  assert.notEqual(first, random);
});
