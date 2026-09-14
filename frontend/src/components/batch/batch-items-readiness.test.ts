import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("batch detail actions stay synchronized with visible item readiness", async () => {
  const tableSource = await readFile(
    new URL("./BatchItemsTable.tsx", import.meta.url),
    "utf8",
  );
  const pageSource = await readFile(
    new URL("../../app/(app)/batch/[id]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(tableSource, /data-batch-items-state=\{loadState\}/);
  assert.match(tableSource, /aria-busy=\{loading \|\| undefined\}/);
  assert.match(tableSource, /onLoadStateChange\?\.\("loading"\)/);
  assert.match(tableSource, /onLoadStateChange\?\.\("ready"\)/);
  assert.match(tableSource, /onLoadStateChange\?\.\("error"\)/);
  assert.match(pageSource, /loading=\{itemsLoadState === "loading" \|\| downloadingCsv\}/);
  assert.match(pageSource, /onLoadStateChange=\{setItemsLoadState\}/);
});

test("skipped batch rows show their stored reason without expansion", async () => {
  const source = await readFile(new URL("./BatchItemsTable.tsx", import.meta.url), "utf8");
  assert.match(source, /item\.status === "skipped" \|\| expanded/);
  assert.match(source, /`Skipped: \$\{item\.error_message\}`/);
  assert.match(source, /item\.status !== "skipped"/);
});
