import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { test, mock } from "node:test";

const headersModule = `data:text/javascript,${encodeURIComponent(`
  let token = "qa-session";
  export const setToken = value => { token = value; };
  export const cookies = async () => ({ get: () => token ? { value: token } : undefined });
  export const headers = async () => new Headers({ "x-proofshape-request-path": "/cost-decisions/compare?audit=1" });
`)}`;
const navigationModule = `data:text/javascript,${encodeURIComponent(`
  export const redirect = url => { throw new Error("redirect:" + url); };
`)}`;
const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "next/headers") return next(headersModule, context);
  if (specifier === "next/navigation") return next(navigationModule, context);
  if (["./session", "./api-base", "./safe-return-path", "./organization-access"].includes(specifier)) {
    return next(new URL(`${specifier}.ts`, import.meta.url).href, context);
  }
  return next(specifier, context);
} });
const { getUser, verifySession } = await import("./dal.ts");
const { setToken } = await import(headersModule);
hooks.deregister();

test("session gate distinguishes rejected credentials from unavailable verification", async () => {
  const user = { id: 7, email: "audit@example.test", role: "analyst", auth_provider: "password", has_password: true };
  let reply = async () => Response.json(user);
  const fetchMock = mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    assert.equal(init?.cache, "no-store");
    assert.ok(init?.signal instanceof AbortSignal, "Session verification must have a deadline");
    assert.equal(new Headers(init?.headers).get("Cookie"), "dash_session=qa-session");
    return reply();
  });
  const login = /redirect:\/login\?next=%2Fcost-decisions%2Fcompare%3Faudit%3D1/;
  const unavailable = (error: Error) => !error.message.startsWith("redirect:");
  try {
    setToken(null);
    assert.equal(await getUser(), null);
    await assert.rejects(verifySession(), login);
    assert.equal(fetchMock.mock.callCount(), 0, "No cookie must make no upstream request");
    setToken("qa-session");
    for (const status of [401, 403]) {
      reply = async () => Response.json({ detail: "Rejected" }, { status });
      assert.equal(await getUser(), null);
      await assert.rejects(verifySession(), login);
    }
    for (const status of [429, 500, 502, 503, 504, 404]) {
      reply = async () => Response.json({ detail: "Unavailable" }, { status });
      await assert.rejects(verifySession(), unavailable, `HTTP${status} must not pretend the session was rejected`);
    }
    for (const failure of [new TypeError("fetch failed"), new DOMException("timeout", "TimeoutError")]) {
      reply = async () => { throw failure; };
      await assert.rejects(verifySession(), unavailable);
    }
    reply = async () => new Response("not JSON");
    await assert.rejects(verifySession(), unavailable);
    for (const malformed of [null, {}, [], { ...user, id: 0 }, { ...user, role: null }, { ...user, has_password: "yes" }]) {
      reply = async () => Response.json(malformed);
      await assert.rejects(verifySession(), unavailable, "Malformed verification must not admit a user or redirect to login");
    }
    for (const valid of [user, { ...user, has_password: false }, { id: 7, email: user.email, role: "analyst", auth_provider: "saml" }]) {
      reply = async () => Response.json(valid);
      assert.deepEqual(await verifySession(), valid, "Retry can verify the same unchanged session");
    }
  } finally {
    setToken("qa-session");
    fetchMock.mock.restore();
  }
});
