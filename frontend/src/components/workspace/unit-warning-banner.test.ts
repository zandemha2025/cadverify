import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Regression: ISSUE-CAD-002 — the engine returned IMPLAUSIBLE_VOLUME but both
// live workspaces silently omitted it, so a user could trust a 16,000x unit error.
// Found by /qa on 2026-07-13.
// Report: outputs/human-sim/manufacturing-cad-adversarial/report.json
test("unit ambiguity stays visible in staged and legacy workspaces", async () => {
  const [banner, staged, legacy] = await Promise.all([
    readFile(new URL("./UnitWarningBanner.tsx", import.meta.url), "utf8"),
    readFile(new URL("./hero/PartHero.tsx", import.meta.url), "utf8"),
    readFile(new URL("./PartWorkspace.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(banner, /role="alert"/);
  assert.match(banner, /data-testid="cad-unit-warning"/);
  assert.match(banner, /Confirm CAD source units before using this decision\./);
  assert.match(banner, /choose Millimetres or Inches/);
  assert.match(staged, /<UnitWarningBanner warnings=\{report\?\.unit_warnings\} \/>/);
  assert.match(legacy, /<UnitWarningBanner warnings=\{report\?\.unit_warnings\} \/>/);
});
