import test from "node:test";
import assert from "node:assert/strict";
import { formatVolumeCm3 } from "./geometry-display.ts";
import { geometryIssueLocation } from "./verify/geometry-failure.ts";
import type { Issue } from "./api";

test("unmeasurable volume never masquerades as a measured zero", () => {
  for (const volume of [0, -1, NaN, Infinity, null, undefined]) {
    assert.equal(formatVolumeCm3(volume, true), "Volume unavailable");
  }
  assert.equal(formatVolumeCm3(12, false), "Volume unavailable");
  assert.equal(formatVolumeCm3(12, undefined), "Volume unavailable");
  assert.equal(formatVolumeCm3(6, true), "6.00 cm³");
  assert.equal(formatVolumeCm3(0.0001, true), "< 0.01 cm³");
});

test("location labels disclose sampled edges and do not invent locations", () => {
  const issue = { code: "NON_WATERTIGHT", severity: "error", message: "Open mesh", fix_suggestion: null } as Issue;
  assert.match(geometryIssueLocation(issue), /no exact location/);
  assert.equal(geometryIssueLocation({ ...issue, edge_segments: [[[0, 0, 0], [1, 0, 0]]], edge_segment_count: 10 }), "1 of 10 affected edges highlighted");
  assert.match(geometryIssueLocation({ ...issue, region_center: [1, 2, 3] }), /one detected location/);
});
