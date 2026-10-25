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

test("a minted local key asks for read and write and refuses a read-only key", async () => {
  const saved = { app: process.env.APP_URL, db: process.env.DATABASE_URL, fetch: globalThis.fetch };
  const bodies = [];
  const mint = (effectiveScope) => async (url, init) => {
    bodies.push({ url: String(url), body: JSON.parse(init.body) });
    if (String(url).endsWith("/api/auth/signup")) {
      return new Response(JSON.stringify({ user: { id: 1 } }), { status: 200, headers: { "set-cookie": "dash_session=session-1; Path=/" } });
    }
    return new Response(JSON.stringify({ id: 7, prefix: "cv_test", scope: "read_write", effective_scope: effectiveScope }), {
      status: 200,
      headers: { "set-cookie": "cv_mint_once=token-1; Path=/" },
    });
  };
  try {
    process.env.APP_URL = "http://localhost:3000";
    process.env.DATABASE_URL = ""; // no database: the paid-access grant is skipped
    globalThis.fetch = mint("read_write");
    const result = await resolveAdminApiKey({ apiBase: "http://127.0.0.1:8000", runId: "scope-test", purpose: "scope" });
    assert.equal(result.token, "token-1");
    const keyRequest = bodies.find((entry) => entry.url === "http://127.0.0.1:8000/api/v1/keys");
    assert.equal(keyRequest.body.scope, "read_write");
    globalThis.fetch = mint("read");
    await assert.rejects(
      resolveAdminApiKey({ apiBase: "http://127.0.0.1:8000", runId: "scope-test", purpose: "scope" }),
      /not read_write/,
    );
  } finally {
    if (saved.app === undefined) delete process.env.APP_URL; else process.env.APP_URL = saved.app;
    if (saved.db === undefined) delete process.env.DATABASE_URL; else process.env.DATABASE_URL = saved.db;
    globalThis.fetch = saved.fetch;
  }
});
