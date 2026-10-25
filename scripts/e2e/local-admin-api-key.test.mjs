import assert from "node:assert/strict";
import test from "node:test";

import { isLoopbackOrigin, resolveAdminApiKey, grantLocalPaidAccess } from "./local-admin-api-key.mjs";

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


test("paid fixtures cannot modify remote services, remote databases or customer accounts", async () => {
  const saved = { app: process.env.APP_URL, db: process.env.DATABASE_URL };
  try {
    process.env.APP_URL = "https://production.example.com";
    process.env.DATABASE_URL = "postgresql://localhost/test";
    assert.equal(await grantLocalPaidAccess("fixture@example.test"), false);
    process.env.APP_URL = "http://localhost:3000";
    process.env.DATABASE_URL = "postgresql://database.example.com/test";
    assert.equal(await grantLocalPaidAccess("fixture@example.test"), false);
    process.env.DATABASE_URL = "postgresql://localhost/test";
    assert.equal(await grantLocalPaidAccess("customer@company.com"), false);
  } finally {
    if (saved.app === undefined) delete process.env.APP_URL; else process.env.APP_URL = saved.app;
    if (saved.db === undefined) delete process.env.DATABASE_URL; else process.env.DATABASE_URL = saved.db;
  }
});
