import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./[...path]/route.ts", import.meta.url), "utf8");

test("same-origin proxy relays Idempotency-Key only for idempotent upload endpoints", () => {
  assert.match(
    source,
    /path\.length === 2 && path\[0\] === "uploads" && path\[1\] === "multipart"/,
  );
  assert.match(source, /path\.length === 1 && path\[0\] === "reconstruct"/);
  assert.match(source, /req\.headers\.get\("idempotency-key"\)/);
  assert.match(source, /headers\["idempotency-key"\] = idempotencyKey/);
});
