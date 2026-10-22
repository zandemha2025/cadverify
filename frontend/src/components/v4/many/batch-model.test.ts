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
  // Not on too little: two parts done of fifty says nothing yet.
  assert.equal(etaText(P({ total_items: 50, completed_items: 2, failed_items: 0, concurrency_limit: 4 }), now), "");
  // The last parts in flight: the slow ones finish last, so no time is guessed (oo-12).
  assert.equal(etaText(P({ total_items: 56, completed_items: 52, failed_items: 1, concurrency_limit: 4 }), now, ["part", "parts"]), "Last 3 parts");
  assert.equal(etaText(P({ total_items: 56, completed_items: 20, failed_items: 0, concurrency_limit: 4 }), new Date("2026-10-18T10:10:00Z").getTime()), "~18 min left");
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

test("a run counts its files one way everywhere: checked, not checked, to go (op-10, op-16)", async () => {
  const { runCounts, runCountsLine } = await import("./batch-model.ts");
  // Batch 23 after it stopped: 28 checked, 270 skipped. Never "296 of 296 checked".
  const stopped = runCounts(P({ status: "failed", total_items: 298, completed_items: 28, failed_items: 0, skipped_items: 270, pending_items: 0 }));
  assert.deepEqual(stopped, { total: 298, checked: 28, notChecked: 270, toGo: 0, checking: 0, unlisted: 0, unlistedChecked: 0, unlistedNotChecked: 0, unlistedToGo: 0 });
  assert.equal(runCountsLine(stopped), "28 of 298 checked · 270 not checked");
  const going = runCounts(P({ total_items: 298, completed_items: 8, failed_items: 1, skipped_items: 0, pending_items: 289 }));
  assert.equal(runCountsLine(going), "8 of 298 checked · 1 not checked · 289 to go");
  // Without the progress read, from the board's rows: a file checked body by body is one file.
  const rows = [
    { item_id: "A", bucket: "in_house" },
    { item_id: "B:1", bucket: "outside" },
    { item_id: "B:2", bucket: "in_house" },
    { item_id: "C", bucket: "not_checked" },
    { item_id: "D", bucket: "checking" },
  ];
  assert.deepEqual(runCounts(null, rows), { total: 4, checked: 2, notChecked: 1, toGo: 1, checking: 0, unlisted: 0, unlistedChecked: 0, unlistedNotChecked: 0, unlistedToGo: 0 });
});

test("a stopped run says when it stopped and what is left, in plain words (op-16)", async () => {
  const { stoppedLine } = await import("./batch-model.ts");
  const none = { checking: 0, unlisted: 0, unlistedChecked: 0, unlistedNotChecked: 0, unlistedToGo: 0 };
  const counts = { total: 298, checked: 28, notChecked: 270, toGo: 0, ...none };
  assert.equal(stoppedLine(counts), "28 of 298 checked; 270 not checked. Check them again.");
  assert.equal(stoppedLine({ total: 3, checked: 2, notChecked: 1, toGo: 0, ...none }), "2 of 3 checked; 1 not checked. Check it again.");
});

test("time left comes from the run's measured pace when the server has one (op-11)", () => {
  const now = new Date("2026-10-18T10:10:00Z").getTime();
  // 298 parts at 45 an hour with 270 to go: about 6 h.
  const p = P({ total_items: 298, completed_items: 28, failed_items: 0, pending_items: 270, concurrency_limit: 10, pace_per_hour: 45, eta_seconds: 21600 });
  assert.equal(etaText(p, now, ["part", "parts"]), "~6 h left at 45 parts an hour");
  assert.equal(etaText(P({ pace_per_hour: 7.5, eta_seconds: 2580 }), now, ["part", "parts"]), "~43 min left at 7.5 parts an hour");
  assert.equal(etaText(P({ pace_per_hour: 120, eta_seconds: 30, total_items: 90, pending_items: 60 }), now, ["part", "parts"]), "~30 s left at 120 parts an hour");
  assert.equal(etaText(P({ total_items: 298, pending_items: 270, pace_per_hour: 45, eta_seconds: 23400 }), now, ["part", "parts"]), "~6 h 30 min left at 45 parts an hour");
});

test("the work bar and the run page say the same thing about a run, and it only goes up (op-10)", async () => {
  const { runCounts, runWork } = await import("./batch-model.ts");
  const a = runWork(runCounts(P({ total_items: 298, completed_items: 6, failed_items: 2, skipped_items: 0, pending_items: 290 })));
  assert.deepEqual(a, { label: "Checking 298 parts", detail: "6 of 298 checked", progress: 8 / 298 });
  // With a parts list: the list's parts, and the files it doesn't name said apart; the bar covers every file.
  const listed = runWork(runCounts({ ...P({ total_items: 298 }), run_counts: { total: 296, checked: 6, not_checked: 2, to_go: 288, checking: 4, unlisted: 2, unlisted_checked: 1, unlisted_not_checked: 0, unlisted_to_go: 1 } } as never));
  assert.deepEqual(listed, { label: "Checking 296 parts", detail: "6 of 296 checked", progress: 9 / 298 });
  const b = runWork(runCounts(null, [{ item_id: "A", bucket: "in_house" }, { item_id: "B", bucket: "checking" }]));
  assert.deepEqual(b, { label: "Checking 2 parts", detail: "1 of 2 checked", progress: 0.5 });
});

test("Home's way back to a run says what the run page says: a run that checked parts and stopped is Stopped, never Didn't start (op-24)", async () => {
  const { lastRunLine } = await import("./batch-model.ts");
  const row = (o: Record<string, unknown>) => ({ batch_ulid: "B", status: "failed", total_items: 298, completed_items: 28, failed_items: 0, skipped_items: 270, created_at: null, ...o }) as never;
  // Batch 23 after it stopped at 16:55: 28 answered, 270 skipped.
  assert.equal(lastRunLine(row({})), "Stopped · 28 of 298 checked · 270 not checked");
  // A run that never checked a part didn't start.
  assert.equal(lastRunLine(row({ completed_items: 0, skipped_items: 298 })), "Didn’t start · 298 files");
  assert.equal(lastRunLine(row({ status: "processing", completed_items: 31, skipped_items: 0 })), "Running · 31 of 298 checked · 267 to go");
  assert.equal(lastRunLine(row({ status: "completed", total_items: 50, completed_items: 34, failed_items: 16, skipped_items: 0 })), "Finished · 34 of 50 checked · 16 not checked");
  assert.equal(lastRunLine(row({ status: "completed", total_items: 1, completed_items: 1, skipped_items: 0 })), "Finished · 1 of 1 checked");
  assert.equal(lastRunLine(row({ status: "cancelled", total_items: 50, completed_items: 10, skipped_items: 40 })), "Cancelled · 10 of 50 checked · 40 not checked");
});


test("one breakdown of a run's files everywhere: the parts list's, with files it doesn't name apart (op-28)", async () => {
  const { runCounts, runCountsLine, stoppedLine, apartLine, lastRunLine } = await import("./batch-model.ts");
  // Batch 23 stopped: 296 listed (28 checked, 268 not checked) and 2 files not on the list, not checked.
  const wire = { total: 296, checked: 28, not_checked: 268, to_go: 0, checking: 0, unlisted: 2, unlisted_checked: 0, unlisted_not_checked: 2, unlisted_to_go: 0 };
  const c = runCounts({ ...P({ status: "failed", total_items: 298, completed_items: 28, skipped_items: 270, failed_items: 0, pending_items: 0 }), run_counts: wire } as never);
  assert.equal(runCountsLine(c), "28 of 296 checked · 268 not checked · 2 files aren’t on your parts list");
  assert.equal(stoppedLine(c), "28 of 296 checked; 268 not checked. Check them again.");
  assert.equal(apartLine(c), "2 files that aren’t on your parts list weren’t checked either.");
  assert.equal(lastRunLine({ status: "failed", total_items: 298, completed_items: 28, failed_items: 0, skipped_items: 270, run_counts: wire } as never), "Stopped · 28 of 296 checked · 268 not checked · 2 files aren’t on your parts list");
  // The board's own rows give the same counts when the server's aren't there (an older API).
  const rows = [
    ...Array.from({ length: 28 }, (_, i) => ({ item_id: `L${i}`, bucket: "in_house", listed: true })),
    ...Array.from({ length: 268 }, (_, i) => ({ item_id: `N${i}`, bucket: "not_checked", listed: true })),
    { item_id: "X1", bucket: "not_checked", listed: false },
    { item_id: "X2", bucket: "not_checked", listed: false },
  ];
  assert.deepEqual(runCounts(null, { has_list: true, rows }), c);
  // Re-checking: queued and checking parts are still to go.
  const going = runCounts(null, { has_list: true, rows: [{ item_id: "A", bucket: "in_house", listed: true }, { item_id: "B", bucket: "checking", status: "processing", listed: true }, { item_id: "C", bucket: "checking", status: "pending", listed: true }, { item_id: "D", bucket: "checking", status: "pending", listed: false }] });
  assert.equal(runCountsLine(going), "1 of 3 checked · 2 to go · 1 file isn’t on your parts list");
  assert.equal(going.checking, 1);
  assert.equal(apartLine(going), null);
});


test("a stopped run says when and why it stopped, and a run stopped before reasons were kept says that (op-25)", async () => {
  const { stopWhy } = await import("./batch-model.ts");
  // Stopped by the sweep under the new code: its stored reason.
  assert.equal(
    stopWhy("16:55", "The run stopped before every part was checked: its files are no longer stored, so its parts can't be checked again here. Start a new run with them."),
    "The run stopped at 16:55: its files are no longer stored, so its parts can't be checked again here. Start a new run with them.",
  );
  assert.equal(stopWhy("16:55", "The run stopped before every part was checked: it made no progress after 3 restarts. Check the parts again."), "The run stopped at 16:55: it made no progress after 3 restarts. Check the parts again.");
  // Batch 23: stopped by the old code, no reason kept. Never nothing.
  assert.equal(stopWhy("16:55", null), "The run stopped at 16:55 before ScaleCAD kept a reason.");
  assert.equal(stopWhy(null, ""), "The run stopped before ScaleCAD kept a reason.");
  // An acronym keeps its case.
  assert.equal(stopWhy("09:10", "ZIP entries were unreadable"), "The run stopped at 09:10: ZIP entries were unreadable.");
});


test("no time left until the server has measured the run's pace, and a long one settles to the half hour (op-26)", async () => {
  const { leftWords } = await import("./batch-model.ts");
  const now = new Date("2026-10-22T19:11:55Z").getTime();
  // 19:11:55: three parts had landed together. The server is still measuring: no guess from the start time.
  const measuring = P({ total_items: 298, completed_items: 31, failed_items: 0, pending_items: 267, started_at: "2026-10-22T15:56:48Z", pace_per_hour: null, eta_seconds: null, pace_state: "measuring" });
  assert.equal(etaText(measuring, now, ["part", "parts"]), "Time left after 10 parts or 10 minutes");
  assert.equal(etaText(P({ pace_per_hour: null, eta_seconds: null, pace_state: "stalled" }), now, ["part", "parts"]), "No part finished in the last 30 minutes");
  // A server that gives the pace fields says when there is none: never the old guess from the start time.
  assert.equal(etaText(P({ pace_per_hour: null, eta_seconds: null }), now), "");
  // Long runs read to the half hour, so a steady run's estimate doesn't flicker by ten minutes.
  assert.deepEqual([leftWords(3 * 3600 + 14 * 60), leftWords(3 * 3600 + 16 * 60), leftWords(8.8 * 3600), leftWords(2 * 3600 + 14 * 60)], ["~3 h", "~3 h 30 min", "~9 h", "~2 h 10 min"]);
});
