import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./manufacturing-cad-adversarial.mjs", import.meta.url),
  "utf8",
);

function stringArray(name) {
  const match = source.match(new RegExp(`const ${name} = \\[(.*?)\\];`, "s"));
  assert.ok(match, `${name} declaration is missing`);
  return [...match[1].matchAll(/"([A-Z]+-\d+)"/g)].map((item) => item[1]);
}

test("manufacturing and adversarial CAD paths use disjoint release evidence maps", () => {
  assert.deepEqual(stringArray("EXACT_GOLDEN_IDS"), [
    "ENT-01",
    "VER-05",
    "WORK-01",
    "WORK-02",
    "FAIL-01",
    "FAIL-02",
  ]);
  assert.deepEqual(stringArray("MANUFACTURING_SUBPATH_IDS"), [
    "MFG-01",
    "MFG-02",
    "MFG-03",
    "MFG-04",
    "MFG-05",
    "MFG-06",
  ]);
  assert.deepEqual(stringArray("SUPPLEMENTAL_CAD_IDS"), [
    "CAD-01",
    "CAD-02",
    "CAD-03",
    "CAD-04",
    "CAD-05",
    "CAD-06",
    "CAD-07",
    "CAD-08",
    "CAD-09",
  ]);
  assert.match(source, /Object\.fromEntries\(EXACT_GOLDEN_IDS\.map/);
  assert.match(source, /Object\.fromEntries\(SUPPLEMENTAL_CAD_IDS\.map/);
  assert.doesNotMatch(source, /PUBLISHED_GOLDEN_IDS/);
});

test("every owned browser path emits the common evidence envelope", () => {
  const expected = [
    ...stringArray("MANUFACTURING_SUBPATH_IDS"),
    ...stringArray("EXACT_GOLDEN_IDS"),
    ...stringArray("SUPPLEMENTAL_CAD_IDS"),
  ].sort();
  const authored = [...source.matchAll(/await recordPath\(page, \{\s*id: "([A-Z]+-\d+)"/g)]
    .map((item) => item[1])
    .sort();

  assert.deepEqual(authored, expected);
  assert.match(source, /makeGoldenPathEvidence\(\{/);
  assert.match(source, /const buildIdentity = captureBuildIdentity\(repoRoot\)/);
  assert.match(source, /consoleErrors: pathConsoleErrors/);
  assert.match(source, /requestFailures: pathRequestFailures/);
});

test("CAD evidence detects remote lighting and proves rendered assembly bytes and summary", () => {
  assert.match(source, /raw\\\.githack\\\.com\|drei-assets/);
  assert.match(source, /forbiddenCadAssetRequests\.push/);
  assert.match(source, /"remote CAD lighting requests"/);
  assert.match(source, /glbResponse\.headers\(\)\["x-assembly-glb-bytes"\]/);
  assert.match(source, /data-render-state/);
  assert.match(source, /PER-PART ANALYSIS — REAL/);
  assert.match(source, /analysisBody\?\.analysis\?\.analysis_summary/);
  assert.match(source, /"combined assembly GLB is non-empty"/);
});

test("expected HTTP rejections are captured separately from JavaScript errors", () => {
  assert.match(source, /isNetworkStatusConsoleMessage\(entry\.text\)/);
  assert.match(source, /if \(response\.status\(\) >= 400\)/);
  assert.match(source, /"HTTP error response count"/);
  assert.match(source, /expectedHttpErrorCount: 1,[\s\S]*id: "CAD-08"/);
});
