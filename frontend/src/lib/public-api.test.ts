import { test } from "node:test";
import assert from "node:assert/strict";
import { publicOriginFrom } from "./public-api.ts";

test("the public API address is the configured origin, trimmed", () => {
  assert.equal(publicOriginFrom("https://api.scalecad.ai/"), "https://api.scalecad.ai");
  assert.equal(publicOriginFrom(" https://api.scalecad.ai/api/v1 "), "https://api.scalecad.ai");
  assert.equal(publicOriginFrom("https://cadverify-api.onrender.com"), "https://cadverify-api.onrender.com");
});

test("loopback, unset or odd values are not a public address", () => {
  for (const raw of ["http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000", "http://0.0.0.0:8000", "", undefined, null, "ftp://x.example", "not a url"]) {
    assert.equal(publicOriginFrom(raw as string | undefined), null, String(raw));
  }
});
