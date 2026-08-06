import assert from "node:assert/strict";
import test from "node:test";

import { isLoopbackOrigin, resolveAdminApiKey } from "./local-admin-api-key.mjs";

test("loopback detection accepts only explicit local origins", () => {
  assert.equal(isLoopbackOrigin("http://localhost:3000"), true);
  assert.equal(isLoopbackOrigin("http://127.0.0.1:8000"), true);
  assert.equal(isLoopbackOrigin("http://[::1]:8000"), true);
  assert.equal(isLoopbackOrigin("https://example.com"), false);
  assert.equal(isLoopbackOrigin("not a URL"), false);
});

test("mixed local API and external app target cannot send signup", async () => {
  const previousAppUrl = process.env.APP_URL;
  const previousFetch = globalThis.fetch;
  let fetches = 0;
  process.env.APP_URL = "https://production.example.com";
  globalThis.fetch = async () => {
    fetches += 1;
    throw new Error("fetch must not be called");
  };
  try {
    const result = await resolveAdminApiKey({
      apiBase: "http://127.0.0.1:8000",
      runId: "mixed-origin-test",
      purpose: "security",
    });
    assert.equal(result.token, "");
    assert.match(result.boundary, /Both APP_URL and API_URL must be loopback/);
    assert.equal(fetches, 0);
  } finally {
    if (previousAppUrl === undefined) delete process.env.APP_URL;
    else process.env.APP_URL = previousAppUrl;
    globalThis.fetch = previousFetch;
  }
});
