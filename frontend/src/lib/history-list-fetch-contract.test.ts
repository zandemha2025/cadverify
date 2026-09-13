import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
for (const file of ["AnalysisHistoryTable.tsx", "CostDecisionHistoryTable.tsx"]) {
  test(`${file} loads after commit rather than mutating state during render`, () => {
    const source = readFileSync(new URL(`../components/${file}`, import.meta.url), "utf8");
    assert.match(source, /useEffect\(\(\) => \{/);
    assert.match(source, /void loadPage\(undefined, true\)/);
    assert.doesNotMatch(source, /if \(!initialized && !loading\) \{\s*loadPage\(undefined, true\);/);
  });
}
