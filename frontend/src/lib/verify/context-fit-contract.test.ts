import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const panel = fs.readFileSync(new URL("../../components/verify/context-fit-panel.tsx", import.meta.url), "utf8");
const viewer = fs.readFileSync(new URL("../../components/verify/context-fit-viewer.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("./context-fit.ts", import.meta.url), "utf8");

test("two-file roles and swap are explicit", () => {
  assert.match(panel, /Your part/);
  assert.match(panel, /The assembly it fits into/);
  assert.match(panel, /Switch part and context/);
  assert.match(panel, /setResult\(null\)/);
});

test("viewer uses solid part and 16 percent context ghost", () => {
  assert.match(viewer, /opacity=\{ghost \? 0\.16 : 1\}/);
  assert.match(panel, /Solid: your part/);
  assert.match(panel, /Ghost: assembly/);
});

test("product copy preserves sampled clearance and measured geometry fallback", () => {
  assert.match(api, /closest_sampled_gap_mm/);
  assert.match(panel, /Closest measured gap/);
  assert.match(panel, /centroid anchor only\. No substitute volume rendered/);
  assert.doesNotMatch(panel, /\bM[0-9]+\b/);
});

test("seating uncertainty and provenance stay first-class", () => {
  assert.match(panel, /Seating uncertain/);
  assert.doesNotMatch(panel, /AUTO_SEATING_UNCERTAIN/);
  assert.match(panel, /We couldn't seat this with confidence/);
  assert.match(panel, /Position set by you\./);
  assert.match(panel, /result\.limits\.map/);
  assert.match(panel, /MEASURED/);
});

test("selected issue text is docked at the viewport edge", () => {
  assert.match(panel, /data-testid="context-fit-docked-callout"/);
  assert.match(panel, /absolute left-2 right-2 top-2/);
  assert.match(panel, /selectedIssue === "collision"/);
});

test("structured repair next action reaches the user", () => {
  assert.match(api, /detail\?\.next_action/);
  assert.match(api, /`\$\{message\} \$\{nextAction\}`/);
});
