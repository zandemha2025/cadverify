import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./notification-decision-golden-matrix.mjs", import.meta.url),
  "utf8",
);

function method(name, nextName) {
  const start = source.indexOf(`async ${name}(`);
  assert.ok(start >= 0, `${name} method is missing`);
  const end = nextName ? source.indexOf(`async ${nextName}(`, start + 1) : source.length;
  assert.ok(end > start, `${name} method boundary is missing`);
  return source.slice(start, end);
}

test("authenticated reads and mutations use the in-page session proxy", () => {
  const request = method("request", "publicRequest");
  assert.match(request, /endpoint\.startsWith\("\/api\/proxy\/"\)/);
  assert.match(request, /page\.evaluate/);
  assert.match(request, /await fetch\(target/);
  assert.match(request, /credentials: "same-origin"/);
  assert.match(request, /custom proxy headers are forbidden/);
  assert.doesNotMatch(request, /apiUrl|authorization|dash_session=/i);

  assert.doesNotMatch(source, /context\.request/);
  assert.doesNotMatch(source, /this\.(?:request|decision|notifications)\(context/);
  assert.doesNotMatch(source, /this\.(?:request|decision|notifications)\([^\n,]*\.context/);
  assert.doesNotMatch(source, /AUTH_PROXY_SECRET|x-auth-proxy|proxy[_-]secret/i);
});

test("signup proves the real browser session cookie before setup", () => {
  const identity = method("newIdentity", "shot");
  assert.match(identity, /page\.goto\("\/signup"/);
  assert.match(identity, /getByRole\("button", \{ name: \/\^Create account\$\//);
  assert.match(identity, /runScopedClientIp\(ipSuffix\)/);
  assert.match(identity, /extraHTTPHeaders: \{ "x-real-ip": clientIp \}/);
  assert.doesNotMatch(identity, /198\.51\.100\.\$\{ipSuffix\}/);
  assert.match(identity, /context\.cookies\(\)/);
  assert.match(identity, /cookie\.name === "dash_session"/);
  assert.match(identity, /sessionCookie\?\.value/);
});

test("repeatable release runs use a run-scoped documentation IP namespace", () => {
  assert.match(source, /function runScopedClientIp\(identityIndex\)/);
  assert.match(source, /\.update\(`\$\{runId\}:\$\{identityIndex\}`\)/);
  assert.match(source, /2001:db8:/);
  assert.match(source, /clientIpMode: "run-scoped-rfc3849"/);
});

test("unauthenticated public-share probes stay separate from the authenticated helper", () => {
  const publicRequest = method("publicRequest", "decision");
  assert.match(publicRequest, /await fetch\(endpoint/);
  assert.doesNotMatch(publicRequest, /dash_session|authorization|api\/proxy/i);

  const exportsBody = method("exports", "crossOrg");
  assert.equal((exportsBody.match(/this\.publicRequest\(/g) || []).length, 2);
  assert.doesNotMatch(exportsBody, /this\.request\(publicContext/);
});

test("cross-tenant proxy probes retain exact 404 and non-mutation oracles", () => {
  const crossOrg = method("crossOrg", "run");
  assert.match(crossOrg, /this\.request\(page, endpoint/);
  assert.match(crossOrg, /`\$\{name\} foreign status`, 404, response\.status/);
  assert.match(crossOrg, /does not leak note/);
  assert.match(crossOrg, /does not leak filename/);
  assert.match(crossOrg, /negative probes do not mutate owner note/);
  assert.match(crossOrg, /negative probes do not mutate owner disposition/);
});
