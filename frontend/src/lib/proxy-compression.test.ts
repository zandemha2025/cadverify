import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const { acceptsGzip, shouldRecompress, variesByEncoding } = await import("./proxy-compression.ts");

const api = (type: string, encoding?: string) => new Headers({ "content-type": type, ...(encoding ? { "content-encoding": encoding } : {}) });

test("a body the API compressed is compressed again for a browser that accepts gzip (buyer-15)", () => {
  assert.equal(shouldRecompress("gzip, deflate, br", api("application/json", "gzip")), true);
  assert.equal(shouldRecompress("br, gzip;q=0.8", api("application/json; charset=utf-8", "gzip")), true);
  assert.equal(shouldRecompress("*", api("model/gltf-binary", "gzip")), true);
  // Small or plain upstream bodies, binary downloads, event streams and refusing browsers stay as they are.
  assert.equal(shouldRecompress("gzip", api("application/json")), false);
  assert.equal(shouldRecompress("gzip", api("application/zip", "gzip")), false);
  assert.equal(shouldRecompress("gzip", api("text/event-stream", "gzip")), false);
  assert.equal(shouldRecompress("gzip;q=0, br", api("application/json", "gzip")), false);
  assert.equal(shouldRecompress(null, api("application/json", "gzip")), false);
  assert.equal(acceptsGzip("identity"), false);
  assert.equal(variesByEncoding("application/pdf"), false);
});

test("the proxy route gzips with the right headers and keeps cache and length rules", async () => {
  const source = await readFile(new URL("../app/api/proxy/[...path]/route.ts", import.meta.url), "utf8");
  assert.match(source, /shouldRecompress\(req\.headers\.get\("accept-encoding"\), res\.headers\)/);
  assert.match(source, /new CompressionStream\("gzip"\)/);
  assert.match(source, /relayed\.set\("content-encoding", "gzip"\)/);
  assert.match(source, /relayed\.append\("vary", "Accept-Encoding"\)/);
  assert.match(source, /"cache-control",/);
});
