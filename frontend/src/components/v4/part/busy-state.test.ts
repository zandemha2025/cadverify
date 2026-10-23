import test from "node:test";
import assert from "node:assert/strict";
import type { ValidationResult } from "@/lib/api";

import {
  STILL_BUSY_TITLE,
  WAITING_FOR_ROOM,
  busyMeta,
  busyReopenLabel,
  busyTitle,
  busyView,
  shownWait,
  stillBusyMeta,
  type BusyWaits,
} from "./busy-state.ts";
import { progressSteps } from "./model.ts";
import type { BusyKind, BusyStep, BusyWait } from "../../../lib/verify/busy.ts";

const T = 1_700_000_000_000;
const wait = (untilS: number, kind: BusyKind = "server", attempt = 1): BusyWait => ({ kind, attempt, since: T, until: T + untilS * 1000 });

test("the countdown reads 'ScaleCAD is busy. Checking again in 8 s…', down to 'now…'", () => {
  const v = { step: "validate" as BusyStep, wait: wait(8) };
  assert.equal(busyTitle(v, T), "ScaleCAD is busy. Checking again in 8 s…");
  assert.equal(busyTitle(v, T + 300), "ScaleCAD is busy. Checking again in 8 s…");
  assert.equal(busyTitle(v, T + 1500), "ScaleCAD is busy. Checking again in 7 s…");
  assert.equal(busyTitle(v, T + 7001), "ScaleCAD is busy. Checking again in 1 s…");
  assert.equal(busyTitle(v, T + 8000), "ScaleCAD is busy. Checking again now…");
  assert.equal(busyTitle({ step: "probe", wait: wait(5) }, T), "ScaleCAD is busy. Checking again in 5 s…");
  assert.equal(busyTitle({ step: "cost", wait: wait(5) }, T), "ScaleCAD is busy. Checking again in 5 s…");
  assert.equal(busyReopenLabel({ phase: "waiting", step: "validate", wait: wait(8) }, T), "Busy · checking again in 8 s");
});

test("one state for the whole check: its own requests first, the soonest try of those", () => {
  const waits: BusyWaits = { preview: wait(2), validate: wait(6) };
  assert.equal(shownWait(waits)?.step, "validate");
  assert.equal(shownWait({ validate: wait(6), cost: wait(3) })?.step, "cost");
  assert.equal(shownWait({ preview: wait(4) })?.step, "preview");
  assert.equal(shownWait({}), null);
  assert.equal(shownWait(null), null);
  // Only the 3D view waiting: said as that, not as the check waiting.
  assert.match(busyTitle({ step: "preview", wait: wait(4) }, T), /^The 3D view is waiting for room\. Trying again in 4 s…$/);
});

test("waiting, then still busy: the check's, and the prices' after the process checks", () => {
  assert.deepEqual(busyView({ busy: { probe: wait(5) } }), { phase: "waiting", step: "probe", wait: { ...wait(5), step: "probe" } });
  const check = busyView({ busy: {}, failure: { kind: "busy", step: "probe", busy: "server", waitedMs: 181_000 } });
  assert.deepEqual(check, { phase: "still", still: { step: "probe", kind: "server", waitedMs: 181_000 } });
  const prices = busyView({ busy: {}, result: { cost: null, costBusy: { kind: "server", waitedMs: 179_500 } } });
  assert.deepEqual(prices, { phase: "still", still: { step: "cost", kind: "server", waitedMs: 179_500 } });
  // Priced after all, or being retried: not "still busy" any more.
  assert.equal(busyView({ busy: {}, result: { cost: { ok: 1 }, costBusy: { kind: "server", waitedMs: 1 } } }), null);
  assert.equal(busyView({ busy: {}, costRetrying: true, result: { cost: null, costBusy: { kind: "server", waitedMs: 1 } } }), null);
  // The check gave up: that's the state, not its 3D view's last wait.
  assert.equal(busyView({ busy: { preview: wait(3) }, failure: { kind: "busy", step: "validate", busy: "server", waitedMs: 170_000 } })?.phase, "still");
  // A wait that's open wins over an older "still busy".
  assert.equal(busyView({ busy: { cost: wait(5) }, result: { cost: null, costBusy: { kind: "server", waitedMs: 1 } } })?.phase, "waiting");
  // Not busy: nothing to show (an interruption or a file problem has its own words).
  assert.equal(busyView({ busy: {}, failure: { kind: "interrupted" } }), null);
  assert.equal(busyView({ busy: {}, failure: { kind: "unreadable" } }), null);
  assert.equal(busyView(null), null);
});

test("still busy: the brief's words, how long it asked, what didn't run", () => {
  assert.equal(STILL_BUSY_TITLE, "Still busy. Your file is kept; try again in a minute.");
  assert.equal(stillBusyMeta({ step: "validate", kind: "server", waitedMs: 182_000 }), "ScaleCAD asked again for 3 minutes and had no room. Nothing was checked.");
  assert.equal(stillBusyMeta({ step: "cost", kind: "server", waitedMs: 179_000 }), "ScaleCAD asked again for 3 minutes and had no room. The process checks are ready; prices haven't run.");
  assert.equal(stillBusyMeta({ step: "probe", kind: "org", waitedMs: 20_000 }), "ScaleCAD asked again for 1 minute and had no room. Nothing was checked.");
  assert.equal(busyReopenLabel({ phase: "still", still: { step: "probe", kind: "server", waitedMs: 1 } }, T), "Still busy · Show");
});

test("busy never reads as a file problem or an error (D1, D2)", () => {
  const FILE_OR_ERROR = /can.?t read|couldn.?t read|no surfaces|fix in cad|re-?export|corrupt|invalid|unsupported|tessellat|didn.?t finish|interrupted|error|failed|usage and plans|allowance/i;
  const lines: string[] = [STILL_BUSY_TITLE, WAITING_FOR_ROOM];
  for (const step of ["probe", "validate", "cost", "preview"] as BusyStep[]) {
    for (const kind of ["server", "org"] as BusyKind[]) {
      lines.push(busyTitle({ step, wait: wait(5, kind) }, T), busyTitle({ step, wait: wait(5, kind) }, T + 9000), busyMeta({ step, wait: wait(5, kind) }));
      lines.push(stillBusyMeta({ step, kind, waitedMs: 180_000 }));
    }
  }
  for (const line of lines) assert.doesNotMatch(line, FILE_OR_ERROR, line);
  // Whose room it is, plainly: the server's, or this organization's share.
  assert.match(busyMeta({ step: "validate", wait: wait(5, "server") }), /^ScaleCAD's servers are full right now\. This isn't about your file/);
  assert.match(busyMeta({ step: "validate", wait: wait(5, "org") }), /^Your organization already has as many checks running/);
  assert.match(busyMeta({ step: "cost", wait: wait(5) }), /The process checks are ready; prices start once there's room/);
});

const V = {
  geometry: { bounding_box_mm: [80, 30, 25], volume_mm3: 28_000, is_watertight: true, faces: 10 },
  process_scores: [],
  best_process: "fdm",
  universal_issues: [],
} as unknown as ValidationResult;
const base = { fileName: "RFS-21368.step", sample: false, validation: null, cost: null, costError: null, geometryInvalid: null, done: false };

test("progress while busy says 'Waiting for room', never a red 'Didn't finish' (D3)", () => {
  const measuring = progressSteps({ ...base, busy: { step: "measure", live: true } });
  assert.deepEqual(measuring.map((s) => [s.t, s.d, s.state]).slice(0, 3), [
    ["Received", "RFS-21368.step · STEP", "done"],
    ["Measured", WAITING_FOR_ROOM, "now"],
    ["Process chosen", "Waiting", "wait"],
  ]);
  const stillMeasuring = progressSteps({ ...base, done: true, busy: { step: "measure", live: false } });
  assert.equal(stillMeasuring[1].d, WAITING_FOR_ROOM);
  assert.equal(stillMeasuring[1].state, "wait");
  // Prices still busy after the waiting: the run's cost error is the busy refusal, yet nothing reads as failed.
  const pricing = progressSteps({ ...base, validation: V, costError: "Too many verification requests were sent. Try again in 5 seconds.", done: true, busy: { step: "price", live: false } });
  assert.deepEqual(pricing.map((s) => s.state), ["done", "done", "wait", "wait", "wait"]);
  assert.equal(pricing[2].d, WAITING_FOR_ROOM);
  for (const s of [...measuring, ...stillMeasuring, ...pricing]) {
    assert.notEqual(s.state, "bad", s.t);
    assert.doesNotMatch(s.d, /didn.?t finish|not computed/i, s.t);
  }
  const live = progressSteps({ ...base, validation: V, busy: { step: "price", live: true } });
  assert.deepEqual([live[2].d, live[2].state], [WAITING_FOR_ROOM, "now"]);
  // The sample's steps too.
  const sample = progressSteps({ ...base, sample: true, validation: V, costError: "busy", done: true, busy: { step: "price", live: false } });
  assert.deepEqual([sample[2].d, sample[2].state], [WAITING_FOR_ROOM, "wait"]);
  // Without busy, a cost that didn't finish still says so (unchanged).
  const failed = progressSteps({ ...base, validation: V, costError: "The should-cost service returned an unreadable response.", done: true });
  assert.deepEqual([failed[2].d, failed[2].state], ["Didn’t finish", "bad"]);
});
