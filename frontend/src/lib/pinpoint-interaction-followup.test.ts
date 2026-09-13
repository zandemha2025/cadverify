import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const workspace = readFileSync(new URL("../components/workspace/PartWorkspace.tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../components/ui/cad-viewer.tsx", import.meta.url), "utf8");
test("pinpoint selection supports keyboard, deselect, deep-link restore state, and URL sync", () => {
  assert.match(workspace, /event\.key === "Escape"/);
  assert.match(workspace, /event\.key === "ArrowLeft"/);
  assert.match(workspace, /event\.key === "ArrowRight"/);
  assert.match(workspace, /key === selectedIssueKey/);
  assert.match(workspace, /url\.searchParams\.delete\("issue"\)/);
  assert.match(workspace, /Issue link ready:/);
  assert.match(workspace, /Upload the original CAD file to restore this issue/);
  assert.match(workspace, /selectPinpoint\(hit\.key\)/);
});
test("marker has no competing hardcoded number and callout omits empty duplicate detail", () => {
  assert.doesNotMatch(workspace, /markerLabel: "1"/);
  assert.match(viewer, /pinpointCallout\.detail &&/);
  assert.match(viewer, /sr-only/);
});
