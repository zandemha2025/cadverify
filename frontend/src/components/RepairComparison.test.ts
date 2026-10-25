import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("repair comparison shows both path-verified verdicts and repaired download", () => {
  const source = readFileSync(new URL("./RepairComparison.tsx", import.meta.url), "utf8");
  assert.match(source, /Re-verified through the same validation path/);
  assert.match(source, /Original verdict:/);
  assert.match(source, /Repaired verdict:/);
  assert.match(source, /Download repaired file/);
  assert.match(source, /repair_verification\.repaired_sha256/);
});
