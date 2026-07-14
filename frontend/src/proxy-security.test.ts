import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./proxy.ts", import.meta.url), "utf8");

test("CSP permits only the exact configured direct-upload origin", () => {
  assert.match(source, /directUploadConnectOrigin\(/);
  assert.match(source, /connect-src 'self' blob:\$\{directUploadSource\}/);
  assert.doesNotMatch(source, /connect-src[^;]*\*\.amazonaws\.com/);
});

test("CSP permits WebAssembly hashing without enabling JavaScript eval", () => {
  assert.match(source, /script-src[^;]*'wasm-unsafe-eval'/);
  assert.match(source, /NODE_ENV === "development" \? " 'unsafe-eval'" : ""/);
});
