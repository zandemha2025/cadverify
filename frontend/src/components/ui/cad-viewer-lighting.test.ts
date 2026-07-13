import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Regression: ISSUE-CAD-001 — the standard viewer loaded Drei's remote studio
// HDR, which production CSP blocked and which could leave the preview unlit.
// Found by /qa on 2026-07-13.
// Report: outputs/human-sim/manufacturing-cad-adversarial/report.json
test("CAD viewer lighting is self-contained in every rendering mode", async () => {
  const source = await readFile(new URL("./cad-viewer.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(source, /<Environment\b[^>]*\bpreset\s*=/);
  assert.doesNotMatch(source, /raw\.githack\.com|https?:\/\//);
  assert.equal(source.match(/<StudioRig\s*\/>/g)?.length, 1);
});
