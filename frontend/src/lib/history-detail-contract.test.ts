import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Regression: WORK-10 — History consumed field names the API did not return,
// making row navigation target /analyses/undefined and omitting decision links.
// Found by /qa on 2026-07-13.
test("history detail renders persisted analysis fields and decision links", async () => {
  const [page, api] = await Promise.all([
    readFile(new URL("../app/(app)/analyses/[id]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("./api.ts", import.meta.url), "utf8"),
  ]);

  assert.match(api, /ulid: string/);
  assert.match(api, /overall_verdict:/);
  assert.match(api, /analysis_time_ms: number/);
  assert.match(api, /decision_links: Array/);
  assert.match(page, /Linked cost decisions/);
  assert.match(page, /router\.push\(decision\.url\)/);
  assert.match(page, /<AnalysisDashboard result=\{analysis\.result_json\} \/>/);
});
