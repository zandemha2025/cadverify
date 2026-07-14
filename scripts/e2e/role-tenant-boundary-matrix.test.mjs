import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./role-tenant-boundary-matrix.mjs", import.meta.url),
  "utf8",
);

function method(name, nextName) {
  const start = source.indexOf(`async ${name}(`);
  assert.ok(start >= 0, `${name} method is missing`);
  const end = nextName ? source.indexOf(`async ${nextName}(`, start + 1) : source.length;
  assert.ok(end > start, `${name} method boundary is missing`);
  return source.slice(start, end);
}

test("every dashboard identity logs in through Chromium and proves its session cookie", () => {
  const login = method("login", "relogin");
  assert.match(login, /page\.goto\("\/login"/);
  assert.match(login, /email\.fill\(identity\.email\)/);
  assert.match(login, /passwordInput\.fill\(password\)/);
  assert.match(login, /await submit\.click\(\)/);
  assert.match(login, /context\.cookies\(\)/);
  assert.match(login, /item\.name === "dash_session"/);
  assert.doesNotMatch(login, /context\.request|if \(name === "owner"\)/);
});

test("dashboard setup, reads, and mutations are constrained to in-page /api/proxy fetch", () => {
  const inPageFetch = method("inPageFetch", "request");
  assert.match(inPageFetch, /page\.evaluate/);
  assert.match(inPageFetch, /await fetch\(requestTarget/);
  assert.match(inPageFetch, /new FormData\(\)/);
  assert.match(inPageFetch, /credentials/);

  const request = method("request", "apiKeyRequest");
  assert.match(request, /dashboard request must use an \/api\/v1 path/);
  assert.match(request, /dashboard proxy requests cannot carry bearer credentials/);
  assert.match(request, /dashboard proxy requests cannot carry custom headers/);
  assert.match(request, /dashboard proxy requests always use same-origin credentials/);
  assert.match(request, /`\/api\/proxy\$\{proxyPath\}`/);
  assert.match(request, /this\.inPageFetch\(actor\.page/);
  assert.match(request, /credentials: "same-origin"/);
  assert.doesNotMatch(request, /apiUrl|authorization|cookie/i);

  const setup = method("createTenantResources", "waitForDesignReady");
  assert.match(setup, /this\.request\(actor, "\/api\/v1\/designs"/);
  assert.match(setup, /this\.request\(actor, "\/api\/v1\/validate"/);
  assert.match(setup, /this\.request\(actor, "\/api\/v1\/validate\/cost"/);
  assert.doesNotMatch(setup, /apiKeyRequest|apiUrl|context\.request/);

  assert.doesNotMatch(source, /context\.request/);
  assert.doesNotMatch(source, /this\.request\([^\n]*"\/auth\/me"/);
  assert.doesNotMatch(source, /AUTH_PROXY_SECRET|x-auth-proxy|proxy[_-]secret/i);
});

test("API-key-only probes are isolated from dashboard fixture setup", () => {
  const apiKeyRequest = method("apiKeyRequest", "switchOrg");
  assert.match(apiKeyRequest, /bearer\.startsWith\("cv_live_"\)/);
  assert.match(apiKeyRequest, /headers: \{ authorization: `Bearer \$\{bearer\}` \}/);
  assert.match(apiKeyRequest, /credentials: "omit"/);
  assert.doesNotMatch(apiKeyRequest, /api\/proxy|AUTH_PROXY_SECRET|dash_session/);

  const prepare = method("prepare", "runRoleCapabilityMatrix");
  assert.doesNotMatch(prepare, /apiKeyRequest/);
  const lifecycle = method("runBearerAndMembershipLifecycle", "runStaleSessionLifecycle");
  assert.equal((lifecycle.match(/this\.apiKeyRequest\(/g) || []).length, 7);
  assert.match(lifecycle, /api_key_org_bound/);
  assert.match(lifecycle, /api_key_org_mismatch/);
  assert.match(lifecycle, /revoked A key denial code/);
});

test("role denials and cross-tenant known-vs-unknown opacity remain exact", () => {
  const roles = method("runRoleCapabilityMatrix", "scopedListRow");
  assert.match(roles, /expected\.platformCreate \? 200 : 403/);
  assert.match(roles, /insufficient_role/);
  assert.match(roles, /insufficient_org_role/);
  assert.match(roles, /platform_superadmin_required/);

  const opaque = method("opaqueForeign", "prepare");
  assert.match(opaque, /known foreign status equals ghost/);
  assert.match(opaque, /options\.expectedStatus \?\? 404/);
  assert.match(opaque, /foreign response equals ghost/);
  assert.match(opaque, /foreign response has no metadata/);

  const crossTenant = method("runSameOrgAndCrossTenantMatrix", "runBearerAndMembershipLifecycle");
  assert.match(crossTenant, /foreign browser proxy status", response\.status\(\), 404/);
  assert.match(crossTenant, /foreign browser page has no A metadata/);
});
