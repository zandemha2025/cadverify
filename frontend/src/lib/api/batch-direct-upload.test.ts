import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

import type { UploadProgress } from "./batch.ts";

register("./direct-upload-test-loader.mjs", import.meta.url);
const { createBatch } = await import("./batch.ts");
const { DirectUploadError } = await import("./direct-upload.ts");

test("capability false preserves the proxied FormData batch upload", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  const file = new File(["proxied zip"], "fallback.zip", {
    type: "application/zip",
  });
  const manifest = new File(["filename,priority\npart.step,high"], "manifest.csv", {
    type: "text/csv",
  });
  const progress: UploadProgress[] = [];
  let batchBody: FormData | null = null;

  globalThis.fetch = (async (input, init = {}) => {
    const url = String(input);
    if (url === "/api/proxy/uploads/capabilities") {
      assert.equal(init.method, "GET");
      return Response.json({ direct_upload: false });
    }
    if (url === "/api/proxy/batch") {
      batchBody = init.body as FormData;
      return Response.json({
        batch_id: "batch_fallback",
        status: "pending",
        status_url: "/api/v1/batch/batch_fallback",
      });
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;

  const result = await createBatch(file, {
    manifest,
    webhookUrl: "https://hooks.example.test/batch",
    concurrencyLimit: 7,
    onUploadProgress: (event) => progress.push(event),
  });

  assert.equal(result.batch_id, "batch_fallback");
  assert.ok(batchBody instanceof FormData);
  assert.equal(batchBody.get("file"), file);
  assert.equal(batchBody.get("direct_upload_id"), null);
  assert.equal(batchBody.get("manifest"), manifest);
  assert.equal(batchBody.get("webhook_url"), "https://hooks.example.test/batch");
  assert.equal(batchBody.get("concurrency_limit"), "7");
  assert.deepEqual(progress.map((event) => event.stage), ["checking", "proxying"]);
  assert.equal(progress.at(-1)?.percent, null);
});

test("backend-shaped direct response completes upload before creating batch by opaque ID", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  const file = new File(["abcdef"], "direct.zip", { type: "application/zip" });
  const partExpiry = new Date(Date.now() + 15 * 60_000).toISOString();
  const requestOrder: string[] = [];
  let completionBody: unknown;
  let batchBody: FormData | null = null;

  globalThis.fetch = (async (input, init = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    if (url === "/api/proxy/uploads/capabilities") {
      requestOrder.push("capabilities");
      return Response.json({ available: true });
    }
    if (url === "/api/proxy/uploads/multipart" && method === "POST") {
      requestOrder.push("initiate");
      return Response.json({
        direct_upload_id: "opaque_upload_id",
        part_size_bytes: 3,
        parts: [
          {
            part_number: 2,
            url: "https://storage.example.test/two",
            expires_at: partExpiry,
          },
          {
            part_number: 1,
            url: "https://storage.example.test/one",
            expires_at: partExpiry,
          },
        ],
        expires_at: "2026-07-13T18:00:00Z",
        complete_url: "/api/v1/uploads/opaque_upload_id/complete",
        refresh_parts_url: "/api/v1/uploads/opaque_upload_id/parts",
      });
    }
    if (url.startsWith("https://storage.example.test/") && method === "PUT") {
      const partNumber = url.endsWith("one") ? 1 : 2;
      requestOrder.push(`put-${partNumber}`);
      return new Response(null, {
        status: 200,
        headers: { etag: `"etag-${partNumber}"` },
      });
    }
    if (url.endsWith("/opaque_upload_id/complete") && method === "POST") {
      requestOrder.push("complete");
      completionBody = JSON.parse(String(init.body));
      return Response.json({ status: "complete" });
    }
    if (url === "/api/proxy/batch" && method === "POST") {
      requestOrder.push("batch");
      batchBody = init.body as FormData;
      return Response.json({
        batch_id: "batch_direct",
        status: "pending",
        status_url: "/api/v1/batch/batch_direct",
      });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  }) as typeof fetch;

  const result = await createBatch(file);

  assert.equal(result.batch_id, "batch_direct");
  assert.deepEqual(completionBody, {
    parts: [
      { part_number: 1, etag: '"etag-1"' },
      { part_number: 2, etag: '"etag-2"' },
    ],
  });
  assert.ok(requestOrder.indexOf("complete") < requestOrder.indexOf("batch"));
  assert.ok(batchBody instanceof FormData);
  assert.equal(batchBody.get("direct_upload_id"), "opaque_upload_id");
  assert.equal(batchBody.get("file"), null);
});

for (const status of [404, 501]) {
  test(`capability ${status} fails closed without proxying the ZIP`, async (t) => {
    const originalFetch = globalThis.fetch;
    t.after(() => {
      globalThis.fetch = originalFetch;
    });

    const calls: Array<{ url: string; method: string }> = [];
    globalThis.fetch = (async (input, init = {}) => {
      const url = String(input);
      const method = init.method ?? "GET";
      calls.push({ url, method });
      if (url !== "/api/proxy/uploads/capabilities") {
        throw new Error(`Capability failure unexpectedly reached ${method} ${url}`);
      }
      return Response.json(
        { detail: { message: "Direct upload capability is unavailable." } },
        { status },
      );
    }) as typeof fetch;

    await assert.rejects(
      () =>
        createBatch(
          new File(["zip"], "rollout.zip", { type: "application/zip" }),
        ),
      (error: unknown) =>
        error instanceof DirectUploadError && error.status === status,
    );
    assert.deepEqual(calls, [
      { url: "/api/proxy/uploads/capabilities", method: "GET" },
    ]);
  });
}
