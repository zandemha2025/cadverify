import assert from "node:assert/strict";
import test from "node:test";

import { startReconstructionPolling } from "./reconstruction-poller.ts";

const settle = () => new Promise<void>((resolve) => setImmediate(resolve));

function manualScheduler() {
  const pending: Array<{ id: number; callback: () => void; delay: number }> = [];
  let nextId = 1;
  return {
    pending,
    schedule(callback: () => void, delay: number) {
      const id = nextId++;
      pending.push({ id, callback, delay });
      return id as unknown as ReturnType<typeof setTimeout>;
    },
    cancel(timer: ReturnType<typeof setTimeout>) {
      const id = timer as unknown as number;
      const index = pending.findIndex((entry) => entry.id === id);
      if (index >= 0) pending.splice(index, 1);
    },
    runNext() {
      const next = pending.shift();
      assert.ok(next, "expected a scheduled poll");
      next.callback();
      return next.delay;
    },
  };
}

test("done follows result_url before completing", async () => {
  const completed: Array<{ value: { mesh: string }; status: string }> = [];
  const scheduler = manualScheduler();
  startReconstructionPolling({
    jobId: "JOB1",
    fetchStatus: async () => ({
      status: "done",
      result_url: "/api/v1/jobs/JOB1/result",
      error: null,
    }),
    fetchResult: async (url) => {
      assert.equal(url, "/api/v1/jobs/JOB1/result");
      return { status: "done", result: { mesh: "ready" } };
    },
    onStatus: () => {},
    onComplete: (value, status) => completed.push({ value, status }),
    onError: assert.fail,
    schedule: scheduler.schedule,
    cancelSchedule: scheduler.cancel,
  });

  await settle();
  assert.deepEqual(completed, [{ value: { mesh: "ready" }, status: "done" }]);
  assert.equal(scheduler.pending.length, 0);
});

test("partial is terminal and result-bearing", async () => {
  let terminalStatus = "";
  startReconstructionPolling({
    jobId: "JOB2",
    fetchStatus: async () => ({
      status: "partial",
      result_url: "/api/v1/jobs/JOB2/result",
      error: null,
    }),
    fetchResult: async () => ({ status: "partial", result: { fallback: true } }),
    onStatus: () => {},
    onComplete: (_value, status) => {
      terminalStatus = status;
    },
    onError: assert.fail,
  });

  await settle();
  assert.equal(terminalStatus, "partial");
});

test("failed status uses the backend error and never requests a result", async () => {
  let message = "";
  let resultCalls = 0;
  startReconstructionPolling({
    jobId: "JOB3",
    fetchStatus: async () => ({
      status: "failed",
      result_url: null,
      error: { code: "RECONSTRUCTION_FAILED", message: "Use clearer photos." },
    }),
    fetchResult: async () => {
      resultCalls += 1;
      throw new Error("result must not be fetched");
    },
    onStatus: () => {},
    onComplete: () => assert.fail("failed jobs cannot complete"),
    onError: (value) => {
      message = value;
    },
  });

  await settle();
  assert.equal(message, "Use clearer photos.");
  assert.equal(resultCalls, 0);
});

test("recursive scheduling cannot overlap a slow status request", async () => {
  const scheduler = manualScheduler();
  let resolveFirst: ((value: {
    status: "queued";
    result_url: null;
    error: null;
  }) => void) | null = null;
  let calls = 0;
  const first = new Promise<{
    status: "queued";
    result_url: null;
    error: null;
  }>((resolve) => {
    resolveFirst = resolve;
  });

  const stop = startReconstructionPolling({
    jobId: "JOB4",
    fetchStatus: async () => {
      calls += 1;
      return calls === 1
        ? first
        : { status: "running", result_url: null, error: null };
    },
    fetchResult: async () => assert.fail("not terminal"),
    onStatus: () => {},
    onComplete: () => {},
    onError: assert.fail,
    baseDelayMs: 10,
    schedule: scheduler.schedule,
    cancelSchedule: scheduler.cancel,
  });

  await settle();
  assert.equal(calls, 1);
  assert.equal(scheduler.pending.length, 0);
  resolveFirst?.({ status: "queued", result_url: null, error: null });
  await settle();
  assert.equal(scheduler.pending.length, 1);
  assert.equal(scheduler.runNext(), 10);
  await settle();
  assert.equal(calls, 2);
  stop();
});

test("transient failures back off and a successful poll resets the delay", async () => {
  const scheduler = manualScheduler();
  let calls = 0;
  const stop = startReconstructionPolling({
    jobId: "JOB5",
    fetchStatus: async () => {
      calls += 1;
      if (calls <= 2) throw new Error("temporary network failure");
      return { status: "running", result_url: null, error: null };
    },
    fetchResult: async () => assert.fail("not terminal"),
    onStatus: () => {},
    onComplete: () => {},
    onError: assert.fail,
    baseDelayMs: 10,
    maxDelayMs: 100,
    schedule: scheduler.schedule,
    cancelSchedule: scheduler.cancel,
  });

  await settle();
  assert.equal(scheduler.runNext(), 10);
  await settle();
  assert.equal(scheduler.runNext(), 20);
  await settle();
  assert.equal(scheduler.pending[0]?.delay, 10);
  stop();
});

test("stopping aborts an in-flight request without surfacing an error", async () => {
  let observedSignal: AbortSignal | null = null;
  let errors = 0;
  const stop = startReconstructionPolling({
    jobId: "JOB6",
    fetchStatus: async (_jobId, signal) => {
      observedSignal = signal;
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        );
      });
    },
    fetchResult: async () => assert.fail("not terminal"),
    onStatus: () => {},
    onComplete: () => {},
    onError: () => {
      errors += 1;
    },
  });

  await settle();
  stop();
  await settle();
  assert.equal(observedSignal?.aborted, true);
  assert.equal(errors, 0);
});
