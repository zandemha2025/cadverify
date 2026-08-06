import { test } from "node:test";
import assert from "node:assert/strict";
import {
  VERIFY_PART_CAD_INPUT,
  GROUND_TRUTH_CSV_INPUT,
  FILE_INPUT_IDENTITIES,
  fileInputIdentitiesAreDistinct,
} from "./file-inputs.ts";

test("the CAD uploader and ground-truth CSV importer share no queryable handle", () => {
  // W7-1: co-located hidden file inputs must never collide on any identity, or
  // a CSV import can land on the CAD uploader (400 "unsupported file type").
  assert.notEqual(VERIFY_PART_CAD_INPUT.id, GROUND_TRUTH_CSV_INPUT.id);
  assert.notEqual(VERIFY_PART_CAD_INPUT.name, GROUND_TRUTH_CSV_INPUT.name);
  assert.notEqual(VERIFY_PART_CAD_INPUT.testId, GROUND_TRUTH_CSV_INPUT.testId);
  assert.notEqual(VERIFY_PART_CAD_INPUT.ariaLabel, GROUND_TRUTH_CSV_INPUT.ariaLabel);
});

test("fileInputIdentitiesAreDistinct is true for the shipped identities", () => {
  assert.equal(fileInputIdentitiesAreDistinct(), true);
  assert.equal(fileInputIdentitiesAreDistinct(FILE_INPUT_IDENTITIES), true);
});

test("fileInputIdentitiesAreDistinct catches a shared handle", () => {
  assert.equal(
    fileInputIdentitiesAreDistinct([
      VERIFY_PART_CAD_INPUT,
      { ...GROUND_TRUTH_CSV_INPUT, id: VERIFY_PART_CAD_INPUT.id },
    ]),
    false,
  );
});

test("the ground-truth CSV importer is labelled as a quote/actuals import, not CAD", () => {
  assert.match(GROUND_TRUTH_CSV_INPUT.ariaLabel, /csv/i);
  assert.doesNotMatch(GROUND_TRUTH_CSV_INPUT.ariaLabel, /\bCAD\b/);
});
