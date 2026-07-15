import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./auth-role-lifecycle-golden-matrix.mjs", import.meta.url),
  "utf8",
);

test("authenticated lifecycle traffic stays on the browser network stack", () => {
  assert.doesNotMatch(
    source,
    /\.context\.request\b/,
    "authenticated setup or assertions must not use Playwright context.request",
  );
  assert.match(
    source,
    /async browserJson\(actor, pathname, options = \{\}\)[\s\S]*targetUrl\.origin === new URL\(appUrl\)\.origin[\s\S]*actor\.page\.evaluate\([\s\S]*credentials: "same-origin"/,
  );
  assert.match(source, /this\.browserJson\(actor, "\/api\/auth\/login"/);
  assert.match(source, /this\.browserJson\(accepted, "\/api\/proxy\/orgs"\)/);
  assert.match(source, /this\.browserJson\(primary, "\/api\/proxy\/orgs"\)/);
  assert.match(source, /this\.browserJson\(stale, "\/api\/proxy\/orgs"\)/);
  assert.match(source, /this\.browserJson\(recovered, "\/api\/proxy\/orgs"\)/);
  assert.match(source, /this\.browserJson\(viewer, "\/api\/proxy\/orgs\/invites"/);
});

test("production session fixtures retain Secure HttpOnly browser semantics", () => {
  assert.match(
    source,
    /name: "dash_session",[\s\S]*domain: sessionOrigin\.hostname,[\s\S]*path: "\/",[\s\S]*httpOnly: true,[\s\S]*secure: true,[\s\S]*sameSite: "Lax"/,
  );
  assert.match(source, /this\.browserNavigationJson\(stale, `\$\{apiUrl\}\/auth\/me`\)/);
  assert.doesNotMatch(source, /headers:\s*\{\s*cookie:\s*`dash_session=/i);
});

test("ROLE-01 multipart fixtures are created by an in-page browser fetch", () => {
  const start = source.indexOf("async browserCost(actor, filename)");
  const end = source.indexOf("async runRole01()", start);
  assert.ok(start >= 0 && end > start, "browserCost helper was not found");
  const browserCost = source.slice(start, end);

  assert.match(browserCost, /actor\.page\.evaluate/);
  assert.match(browserCost, /new FormData\(\)/);
  assert.match(browserCost, /new Blob\(/);
  assert.match(browserCost, /fetch\(pathname,/);
  assert.match(browserCost, /credentials: "same-origin"/);
  assert.match(browserCost, /AbortSignal\.timeout\(120_000\)/);
  assert.doesNotMatch(browserCost, /context\.request/);
});
