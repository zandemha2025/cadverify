import assert from "node:assert/strict";
import test from "node:test";
import {
  analysisIdOf,
  cancelText,
  doneFraction,
  etaText,
  filterCounts,
  laneItems,
  parseConcurrency,
  progressText,
  seconds,
  sortItems,
  zipProblem,
} from "./batch-model.ts";

const P = (o: Record<string, unknown> = {}) =>
  ({
    batch_ulid: "B1",
    status: "processing",
    input_mode: "direct_upload",
    total_items: 9,
    completed_items: 4,
    failed_items: 1,
    skipped_items: 0,
    pending_items: 4,
    concurrency_limit: 10,
    created_at: "2026-10-18T10:00:00Z",
    started_at: "2026-10-18T10:00:00Z",
    completed_at: null,
    ...o,
  }) as never;

const item = (o: Record<string, unknown>) =>
  ({
    item_ulid: String(o.filename),
    filename: "a.stl",
    status: "completed",
    priority: "normal",
    analysis_id: 1,
    analysis_url: null,
    verdict: "issues",
    best_process: "fdm",
    issue_count: 1,
    error_message: null,
    duration_ms: 100,
    created_at: null,
    ...o,
  }) as never;

test("progress line counts checked, failed and waiting, and drops waiting once final", () => {
  assert.equal(progressText(P()), "4 of 9 checked · 1 failed · 4 waiting");
  assert.equal(progressText(P({ status: "completed", pending_items: 0, completed_items: 8 })), "8 of 9 checked · 1 failed");
  assert.equal(doneFraction(P()), 5 / 9);
  assert.equal(doneFraction(P({ total_items: 0 })), 0);
});

test("ETA comes from the real rate and is empty when it can't be said", () => {
  const now = new Date("2026-10-18T10:00:50Z").getTime();
  assert.equal(etaText(P(), now), "~40 s left");
  assert.equal(etaText(P({ started_at: null }), now), "");
  assert.equal(etaText(P({ completed_items: 0, failed_items: 0 }), now), "");
  assert.equal(etaText(P({ status: "completed" }), now), "");
});

test("cancel question says in-progress items are skipped too", () => {
  assert.match(cancelText(P()), /^4 unfinished items will be skipped, including any in progress\. Finished results stay\. This can’t be undone\.$/);
  assert.match(cancelText(P({ pending_items: 1 })), /^1 unfinished item will/);
});

test("analysis id is read from the analysis url only", () => {
  assert.equal(analysisIdOf({ analysis_url: "/api/v1/analyses/01ABC" }), "01ABC");
  assert.equal(analysisIdOf({ analysis_url: null }), null);
});

test("sorting by name is natural, by time longest first, arrival unchanged", () => {
  const xs = [item({ filename: "b10.stl", duration_ms: 5 }), item({ filename: "b2.stl", duration_ms: 50 }), item({ filename: "a.stl", duration_ms: null })];
  assert.deepEqual(sortItems(xs, "name").map((x: { filename: string }) => x.filename), ["a.stl", "b2.stl", "b10.stl"]);
  assert.deepEqual(sortItems(xs, "time").map((x: { filename: string }) => x.filename), ["b2.stl", "b10.stl", "a.stl"]);
  assert.deepEqual(sortItems(xs, "arrival"), xs);
});

test("filter counts split pending and processing only when every item is loaded", () => {
  const loaded = [item({ status: "pending" }), item({ status: "processing" }), item({ status: "completed" })];
  const c = filterCounts(P(), loaded, false);
  assert.equal(c.all, 9);
  assert.equal(c.pending, null);
  assert.equal(c.completed, 4);
  const d = filterCounts(P(), loaded, true);
  assert.equal(d.pending, 1);
  assert.equal(d.processing, 1);
  assert.equal(filterCounts(P({ status: "completed", pending_items: 0 }), [], false).pending, 0);
});

test("lanes: matched parts go to their bucket, DFM-blocked ruled-out parts to design change, unmatched to unknown", () => {
  const row = (verdict: string, gap: unknown = null) => ({ part_key: "k", filename: "x", makeability: { verdict, stale: false, gap } });
  const lookup = new Map([
    ["A", { bucket: "makeable_in_house", row: row("makeable_in_house") }],
    ["B", { bucket: "not_makeable", row: row("not_makeable", { gate: "dfm", gap: [{ gate: "dfm", axis: "THIN_WALL", human: "Walls under 0.8 mm" }] }) }],
    ["C", { bucket: "not_makeable", row: row("environment_excluded") }],
    ["D", { bucket: "needs_redesign_soon", row: row("brand_new_verdict") }],
  ]);
  const items = [
    item({ filename: "a", analysis_url: "/api/v1/analyses/A" }),
    item({ filename: "b", analysis_url: "/api/v1/analyses/B" }),
    item({ filename: "c", analysis_url: "/api/v1/analyses/C" }),
    item({ filename: "d", analysis_url: "/api/v1/analyses/D" }),
    item({ filename: "e", analysis_url: "/api/v1/analyses/E" }),
    item({ filename: "f", status: "failed", analysis_url: null }),
  ];
  const lanes = laneItems(items, lookup as never);
  const names = (k: string) => (lanes.get(k) ?? []).map((x) => x.item.filename);
  assert.deepEqual(names("makeable_in_house"), ["a"]);
  assert.deepEqual(names("design_change"), ["b"]);
  assert.deepEqual(names("not_makeable"), ["c"]);
  assert.deepEqual(names("needs_redesign_soon"), ["d"]);
  assert.deepEqual(names("unknown"), ["e"]);
  assert.equal([...lanes.values()].flat().length, 5);
});

test("form checks: zip type and size, files at a time is a whole number 1 to 12", () => {
  assert.equal(zipProblem({ name: "parts.ZIP", size: 10 }), null);
  assert.match(zipProblem({ name: "parts.rar", size: 10 })!, /\.zip/);
  assert.match(zipProblem({ name: "p.zip", size: 6 * 1024 ** 3 })!, /5 GB/);
  assert.equal(parseConcurrency("12"), 12);
  assert.equal(parseConcurrency(" 3 "), 3);
  for (const bad of ["0", "13", "2.5", "", "abc", "-1"]) assert.equal(parseConcurrency(bad), null);
});

test("durations", () => {
  assert.equal(seconds(40), "<0.1 s");
  assert.equal(seconds(1234), "1.2 s");
  assert.equal(seconds(null), "—");
});
