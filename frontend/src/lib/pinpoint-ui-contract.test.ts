import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const workspace = fs.readFileSync(new URL("../components/workspace/PartWorkspace.tsx", import.meta.url), "utf8");
const dashboard = fs.readFileSync(new URL("../components/AnalysisDashboard.tsx", import.meta.url), "utf8");

test("production tabs stay clean until a physical defect is selected", () => {
  assert.match(workspace, /if \(!validation \|\| !selectedGroup\) return \[\]/);
  assert.doesNotMatch(workspace, /setSelectedIssueKey\(pinpointGroups\[0\]\.key\)/);
  assert.match(workspace, /markerLabel: "1"/);
  assert.match(workspace, /pinpointOverlays=\{tab === "routing" && selectedGroup/);
  assert.match(workspace, /Previous issue/);
  assert.match(workspace, /Next issue/);
});

test("issue list receives canonical physical defects with process implications", () => {
  assert.match(workspace, /canonicalIssues=\{canonicalIssues\}/);
  assert.match(workspace, /processImplications=\{processImplications\}/);
  assert.match(dashboard, /grouped by physical defect/);
});

test("selection is deep-linkable and the viewer owns a docked leader association", () => {
  assert.match(workspace, /searchParams\.set\("issue", key\)/);
  assert.match(workspace, /pinpointCallout=\{selectedIssue/);
  const viewer = fs.readFileSync(new URL("../components/ui/cad-viewer.tsx", import.meta.url), "utf8");
  assert.match(viewer, /data-testid="pinpoint-docked-callout"/);
  assert.match(viewer, /strokeWidth="1\.5"/);
  assert.match(viewer, /On the far side - drag to spin\./);
  assert.match(viewer, /pin\.severity === "error"[\s\S]*polygon\(50% 0,100% 50%,50% 100%,0 50%\)[\s\S]*polygon\(50% 0,100% 100%,0 100%\)/);
});
