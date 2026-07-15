import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { boundedJsonFetch } from "./bounded-json-fetch.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("read-only JSON fetch retries one interrupted browser response", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    if (calls === 1) throw new TypeError("interrupted response body");
    return Response.json({ revisions: [{ id: "R1", number: 1 }] });
  }) as typeof fetch;

  const payload = await boundedJsonFetch<{ revisions: Array<{ id: string; number: number }> }>(
    "/api/proxy/designs/01DESIGN/revisions",
  );
  assert.equal(calls, 2);
  assert.deepEqual(payload.revisions, [{ id: "R1", number: 1 }]);
});

test("mutating JSON fetch stays single-shot after a network failure", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    throw new TypeError("connection reset");
  }) as typeof fetch;

  await assert.rejects(
    boundedJsonFetch("/api/proxy/designs", { method: "POST" }),
    /connection reset/,
  );
  assert.equal(calls, 1);
});

test("a stalled GET is aborted and retried within its deadline", async () => {
  let calls = 0;
  globalThis.fetch = (async (_input, init = {}) => {
    calls += 1;
    if (calls === 1) {
      return new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("timed out", "AbortError")),
          { once: true },
        );
      });
    }
    return Response.json({ revisions: [] });
  }) as typeof fetch;

  const payload = await boundedJsonFetch<{ revisions: unknown[] }>(
    "/api/proxy/designs/01DESIGN/revisions",
    {},
    { timeoutMs: 10 },
  );
  assert.equal(calls, 2);
  assert.deepEqual(payload, { revisions: [] });
});
