import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./compare-rfq-key-golden-matrix.mjs", import.meta.url),
  "utf8",
);

test("authenticated setup and dashboard assertions stay inside the browser proxy", () => {
  assert.match(source, /async function inPageProxyFetch\(page, pathname/);
  assert.match(source, /fetch\(pathname, \{/);
  assert.match(source, /credentials:\s*["']same-origin["']/);
  assert.match(source, /pathname\.startsWith\(["']\/api\/proxy\/["']\)/);
  assert.match(source, /seedRetainedCadThroughBrowserProxy/);
  assert.match(source, /inPageProxyFetch\(actor\.page, ["']\/api\/proxy\/batch["']/);
  assert.match(source, /new File\(\[bytes\]/);
  assert.match(source, /\{ name: ["']job_type["'], value: ["']cost["'] \}/);
  assert.match(source, /\/api\/proxy\/batch\/\$\{batchId\}\/results\/csv/);
  assert.match(source, /\/api\/proxy\/cost-decisions\/\$\{decisionId\}/);
  assert.doesNotMatch(source, /UPDATE batch_items AS item SET cost_decision_id/);
  assert.match(source, /inPageProxyFetch\(actor\.page, ["']\/api\/proxy\/keys["']\)/);
  assert.match(source, /["']\/api\/proxy\/cost-decisions\?limit=1["']/);
  assert.doesNotMatch(source, /actor\.context\.request\.get\(["']\/api\/proxy/);
});

test("direct bearer rejection remains a backend authorization oracle", () => {
  assert.equal(source.match(/actor\.context\.request\.get\(/g)?.length, 1);
  assert.match(source, /apiUrl \+ ["']\/api\/v1\/cost-decisions\?limit=10["']/);
  assert.match(source, /Authorization:\s*["']Bearer ["'] \+ token/);
  for (const oracle of [
    "created bearer authorization",
    "rotated old token rejection status",
    "rotated old token rejection code",
    "rotation replacement authorization",
    "revoked replacement rejection status",
    "revoked replacement rejection code",
    "dashboard session remains authorized after key rejection",
  ]) {
    assert.ok(source.includes(oracle), `runner omitted authorization oracle: ${oracle}`);
  }
});

test("WORK-08 keeps exact raw-CAD, archive, PDF, and numeric contracts", () => {
  assert.match(source, /zipSync\(/);
  assert.match(source, /retained CAD setup authorization status/);
  assert.match(source, /RFQ raw CAD included["'], pkg\.raw_cad_included, true/);
  assert.match(source, /RFQ retained raw payload count["'], pkg\.metadata\.raw_payload_count, 1/);
  assert.match(source, /retained raw CAD bytes are exact/);
  assert.match(source, /sha256\(entries\[retainedRawName\]\)/);
  assert.match(source, /waitForEvent\(["']download["']/);
  assert.match(source, /download\.saveAs\(artifacts\.rfqZip\)/);
  assert.match(source, /unzipSync\(new Uint8Array\(zipBytes\)\)/);
  assert.match(source, /pdftotext/);
  for (const exactValue of [
    "RFQ selected item count",
    "RFQ approved count",
    "RFQ stale count",
    "RFQ unvalidated count",
    "visible RFQ summary counts",
    "RFQ CSV exact raw CAD flags",
    "supplier PDF repeated raw-CAD warning count",
  ]) {
    assert.ok(source.includes(exactValue), `runner omitted numeric/content oracle: ${exactValue}`);
  }
  assert.doesNotMatch(source, /pkg\.raw_cad_included\s*\|\|/);
  assert.doesNotMatch(source, /keyList\.status\s*===\s*401/);
});
