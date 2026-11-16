import test from "node:test";
import assert from "node:assert/strict";
import { publicOriginFrom, publicApiOrigin } from "./public-api.ts";

test("API_ORIGIN wins and public API_BASE publishes itself", () => {
  assert.equal(publicApiOrigin("https://api.example.com", "http://backend:8000"), "https://api.example.com");
  assert.equal(publicApiOrigin(undefined, "https://cadverify-api.onrender.com"), "https://cadverify-api.onrender.com");
  assert.equal(publicApiOrigin(null, "https://api.example.com/api/v1/"), "https://api.example.com");
});

test("internal and malformed addresses never publish", () => {
  for (const bad of [
    undefined, null, "", "not a url",
    "http://backend:8000",                 // compose service name
    "http://localhost:8000", "http://127.0.0.1:8000",
    "http://10.1.2.3:8000", "http://192.168.1.4:8000", "http://172.20.1.5:8000",
    "http://api.internal", "http://api.local",
    "ftp://api.example.com",
  ]) {
    assert.equal(publicOriginFrom(bad), null, `expected null for ${String(bad)}`);
  }
  assert.equal(publicApiOrigin(undefined, "http://backend:8000"), null);
  assert.equal(publicApiOrigin(undefined, undefined), null);
});
