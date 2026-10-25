import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { registerHooks } from "node:module";
import { mock, test } from "node:test";

const sessionStub = "data:text/javascript,export let clears=0;export async function clearSession(){clears++};export function reset(){clears=0}";
const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "next/server") return next("next/server.js", context);
  if (specifier === "server-only") return next("data:text/javascript,", context);
  if (specifier === "@/lib/session") return next(sessionStub, context);
  if (specifier === "@/lib/api-base") return next(new URL("../../../../../lib/api-base.ts", import.meta.url).href, context);
  if (specifier === "@/lib/auth-proxy") return next(new URL("../../../../../lib/auth-proxy.ts", import.meta.url).href, context);
  if (specifier === "./auth-proxy-ip") return next(new URL("../../../../../lib/auth-proxy-ip.ts", import.meta.url).href, context);
  return next(specifier, context);
} });
const { POST } = await import("./[action]/route.ts");
const session = await import(sessionStub);
hooks.deregister();

test("reset proxy signs its boundary, clears cookies only after success, and never returns credentials", async () => {
  const secret = Buffer.alloc(32, 7);
  const oldEnv = { ...process.env };
  process.env.AUTH_PROXY_SECRET = secret.toString("base64");
  process.env.AUTH_PROXY_CLIENT_IP_SOURCE = "nginx";
  process.env.API_BASE = "http://127.0.0.1:8000";
  let reply = () => Response.json({ ok: true, token: "must-not-leak", session: "must-not-leak" });
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchMock = mock.method(globalThis, "fetch", async (url: unknown, init: RequestInit) => {
    calls.push({ url: String(url), init });
    return reply();
  });
  const call = (action: string) => POST(new Request(`http://localhost/api/auth/password/reset/${action}`, {
    method: "POST", headers: { "content-type": "application/json", "x-real-ip": "203.0.113.7" },
    body: JSON.stringify({ token: "A".repeat(43), password: "ResetPassword456" }),
  }), { params: Promise.resolve({ action }) });
  try {
    session.reset();
    let response = await call("start");
    assert.deepEqual(await response.json(), { ok: true });
    assert.equal(session.clears, 0);
    response = await call("complete");
    assert.deepEqual(await response.json(), { ok: true });
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(session.clears, 1);
    const complete = calls.at(-1)!;
    assert.equal(complete.url, "http://127.0.0.1:8000/auth/password/reset/complete");
    const headers = new Headers(complete.init.headers);
    const timestamp = headers.get("x-cadverify-proxy-timestamp");
    const signature = createHmac("sha256", secret).update(`${timestamp}\nPOST\n/auth/password/reset/complete\n203.0.113.7`).digest("base64url");
    assert.equal(headers.get("x-cadverify-proxy-signature"), signature);
    assert.equal(JSON.parse(String(complete.init.body)).token.length, 43);

    session.reset();
    reply = () => Response.json({ detail: { message: "Expired" } }, { status: 400 });
    assert.equal((await call("complete")).status, 400);
    reply = () => Response.json({ code: "weak_password", message: "Use a letter and a number." }, { status: 400 });
    assert.deepEqual(await (await call("complete")).json(), { detail: { message: "Use a letter and a number." } });
    reply = () => Response.json({ message: "must-not-leak", detail: [{ input: "must-not-leak" }] }, { status: 422 });
    assert.equal(JSON.stringify(await (await call("complete")).json()).includes("must-not-leak"), false);
    reply = () => Response.json({}, { status: 200 });
    assert.equal((await call("complete")).status, 502);
    reply = () => Response.json({ detail: "Rate limited" }, { status: 429, headers: { "retry-after": "60" } });
    response = await call("start");
    assert.equal(response.status, 429);
    assert.equal(response.headers.get("retry-after"), "60");
    reply = () => { throw new Error("Transport unavailable"); };
    assert.equal((await call("complete")).status, 503);
    const count = calls.length;
    assert.equal((await call("other")).status, 404);
    assert.equal(calls.length, count);
    assert.equal(session.clears, 0);
  } finally {
    fetchMock.mock.restore();
    for (const key of ["AUTH_PROXY_SECRET", "AUTH_PROXY_CLIENT_IP_SOURCE", "API_BASE"]) {
      if (oldEnv[key] === undefined) delete process.env[key]; else process.env[key] = oldEnv[key];
    }
  }
});
