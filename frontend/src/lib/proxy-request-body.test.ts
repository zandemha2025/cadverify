import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAX_BUFFERED_PROXY_JSON_BYTES,
  isJsonContentType,
  prepareProxyRequestBody,
} from "./proxy-request-body.ts";

function stream(...chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

test("recognizes JSON content types without treating CAD uploads as JSON", () => {
  assert.equal(isJsonContentType("application/json; charset=utf-8"), true);
  assert.equal(isJsonContentType("application/problem+json"), true);
  assert.equal(isJsonContentType("multipart/form-data; boundary=proof"), false);
  assert.equal(isJsonContentType("application/step"), false);
});

test("buffers a bounded JSON command into a non-streaming body", async () => {
  const expected = new TextEncoder().encode('{"token":"abc"}');
  const prepared = await prepareProxyRequestBody(
    "POST",
    "application/json",
    stream(expected.slice(0, 5), expected.slice(5)),
  );

  assert.equal(prepared.tooLarge, false);
  assert.equal(prepared.streaming, false);
  assert.deepEqual(new Uint8Array(prepared.body as ArrayBuffer), expected);
});

test("preserves streaming for large-upload content types", async () => {
  const source = stream(new Uint8Array([1, 2, 3]));
  const prepared = await prepareProxyRequestBody(
    "POST",
    "multipart/form-data; boundary=proof",
    source,
  );

  assert.equal(prepared.tooLarge, false);
  assert.equal(prepared.streaming, true);
  assert.equal(prepared.body, source);
});

test("rejects oversized JSON before forwarding it", async () => {
  const prepared = await prepareProxyRequestBody(
    "POST",
    "application/json",
    stream(
      new Uint8Array(MAX_BUFFERED_PROXY_JSON_BYTES),
      new Uint8Array([1]),
    ),
  );

  assert.equal(prepared.tooLarge, true);
  assert.equal(prepared.body, undefined);
  assert.equal(prepared.streaming, false);
});

test("does not attach a body to GET or HEAD", async () => {
  for (const method of ["GET", "HEAD"]) {
    const prepared = await prepareProxyRequestBody(
      method,
      "application/json",
      stream(new Uint8Array([1])),
    );
    assert.deepEqual(prepared, {
      body: undefined,
      streaming: false,
      tooLarge: false,
    });
  }
});
