import { test } from "node:test";
import assert from "node:assert/strict";

import {
  BUSY_BOUND_MS,
  busyDelayMs,
  busySignal,
  parseRetryAfter,
  retryWhileBusy,
  secondsUntil,
  serverTrouble,
  type BusyAttempt,
  type BusySignal,
  type BusyWait,
} from "./busy.ts";

// The server's own busy answers (backend admission.py and compute_budget.py): 429, Retry-After 5.
const SERVER_BUSY = { detail: { code: "server_busy", message: "server is at capacity, retry shortly", doc_url: "x" } };
const ORG_BUSY = { detail: { code: "org_at_capacity", message: "this organization has reached its concurrent-analysis limit of 3" } };

test("only a busy refusal is busy: server_busy (429 or 503) and org_at_capacity", () => {
  assert.deepEqual(busySignal(429, SERVER_BUSY, "5"), { kind: "server", retryAfterS: 5 });
  assert.deepEqual(busySignal(503, { detail: { code: "server_busy", message: "database busy" } }, "3"), { kind: "server", retryAfterS: 3 });
  assert.deepEqual(busySignal(503, { code: "server_busy" }, null), { kind: "server", retryAfterS: null });
  assert.deepEqual(busySignal(429, ORG_BUSY, "5"), { kind: "org", retryAfterS: 5 });
  // An older server without a code says it in words.
  assert.equal(busySignal(429, { detail: "server is at capacity, retry shortly" }, "5")?.kind, "server");
  // A thrown error carries the code (api.ts withHttpStatus) but its message is the app's own words.
  assert.equal(busySignal(429, { code: "server_busy", message: "Too many verification requests were sent." }, "5")?.kind, "server");
});

test("an allowance, a rate limit, a refused file or a timeout is never retried as busy", () => {
  for (const code of ["org_validation_cap_exceeded", "user_validation_cap_exceeded", "org_quota_exceeded", "free_tool_limit", "phone_verification_required", "paid_access_required"]) {
    assert.equal(busySignal(429, { detail: { code, message: "used up" } }, "60"), null, code);
    assert.equal(busySignal(403, { detail: { code, message: "used up" } }, null), null, code);
  }
  assert.equal(busySignal(429, { detail: "Rate limit exceeded" }, "60"), null);
  assert.equal(busySignal(400, { code: "GEOMETRY_INVALID", message: "server is at capacity" }, null), null);
  assert.equal(busySignal(500, SERVER_BUSY, "5"), null);
  assert.equal(busySignal(504, { detail: "Assembly parsing exceeded 60s timeout" }, null), null);
  assert.equal(busySignal(503, { detail: "Connector credential storage is not configured." }, null), null);
  assert.equal(busySignal(200, SERVER_BUSY, "5"), null);
});

test("ScaleCAD's side: any 5xx that isn't busy, or no answer; never a 4xx file refusal", () => {
  for (const status of [500, 502, 503, 504, 0]) assert.equal(serverTrouble(status), true, String(status));
  // Busy is waited out, not this.
  assert.equal(serverTrouble(503, true), false);
  assert.equal(serverTrouble(429, true), false);
  for (const status of [400, 401, 403, 404, 409, 413, 415, 422, 429]) assert.equal(serverTrouble(status), false, String(status));
  assert.equal(serverTrouble(null), false);
  assert.equal(serverTrouble(undefined), false);
});

test("Retry-After is read as seconds or as an HTTP date", () => {
  const now = Date.parse("2026-10-23T05:00:00Z");
  assert.equal(parseRetryAfter("5", now), 5);
  assert.equal(parseRetryAfter(" 12 ", now), 12);
  assert.equal(parseRetryAfter("Fri, 23 Oct 2026 05:00:09 GMT", now), 9);
  assert.equal(parseRetryAfter("Fri, 23 Oct 2026 04:59:00 GMT", now), 0);
  assert.equal(parseRetryAfter("", now), null);
  assert.equal(parseRetryAfter("soon", now), null);
  assert.equal(parseRetryAfter(null, now), null);
});

test("each wait honours Retry-After, with jitter that only ever adds", () => {
  const five: BusySignal = { kind: "server", retryAfterS: 5 };
  assert.equal(busyDelayMs(five, () => 0), 5000);
  assert.equal(busyDelayMs(five, () => 1), 6250);
  for (let i = 0; i < 200; i++) {
    const d = busyDelayMs(five);
    assert.ok(d >= 5000 && d <= 6250, `delay ${d}`);
  }
  // Unsaid: the server's usual 5 s. Bounded: never under 1 s, never over 30 s (plus jitter).
  assert.equal(busyDelayMs({ kind: "server", retryAfterS: null }, () => 0), 5000);
  assert.equal(busyDelayMs({ kind: "server", retryAfterS: 0 }, () => 0), 1000);
  assert.equal(busyDelayMs({ kind: "server", retryAfterS: 600 }, () => 0), 30000);
  assert.equal(busyDelayMs({ kind: "org", retryAfterS: 12 }, () => 0.5), 13500);
});

test("after three busy answers the wait grows gently, to 15 s, never below what was asked", () => {
  const five: BusySignal = { kind: "server", retryAfterS: 5 };
  assert.deepEqual([1, 2, 3, 4, 5, 6, 7, 12].map((n) => busyDelayMs(five, () => 0, n)), [5000, 5000, 5000, 7500, 11250, 15000, 15000, 15000]);
  // A server that asks for longer is never asked sooner.
  assert.equal(busyDelayMs({ kind: "server", retryAfterS: 25 }, () => 0, 9), 25000);
  assert.equal(busyDelayMs({ kind: "server", retryAfterS: 25 }, () => 1, 9), 31250);
});

/** A fake clock: sleeping moves it; each try takes `tryMs`. */
function clock(tryMs = 0) {
  let t = 1_000_000;
  const slept: number[] = [];
  return {
    now: () => t,
    sleep: async (ms: number) => {
      slept.push(ms);
      t += ms;
    },
    spend: () => {
      t += tryMs;
    },
    slept,
    at: () => t,
  };
}

test("busy, busy, answer: asks again after each Retry-After and counts it down", async () => {
  const c = clock();
  const answers: BusyAttempt<string>[] = [{ busy: { kind: "server", retryAfterS: 7 } }, { busy: { kind: "server", retryAfterS: 3 } }, { value: "result" }];
  const waits: (BusyWait | null)[] = [];
  const starts: number[] = [];
  const out = await retryWhileBusy(
    async () => {
      starts.push(c.at());
      return answers.shift()!;
    },
    { now: c.now, sleep: c.sleep, random: () => 0, onWait: (w) => waits.push(w) },
  );
  assert.deepEqual(out, { ok: true, value: "result", attempts: 3 });
  // Each wait is the Retry-After of the answer before it.
  assert.deepEqual(c.slept, [7000, 3000]);
  assert.deepEqual(starts.map((s) => s - starts[0]), [0, 7000, 10000]);
  // Each wait names the next try, so the page shows "Checking again in 7 s…" then "in 3 s…".
  assert.equal(waits.length, 3);
  assert.equal(secondsUntil(waits[0]!.until, starts[0]), 7);
  assert.equal(waits[0]!.attempt, 1);
  assert.equal(secondsUntil(waits[1]!.until, starts[1]), 3);
  assert.equal(waits[1]!.since, starts[0]);
  // The wait is over once it answers.
  assert.equal(waits[2], null);
});

test("never busy: one try, no wait shown", async () => {
  const c = clock();
  const waits: (BusyWait | null)[] = [];
  const out = await retryWhileBusy(async () => ({ value: 42 }), { now: c.now, sleep: c.sleep, onWait: (w) => waits.push(w) });
  assert.deepEqual(out, { ok: true, value: 42, attempts: 1 });
  assert.deepEqual(waits, []);
  assert.deepEqual(c.slept, []);
});

test("it stops asking after about three minutes, and no try starts after the bound", async () => {
  const c = clock();
  const starts: number[] = [];
  let last: BusyWait | null | undefined;
  const out = await retryWhileBusy<string>(
    async () => {
      starts.push(c.at());
      return { busy: { kind: "server", retryAfterS: 5 }, value: "refused" };
    },
    { now: c.now, sleep: c.sleep, random: () => 0, onWait: (w) => (last = w) },
  );
  assert.equal(out.ok, false);
  if (out.ok) return;
  // Tries at 0, 5, 10, 15, 22.5, 33.75, then every 15 s to 168.75 s; the next would start past 180 s.
  assert.deepEqual(c.slept.slice(0, 6), [5000, 5000, 5000, 7500, 11250, 15000]);
  assert.equal(out.attempts, 15);
  assert.equal(starts.at(-1)! - starts[0], 168_750);
  assert.ok(starts.every((s) => s - starts[0] <= BUSY_BOUND_MS));
  assert.equal(c.at() - out.since, 168_750);
  assert.equal(out.value, "refused");
  assert.equal(out.busy.kind, "server");
  assert.equal(last, null);
});

test("a slow busy answer (the server waited for room first) counts toward the bound", async () => {
  // The compute budget holds a request up to its wait before answering busy: each try takes 30 s here.
  const c = clock(30_000);
  let tries = 0;
  const out = await retryWhileBusy<string>(
    async () => {
      tries += 1;
      c.spend();
      return { busy: { kind: "server", retryAfterS: 5 } };
    },
    { now: c.now, sleep: c.sleep, random: () => 0 },
  );
  assert.equal(out.ok, false);
  // Tries start at 0, 35, 70, 105 and 142.5 s; the fifth answers at 172.5 s and a sixth would start past 180 s.
  assert.equal(tries, 5);
  assert.equal(c.at() - out.since, 172_500);
});

test("a longer Retry-After means fewer tries in the same three minutes", async () => {
  const c = clock();
  let tries = 0;
  await retryWhileBusy(
    async () => {
      tries += 1;
      return { busy: { kind: "org", retryAfterS: 30 } };
    },
    { now: c.now, sleep: c.sleep, random: () => 0 },
  );
  assert.equal(tries, 7);
});

test("bound 0 is one try: the busy answer comes straight back with its value", async () => {
  const c = clock();
  const waits: (BusyWait | null)[] = [];
  const out = await retryWhileBusy(async () => ({ busy: { kind: "server", retryAfterS: 5 }, value: "first" }), { boundMs: 0, now: c.now, sleep: c.sleep, onWait: (w) => waits.push(w) });
  assert.equal(out.ok, false);
  assert.equal(out.attempts, 1);
  assert.equal(out.value, "first");
  assert.deepEqual(c.slept, []);
  // Nothing was ever shown as waiting, so there's nothing to clear but the null.
  assert.deepEqual(waits, [null]);
});

test("a try that throws ends the waiting and the error reaches the caller", async () => {
  const c = clock();
  const waits: (BusyWait | null)[] = [];
  let n = 0;
  await assert.rejects(
    retryWhileBusy(
      async () => {
        n += 1;
        if (n === 2) throw new Error("network");
        return { busy: { kind: "server", retryAfterS: 5 } };
      },
      { now: c.now, sleep: c.sleep, random: () => 0, onWait: (w) => waits.push(w) },
    ),
    /network/,
  );
  assert.equal(waits.length, 2);
  assert.equal(waits.at(-1), null);
});

test("stop ends the asking: no further try once the check it serves has stopped", async () => {
  const c = clock();
  let tries = 0;
  let stopped = false;
  const waits: (BusyWait | null)[] = [];
  const out = await retryWhileBusy(
    async () => {
      tries += 1;
      if (tries === 2) stopped = true; // the check gave up while this try was out
      return { busy: { kind: "server", retryAfterS: 5 } };
    },
    { now: c.now, sleep: c.sleep, random: () => 0, stop: () => stopped, onWait: (w) => waits.push(w) },
  );
  assert.equal(out.ok, false);
  assert.equal(!out.ok && out.stopped, true);
  assert.equal(tries, 2);
  assert.equal(waits.at(-1), null);
  // Stopped during a wait: the next try never goes out.
  let n = 0;
  let stopNow = false;
  const c2 = clock();
  const out2 = await retryWhileBusy(
    async () => {
      n += 1;
      return { busy: { kind: "server", retryAfterS: 5 } };
    },
    { now: c2.now, sleep: async (ms) => { await c2.sleep(ms); stopNow = true; }, random: () => 0, stop: () => stopNow },
  );
  assert.equal(n, 1);
  assert.equal(!out2.ok && out2.stopped, true);
});

test("the countdown is whole seconds, rounded up, and 0 once the try is out", () => {
  assert.equal(secondsUntil(10_000, 2_000), 8);
  assert.equal(secondsUntil(10_000, 2_001), 8);
  assert.equal(secondsUntil(10_000, 9_999), 1);
  assert.equal(secondsUntil(10_000, 10_000), 0);
  assert.equal(secondsUntil(10_000, 12_000), 0);
});
