import test from "node:test";
import assert from "node:assert/strict";
import type { ValidationResult } from "@/lib/api";

import {
  STILL_BUSY_TITLE,
  WAITING_FOR_ROOM,
  busyMeta,
  busyReopenBar,
  busyReopenLabel,
  busyTitle,
  busyView,
  serverMeta,
  serverStepText,
  serverTitle,
  sheetRunNotice,
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
  // At 390 the hidden panel's button is a bar above the tab bar that carries the state itself.
  assert.equal(busyReopenBar({ phase: "still", still: { step: "validate", kind: "server", waitedMs: 1 } }, T), "Still busy · your file is kept · Show");
  assert.equal(busyReopenBar({ phase: "waiting", step: "validate", wait: wait(9) }, T), "ScaleCAD is busy · checking again in 9 s");
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

test("while busy the sheet never falls back to 'Check interrupted' or 'Cost didn't finish'", () => {
  const views = [{ phase: "waiting", step: "validate", wait: wait(5) }, { phase: "still", still: { step: "validate", kind: "server", waitedMs: 180_000 } }, { phase: "still", still: { step: "cost", kind: "server", waitedMs: 180_000 } }] as const;
  const flags = [true, false];
  for (const busy of views)
    for (const panelOpen of flags)
      for (const checking of flags)
        for (const interrupted of flags)
          for (const costOff of flags)
            for (const costRetrying of flags) {
              if (!(checking || interrupted || costOff || costRetrying)) continue;
              const which = sheetRunNotice({ busy, panelOpen, checking, interrupted, costOff, costRetrying });
              assert.equal(which, panelOpen ? "panel" : "busy");
            }
  // Not busy: the sheet's own notices, as before.
  assert.equal(sheetRunNotice({ busy: null, panelOpen: true, checking: false, interrupted: true, costOff: false, costRetrying: false }), "other");
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

test("a gateway timeout or other 5xx is ScaleCAD's side: plain words, one Try again, never a file problem", () => {
  // From the check (probe or /validate), and from prices.
  assert.deepEqual(busyView({ busy: {}, failure: { kind: "server", step: "probe", status: 504 } }), { phase: "server", step: "probe", status: 504 });
  assert.deepEqual(busyView({ busy: {}, failure: { kind: "server", step: "validate", status: 502 } }), { phase: "server", step: "validate", status: 502 });
  assert.deepEqual(busyView({ busy: {}, result: { cost: null, costError: "Gateway Timeout", costStatus: 504 } }), { phase: "server", step: "cost", status: 504 });
  assert.deepEqual(busyView({ busy: {}, result: { cost: null, costError: "no answer", costStatus: 0 } }), { phase: "server", step: "cost", status: 0 });
  // A refusal of the file (4xx) keeps its own words; pricing again or priced: not this.
  assert.equal(busyView({ busy: {}, result: { cost: null, costError: "Geometry invalid", costStatus: 400 } }), null);
  assert.equal(busyView({ busy: {}, costRetrying: true, result: { cost: null, costError: "x", costStatus: 504 } }), null);
  assert.equal(busyView({ busy: {}, result: { cost: { ok: 1 }, costError: null, costStatus: null } }), null);
  // The brief's words for a timeout; a crash and no answer are said as what they are.
  assert.equal(serverTitle(504), "That took too long on our side. Your file is kept.");
  assert.equal(serverTitle(502), "That took too long on our side. Your file is kept.");
  assert.equal(serverTitle(503), "That took too long on our side. Your file is kept.");
  assert.equal(serverTitle(500), "That didn't finish on our side. Your file is kept.");
  assert.equal(serverTitle(0), "ScaleCAD didn't answer. Your file is kept.");
  assert.equal(serverMeta("validate", 504), "ScaleCAD stopped before answering (504). Nothing was checked. Try again runs the check once more.");
  assert.equal(serverMeta("cost", 502), "ScaleCAD stopped before answering (502). The process checks are ready; prices haven't run. Try again prices it once more.");
  const FILE = /can.?t read|couldn.?t read|no surfaces|fix in cad|re-?export|corrupt|invalid|unsupported|tessellat|interrupted|error|failed|usage and plans|allowance|file problem/i;
  for (const status of [500, 502, 503, 504, 0]) {
    const lines = [serverTitle(status), serverStepText(status), busyReopenLabel({ phase: "server", step: "validate", status }, T), busyReopenBar({ phase: "server", step: "validate", status }, T)];
    for (const step of ["probe", "validate", "cost", "preview"] as BusyStep[]) lines.push(serverMeta(step, status));
    for (const line of lines) assert.doesNotMatch(line, FILE, line);
  }
  // The sheet shows it (or the panel does), never "Check interrupted" or "Cost didn't finish".
  for (const panelOpen of [true, false]) assert.equal(sheetRunNotice({ busy: { phase: "server", step: "cost", status: 504 }, panelOpen, checking: false, interrupted: false, costOff: true, costRetrying: false }), panelOpen ? "panel" : "busy");
});

test("progress stopped on ScaleCAD's side says so, calmly: no red cross, no 'Didn't finish'", () => {
  const measured = progressSteps({ ...base, done: true, busy: { step: "measure", live: false, text: serverStepText(504) } });
  assert.deepEqual([measured[1].d, measured[1].state], ["Took too long on our side", "wait"]);
  const priced = progressSteps({ ...base, validation: V, costError: "Gateway Timeout", done: true, busy: { step: "price", live: false, text: serverStepText(502) } });
  assert.deepEqual(priced.map((s) => s.state), ["done", "done", "wait", "wait", "wait"]);
  assert.equal(priced[2].d, "Took too long on our side");
  // Pricing again after Try again: running, not failed.
  const again = progressSteps({ ...base, validation: V, costError: "Gateway Timeout", busy: { step: "price", live: true, text: "Pricing again…" } });
  assert.deepEqual([again[2].d, again[2].state], ["Pricing again…", "now"]);
  for (const s of [...measured, ...priced, ...again]) {
    assert.notEqual(s.state, "bad", s.t);
    assert.doesNotMatch(s.d, /didn.?t finish|not computed/i, s.t);
  }
});
