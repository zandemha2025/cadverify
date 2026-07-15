import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { register } from "node:module";
import test from "node:test";

import type { UploadProgress } from "./direct-upload.ts";

register("./direct-upload-test-loader.mjs", import.meta.url);
const {
  MULTIPART_UPLOAD_CONCURRENCY,
  uploadBatchZipDirect,
} = await import("./direct-upload.ts");

function multipartSession(
  partSize: number,
  partNumbers: number[],
): Record<string, unknown> {
  return {
    upload_id: "upload_123",
    part_size_bytes: partSize,
    parts: partNumbers.map((partNumber) => ({
      part_number: partNumber,
      url: `https://storage.example.test/part-${partNumber}`,
    })),
    expires_at: "2026-07-13T18:00:00Z",
  };
}

test("multipart upload slices parts, bounds concurrency, and completes in part order", async () => {
  const file = new File(["abcdefghijkl"], "assembly.zip", {
    type: "application/zip",
  });
  const initiationBodies: unknown[] = [];
  const uploadedBodies = new Map<number, string>();
  const putOptions: RequestInit[] = [];
  const calls: Array<{ url: string; method: string }> = [];
  let completionBody: { parts: Array<{ part_number: number; etag: string }> } | null = null;
  let activeUploads = 0;
  let maxActiveUploads = 0;

  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    calls.push({ url, method });

    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      initiationBodies.push(JSON.parse(String(init.body)));
      return Response.json(multipartSession(2, [6, 2, 5, 1, 4, 3]));
    }

    if (url.startsWith("https://storage.example.test/part-") && method === "PUT") {
      const partNumber = Number(url.split("-").at(-1));
      activeUploads += 1;
      maxActiveUploads = Math.max(maxActiveUploads, activeUploads);
      putOptions.push(init);
      uploadedBodies.set(partNumber, await (init.body as Blob).text());
      await new Promise<void>((resolve) => setTimeout(resolve, (7 - partNumber) * 2));
      activeUploads -= 1;
      return new Response(null, {
        status: 200,
        headers: { etag: `"etag-${partNumber}"` },
      });
    }

    if (url.endsWith("/upload_123/complete") && method === "POST") {
      completionBody = JSON.parse(String(init.body));
      return Response.json({ status: "complete" });
    }

    throw new Error(`Unexpected request: ${method} ${url}`);
  };

  const progress: UploadProgress[] = [];
  const directUploadId = await uploadBatchZipDirect(file, {
    fetcher,
    onProgress: (event) => progress.push(event),
  });

  assert.equal(directUploadId, "upload_123");
  assert.deepEqual(initiationBodies, [
    {
      purpose: "batch_zip",
      filename: "assembly.zip",
      size_bytes: 12,
      content_type: "application/zip",
      checksum_sha256: createHash("sha256").update("abcdefghijkl").digest("hex"),
    },
  ]);
  assert.deepEqual(
    Object.fromEntries([...uploadedBodies.entries()].sort(([a], [b]) => a - b)),
    { 1: "ab", 2: "cd", 3: "ef", 4: "gh", 5: "ij", 6: "kl" },
  );
  assert.equal(maxActiveUploads, MULTIPART_UPLOAD_CONCURRENCY);
  assert.ok(putOptions.every((options) => options.credentials === "omit"));
  assert.deepEqual(completionBody, {
    parts: [1, 2, 3, 4, 5, 6].map((partNumber) => ({
      part_number: partNumber,
      etag: `"etag-${partNumber}"`,
    })),
  });
  assert.ok(
    calls.some(
      (call) =>
        call.url === "/api/proxy/uploads/upload_123/complete" &&
        call.method === "POST",
    ),
  );
  assert.equal(
    calls.some((call) => call.url.includes("/uploads/multipart/upload_123/complete")),
    false,
  );
  assert.equal(calls.some((call) => call.method === "DELETE"), false);
  assert.deepEqual(progress.at(-1), {
    stage: "complete",
    percent: 100,
    uploadedBytes: 12,
    totalBytes: 12,
    completedParts: 6,
    totalParts: 6,
    partNumber: undefined,
    nextAttempt: undefined,
    maxAttempts: undefined,
    retryDelayMs: undefined,
  });
});

test("multipart upload retries transient failures with exponential backoff", async () => {
  const file = new File(["zip"], "retry.zip", { type: "application/zip" });
  const retryDelays: number[] = [];
  const progress: UploadProgress[] = [];
  let putAttempts = 0;

  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      return Response.json(multipartSession(3, [1]));
    }
    if (url.endsWith("/part-1") && method === "PUT") {
      putAttempts += 1;
      if (putAttempts === 1) throw new TypeError("connection reset");
      if (putAttempts === 2) return new Response(null, { status: 503 });
      return new Response(null, { status: 200, headers: { etag: '"etag-1"' } });
    }
    if (url.endsWith("/upload_123/complete") && method === "POST") {
      return Response.json({ status: "complete" });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };

  await uploadBatchZipDirect(file, {
    fetcher,
    sleep: async (delayMs) => {
      retryDelays.push(delayMs);
    },
    onProgress: (event) => progress.push(event),
  });

  assert.equal(putAttempts, 3);
  assert.deepEqual(retryDelays, [500, 1000]);
  assert.deepEqual(
    progress
      .filter((event) => event.stage === "retrying")
      .map(({ partNumber, nextAttempt, maxAttempts, retryDelayMs }) => ({
        partNumber,
        nextAttempt,
        maxAttempts,
        retryDelayMs,
      })),
    [
      { partNumber: 1, nextAttempt: 2, maxAttempts: 4, retryDelayMs: 500 },
      { partNumber: 1, nextAttempt: 3, maxAttempts: 4, retryDelayMs: 1000 },
    ],
  );
});

test("expired 403 refreshes only the affected part URL before retrying its Blob", async () => {
  const file = new File(["abcdef"], "refresh.zip", { type: "application/zip" });
  const futureExpiry = new Date(Date.now() + 15 * 60_000).toISOString();
  const putBodies = new Map<string, string[]>();
  let refreshBody: unknown;
  let completionBody: unknown;

  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      return Response.json({
        upload_id: "upload_123",
        part_size_bytes: 3,
        parts: [
          {
            part_number: 1,
            url: "https://storage.example.test/stable-1",
            expires_at: futureExpiry,
          },
          {
            part_number: 2,
            url: "https://storage.example.test/expired-2",
            expires_at: futureExpiry,
          },
        ],
        expires_at: new Date(Date.now() + 60 * 60_000).toISOString(),
        refresh_parts_url: "/api/v1/uploads/upload_123/parts",
      });
    }
    if (url.startsWith("https://storage.example.test/") && method === "PUT") {
      const bodies = putBodies.get(url) ?? [];
      bodies.push(await (init.body as Blob).text());
      putBodies.set(url, bodies);
      if (url.endsWith("/expired-2")) {
        return new Response(null, { status: 403 });
      }
      const etag = url.endsWith("/stable-1") ? '"etag-1"' : '"etag-2"';
      return new Response(null, { status: 200, headers: { etag } });
    }
    if (url === "/api/proxy/uploads/upload_123/parts" && method === "POST") {
      refreshBody = JSON.parse(String(init.body));
      return Response.json({
        direct_upload_id: "upload_123",
        parts: [
          {
            part_number: 2,
            url: "https://storage.example.test/refreshed-2",
            expires_at: futureExpiry,
          },
        ],
      });
    }
    if (url === "/api/proxy/uploads/upload_123/complete" && method === "POST") {
      completionBody = JSON.parse(String(init.body));
      return Response.json({ status: "complete" });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };

  await uploadBatchZipDirect(file, {
    fetcher,
    sleep: async () => undefined,
  });

  assert.deepEqual(refreshBody, { part_numbers: [2] });
  assert.deepEqual(putBodies.get("https://storage.example.test/stable-1"), ["abc"]);
  assert.deepEqual(putBodies.get("https://storage.example.test/expired-2"), ["def"]);
  assert.deepEqual(putBodies.get("https://storage.example.test/refreshed-2"), ["def"]);
  assert.deepEqual(completionBody, {
    parts: [
      { part_number: 1, etag: '"etag-1"' },
      { part_number: 2, etag: '"etag-2"' },
    ],
  });
});

test("refreshed part destinations receive the same URL validation as initiation", async () => {
  const file = new File(["zip"], "invalid-refresh.zip", {
    type: "application/zip",
  });

  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      return Response.json(multipartSession(3, [1]));
    }
    if (url === "https://storage.example.test/part-1" && method === "PUT") {
      return new Response(null, { status: 403 });
    }
    if (url === "/api/proxy/uploads/upload_123/parts" && method === "POST") {
      return Response.json({
        direct_upload_id: "upload_123",
        parts: [{ part_number: 1, url: "javascript:unsafe" }],
      });
    }
    if (url === "/api/proxy/uploads/upload_123/abort" && method === "POST") {
      return Response.json({ status: "aborted" });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };

  await assert.rejects(
    () =>
      uploadBatchZipDirect(file, {
        fetcher,
        sleep: async () => undefined,
      }),
    /invalid part destination/i,
  );
});

test("near-expiry part URL refreshes before the first PUT", async () => {
  const file = new File(["zip"], "near-expiry.zip", {
    type: "application/zip",
  });
  const calls: Array<{ url: string; method: string }> = [];

  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    calls.push({ url, method });
    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      return Response.json({
        ...multipartSession(3, [1]),
        parts: [
          {
            part_number: 1,
            url: "https://storage.example.test/soon-expired",
            expires_at: new Date(Date.now() + 30_000).toISOString(),
          },
        ],
      });
    }
    if (url === "/api/proxy/uploads/upload_123/parts" && method === "POST") {
      assert.deepEqual(JSON.parse(String(init.body)), { part_numbers: [1] });
      return Response.json({
        direct_upload_id: "upload_123",
        parts: [
          {
            part_number: 1,
            url: "https://storage.example.test/fresh",
            expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
          },
        ],
      });
    }
    if (url === "https://storage.example.test/fresh" && method === "PUT") {
      return new Response(null, {
        status: 200,
        headers: { etag: '"etag-1"' },
      });
    }
    if (url === "/api/proxy/uploads/upload_123/complete" && method === "POST") {
      return Response.json({ status: "complete" });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };

  await uploadBatchZipDirect(file, { fetcher });

  assert.equal(
    calls.some((call) => call.url === "https://storage.example.test/soon-expired"),
    false,
  );
  assert.ok(
    calls.some(
      (call) =>
        call.url === "/api/proxy/uploads/upload_123/parts" &&
        call.method === "POST",
    ),
  );
});

test("terminal part failure aborts the multipart session and never completes it", async () => {
  const file = new File(["zip"], "broken.zip", { type: "application/zip" });
  const calls: Array<{ url: string; method: string }> = [];

  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    calls.push({ url, method });
    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      return Response.json(multipartSession(3, [1]));
    }
    if (url.endsWith("/part-1") && method === "PUT") {
      return new Response(null, { status: 400 });
    }
    if (url === "/api/proxy/uploads/upload_123/abort" && method === "POST") {
      return Response.json({ status: "aborted" });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };

  await assert.rejects(
    () => uploadBatchZipDirect(file, { fetcher }),
    /Part 1 was rejected during upload \(400\)/,
  );
  assert.deepEqual(calls.at(-1), {
    url: "/api/proxy/uploads/upload_123/abort",
    method: "POST",
  });
  assert.equal(calls.some((call) => call.method === "DELETE"), false);
  assert.equal(calls.some((call) => call.url.endsWith("/complete")), false);
});

test("lost completion response reconciles through status without aborting", async () => {
  const file = new File(["zip"], "reconcile.zip", { type: "application/zip" });
  const calls: string[] = [];

  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    calls.push(`${method} ${url}`);
    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      return Response.json(multipartSession(3, [1]));
    }
    if (url.endsWith("/part-1") && method === "PUT") {
      return new Response(null, { status: 200, headers: { etag: '"etag-1"' } });
    }
    if (url.endsWith("/upload_123/complete") && method === "POST") {
      throw new TypeError("provider response lost");
    }
    if (url.endsWith("/uploads/upload_123") && method === "GET") {
      return Response.json({ direct_upload_id: "upload_123", status: "completed" });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };

  const uploadId = await uploadBatchZipDirect(file, {
    fetcher,
    checksum: async () => "a".repeat(64),
    sleep: async () => undefined,
  });

  assert.equal(uploadId, "upload_123");
  assert.ok(calls.includes("GET /api/proxy/uploads/upload_123"));
  assert.equal(calls.some((call) => call.endsWith("/abort")), false);
});

test("ambiguous completion keeps one reload-safe idempotency key and never aborts", async (t) => {
  const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    clear: () => values.clear(),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
  } satisfies Storage;
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    value: storage,
  });
  t.after(() => {
    if (originalDescriptor) {
      Object.defineProperty(globalThis, "sessionStorage", originalDescriptor);
    } else {
      delete (globalThis as { sessionStorage?: Storage }).sessionStorage;
    }
  });

  const fileOptions = { type: "application/zip", lastModified: 1234 };
  const firstFile = new File(["zip"], "resume.zip", fileOptions);
  const initiationKeys: string[] = [];
  let phase: "ambiguous" | "replayed" = "ambiguous";
  let aborts = 0;

  const fetcher: typeof fetch = async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      initiationKeys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
      if (phase === "replayed") {
        return Response.json({
          direct_upload_id: "upload_123",
          status: "completed",
          part_size_bytes: 3,
          parts: [],
          expires_at: "2026-07-13T18:00:00Z",
        });
      }
      return Response.json(multipartSession(3, [1]));
    }
    if (url.endsWith("/part-1") && method === "PUT") {
      return new Response(null, { status: 200, headers: { etag: '"etag-1"' } });
    }
    if (url.endsWith("/upload_123/complete") && method === "POST") {
      throw new TypeError("completion response unavailable");
    }
    if (url.endsWith("/uploads/upload_123") && method === "GET") {
      throw new TypeError("status unavailable");
    }
    if (url.endsWith("/abort") && method === "POST") {
      aborts += 1;
      return Response.json({ status: "aborted" });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };

  await assert.rejects(
    () => uploadBatchZipDirect(firstFile, {
      fetcher,
      checksum: async () => "b".repeat(64),
      sleep: async () => undefined,
    }),
    /resume the same upload/i,
  );
  phase = "replayed";
  const replayId = await uploadBatchZipDirect(
    new File(["zip"], "resume.zip", fileOptions),
    {
      fetcher,
      checksum: async () => "b".repeat(64),
      sleep: async () => undefined,
    },
  );

  assert.equal(replayId, "upload_123");
  assert.equal(aborts, 0);
  assert.equal(initiationKeys.length, 2);
  assert.ok(initiationKeys[0].startsWith("browser-"));
  assert.equal(initiationKeys[0], initiationKeys[1]);
});
