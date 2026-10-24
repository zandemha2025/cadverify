import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("./RepairComparison.tsx", import.meta.url), "utf8");

test("repair comparison shows both path-verified verdicts and repaired download", () => {
  assert.match(source, /Re-verified through the same validation path/);
  assert.match(source, /Original verdict:/);
  assert.match(source, /Repaired verdict:/);
  assert.match(source, /Download repaired file/);
  assert.match(source, /repair_verification\.repaired_sha256/);
});

// Regression: the API explains refusals in `repair_details.reason`; reading only
// `.error` left users with "Repair not possible" and no explanation.
test("refused repair explains itself with the field the API sends", () => {
  assert.match(source, /repairFailureReason\(result\.repair_details\)/);
  assert.doesNotMatch(source, /repair_details\.error/);
});

// Regression: a repair that closes the shell by filling a bore (+10.4% volume)
// must not read as a clean "Mesh repaired" next to the download button.
test("repaired view surfaces the volume-change warning beside the download", () => {
  const banner = source.indexOf("{/* Repair summary banner */}");
  const download = source.indexOf("Download repaired file", banner);
  const warning = source.indexOf('data-testid="repair-volume-warning"', banner);
  const verification = source.indexOf("Re-verified through the same validation path");
  assert.ok(banner >= 0 && download > banner && warning > download && warning < verification);
  assert.match(source, /const volumeWarning = result\.repair_details\.volume_warning;/);
  assert.match(source, /role="alert"/);
  assert.match(source, /label=\{volumeWarning \? "Repaired — check features" : "Mesh repaired"\}/);
  assert.match(source, /formatVolumeChange\(result\.repair_details\.volume_change_pct\)/);
});
