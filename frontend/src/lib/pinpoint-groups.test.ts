import { test } from "node:test";
import assert from "node:assert/strict";
import { groupForIssueKey, groupPinpointIssues, pinpointLinkEvidence } from "./pinpoint-groups.ts";

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

test("matching evidence across processes becomes one group", () => {
  const groups = groupPinpointIssues([row("fdm#0", "fdm", [1, 2]), row("sla#0", "sla", [2, 3])]);
  assert.equal(groups.length, 1);
  assert.deepEqual(groups[0].faces, [1, 2, 3]);
  assert.deepEqual(groups[0].processes, ["fdm", "sla"]);
  assert.equal(groups[0].severity, "warning");
  assert.equal(groupForIssueKey(groups, "sla#0")?.key, groups[0].key);
});

test("different process evidence cannot inherit another process's advice or severity", () => {
  const base = row("fdm#0", "fdm", [1]);
  for (const change of [
    { severity: "error" as const }, { required_value: 1.2 },
    { measured_value: 0.4 }, { fix_suggestion: "Use a different process." },
    { message: "Another measured defect" },
  ]) {
    const other = row("sla#0", "sla", [1]);
    Object.assign(other.issue, change);
    const groups = groupPinpointIssues([base, other]);
    assert.equal(groups.length, 2);
    assert.notEqual(groups[0].key, groups[1].key);
    assert.deepEqual(groups.map((g) => g.processes), [["fdm"], ["sla"]]);
    assert.equal(groupForIssueKey(groups, other.key)?.issue, other.issue);
  }
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

test("issue links require the same mesh, process membership, locations and findings", async (t) => {
  const first = row("casting#0", "investment_casting", [1, 2]);
  const second = row("sand#0", "sand_casting", [3, 4]);
  second.issue.required_value = 3;
  const groups = groupPinpointIssues([first, second]);
  const evidence = await pinpointLinkEvidence(groups, "mesh-a");
  assert.match(evidence!, /^[a-f0-9]{64}$/);
  assert.equal(await pinpointLinkEvidence(structuredClone(groups), "mesh-a"), evidence);
  assert.notEqual(await pinpointLinkEvidence(groups, "mesh-b"), evidence);
  // Removing an earlier same-code finding reuses its old positional key.
  const removed = groupPinpointIssues([second]);
  assert.equal(removed[0].key, groups[0].key);
  assert.notEqual(await pinpointLinkEvidence(removed, "mesh-a"), evidence);
  for (const change of [
    { faces: [5, 6] }, { processes: ["die_casting"] },
    { issue: { ...groups[0].issue, required_value: 1.5 } },
    { issue: { ...groups[0].issue, severity: "error" as const } },
    { issue: { ...groups[0].issue, fix_suggestion: "Different manufacturing advice." } },
  ]) {
    assert.notEqual(await pinpointLinkEvidence([{ ...groups[0], ...change }, groups[1]], "mesh-a"), evidence);
  }
  assert.equal(await pinpointLinkEvidence(groups, undefined), null);
  t.mock.method(crypto.subtle, "digest", async () => { throw new Error("unavailable"); });
  assert.equal(await pinpointLinkEvidence(groups, "mesh-a"), null);
});
