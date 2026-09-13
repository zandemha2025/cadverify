import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./route.ts", import.meta.url), "utf8");

test("me/usage handler requires a session before any upstream call", () => {
  const token = source.indexOf("const token = await getSessionToken()");
  const missing = source.indexOf("if (!token)", token);
  const authCode = source.indexOf("dashboard_auth_required", missing);
  const upstream = source.indexOf("await fetch(", missing);

  assert.ok(token >= 0, "session lookup is missing");
  assert.ok(missing > token, "missing-session branch must follow session lookup");
  assert.ok(authCode > missing, "missing-session branch must return a structured auth code");
  assert.ok(upstream > authCode, "upstream fetch must happen only after the session check");
});

test("me/usage handler forwards the dash_session cookie and relays status", () => {
  assert.ok(source.includes("/auth/me/usage"), "must target the backend usage route");
  assert.ok(source.includes("dash_session=${token}"), "must forward the session cookie");
  assert.ok(source.includes("status: res.status"), "must relay the backend status verbatim");
});
