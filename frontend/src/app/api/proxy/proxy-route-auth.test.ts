import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./[...path]/route.ts", import.meta.url),
  "utf8",
);

test("same-origin proxy rejects a missing session before reading an upload body", () => {
  const token = source.indexOf("const token = await getSessionToken()");
  const missing = source.indexOf("if (!token)", token);
  const authCode = source.indexOf('code: "dashboard_auth_required"', missing);
  const prepare = source.indexOf("prepareProxyRequestBody", authCode);
  const upstream = source.indexOf("await fetch(target, init)", prepare);

  assert.ok(token >= 0, "session lookup is missing");
  assert.ok(missing > token, "missing-session branch must follow session lookup");
  assert.ok(authCode > missing, "missing-session branch must return a structured auth code");
  assert.ok(prepare > authCode, "missing-session rejection must happen before request-body preparation");
  assert.ok(upstream > prepare, "upstream fetch must happen only after the authenticated body is prepared");
});
