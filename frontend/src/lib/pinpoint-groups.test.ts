import { test } from "node:test";
import assert from "node:assert/strict";
import { groupForIssueKey, groupPinpointIssues } from "./pinpoint-groups.ts";

const row = (key: string, process: string, faces: number[], severity: "error" | "warning" = "warning") => ({
  key,
  faces,
  issue: {
    code: "THIN_WALL",
    severity,
    message: "Thin wall",
    fix_suggestion: "Make the wall thicker.",
    process,
    region_center: [10, 10, 10] as [number, number, number],
    measured_value: 0.497,
    required_value: 0.8,
  },
});

test("same physical defect across processes becomes one group", () => {
  const groups = groupPinpointIssues([row("fdm#0", "fdm", [1, 2]), row("sla#0", "sla", [2, 3], "error")]);
  assert.equal(groups.length, 1);
  assert.deepEqual(groups[0].faces, [1, 2, 3]);
  assert.deepEqual(groups[0].processes, ["fdm", "sla"]);
  assert.equal(groups[0].severity, "error");
  assert.equal(groupForIssueKey(groups, "sla#0")?.key, groups[0].key);
});

test("different payload locations remain separate geometry issues", () => {
  const other = row("fdm#1", "fdm", [8]);
  other.issue.region_center = [8, 5, 6];
  assert.equal(groupPinpointIssues([row("fdm#0", "fdm", [1]), other]).length, 2);
});

test("unlocatable error and warning rows remain canonical but informational rows do not", () => {
  const unlocated = row("x", "fdm", []);
  delete unlocated.issue.region_center;
  unlocated.issue.severity = "warning";
  const info = row("i", "fdm", [1]) as ReturnType<typeof row>;
  (info.issue as { severity: string }).severity = "info";
  const groups = groupPinpointIssues([unlocated, info]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].key, "THIN_WALL|faces");
  assert.equal(groups[0].regionCenter, null);
  assert.deepEqual(groups[0].faces, []);
});
