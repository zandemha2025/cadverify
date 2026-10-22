/**
 * Login CSRF: the session handlers refuse cross-site browser requests and keep
 * same-origin ones (and scripts) working.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/lib/same-origin-request.test.ts
 */
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { mock, test } from "node:test";

const sessionStub =
  "data:text/javascript,export let sets=0;export async function setSession(){sets++};export async function setRevealOnce(){};export async function clearSession(){};export async function getSessionToken(){return null};export function reset(){sets=0}";
// Two-step challenge cookie helpers (next/headers): never reached in these cases.
const twoStepStub =
  "data:text/javascript,export function isChallenge(){return false};export function isPurpose(){return false};export async function setTwoStepChallenge(){}";
const hooks = registerHooks({
  resolve(specifier, context, next) {
    if (specifier === "next/server") return next("next/server.js", context);
    if (specifier === "server-only") return next("data:text/javascript,", context);
    if (specifier === "@/lib/session") return next(sessionStub, context);
    if (specifier === "@/lib/two-step-cookie") return next(twoStepStub, context);
    if (specifier === "@/lib/same-origin-request") return next(new URL("./same-origin-request.ts", import.meta.url).href, context);
    if (specifier === "@/lib/api-base") return next(new URL("./api-base.ts", import.meta.url).href, context);
    if (specifier === "@/lib/auth-proxy") return next(new URL("./auth-proxy.ts", import.meta.url).href, context);
    if (specifier === "./auth-proxy-ip") return next(new URL("./auth-proxy-ip.ts", import.meta.url).href, context);
    return next(specifier, context);
  },
});
const { isCrossSiteRequest } = await import("./same-origin-request.ts");
const exchange = await import("../app/api/auth/magic/exchange/route.ts");
const login = await import("../app/api/auth/login/route.ts");
const session = await import(sessionStub);
hooks.deregister();

function req(url: string, headers: Record<string, string>, body: unknown = {}) {
  return new Request(url, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
}

test("same-origin, direct and script requests pass; another site's do not", () => {
  const app = "https://app.scalecad.test/api/auth/login";
  assert.equal(isCrossSiteRequest(req(app, { origin: "https://app.scalecad.test", "sec-fetch-site": "same-origin" })), false);
  assert.equal(isCrossSiteRequest(req(app, { "sec-fetch-site": "none" })), false);
  assert.equal(isCrossSiteRequest(req(app, {})), false);
  // Behind a proxy the request URL is internal; the forwarded host is the app's.
  assert.equal(
    isCrossSiteRequest(req("http://10.0.0.5:3000/api/auth/login", { origin: "https://app.scalecad.test", "x-forwarded-host": "app.scalecad.test" })),
    false,
  );
  assert.equal(isCrossSiteRequest(req(app, { origin: "https://evil.example", "sec-fetch-site": "cross-site" })), true);
  assert.equal(isCrossSiteRequest(req(app, { origin: "null" })), true);
  assert.equal(isCrossSiteRequest(req(app, { "sec-fetch-site": "cross-site" })), true);
  assert.equal(isCrossSiteRequest(req(app, { origin: "https://docs.scalecad.test", "sec-fetch-site": "same-site" })), true);
});

test("a cross-site magic-link exchange or login never reaches the backend or sets a session", async () => {
  const calls: string[] = [];
  const fetchMock = mock.method(globalThis, "fetch", async (url: unknown) => {
    calls.push(String(url));
    return Response.json({ session: "s".repeat(64), user: { id: 1 } });
  });
  try {
    session.reset();
    const evil = { origin: "https://evil.example", "sec-fetch-site": "cross-site" };
    const refused = await exchange.POST(req("http://localhost:3000/api/auth/magic/exchange", evil, { token: "t".repeat(43) }));
    assert.equal(refused.status, 403);
    assert.equal((await refused.json()).detail.code, "cross_site_request");
    const refusedLogin = await login.POST(req("http://localhost:3000/api/auth/login", evil, { email: "a@b.c", password: "x" }));
    assert.equal(refusedLogin.status, 403);
    assert.deepEqual(calls, []);
    assert.equal(session.sets, 0);

    const ok = await exchange.POST(
      req("http://localhost:3000/api/auth/magic/exchange", { origin: "http://localhost:3000", "sec-fetch-site": "same-origin" }, { token: "t".repeat(43) }),
    );
    assert.equal(ok.status, 200);
    assert.equal(session.sets, 1);
    assert.equal(calls.length, 1);
  } finally {
    fetchMock.mock.restore();
  }
});
