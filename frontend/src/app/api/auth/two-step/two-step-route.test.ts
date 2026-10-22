import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { mock, test } from "node:test";

// Stand-ins for the cookie helpers (they need next/headers): record what the
// handlers store, so the tests can prove no token reaches the browser body.
const sessionStub =
  "data:text/javascript,export const jar={session:null,token:'live-session-token-0123456789abcdef'};" +
  "export async function setSession(t){jar.session=t};export async function getSessionToken(){return jar.token};" +
  "export async function setRevealOnce(){}";
const challengeStub =
  "data:text/javascript,export const jar={challenge:null,cleared:0};" +
  "export function isChallenge(v){return typeof v==='string'&&v.startsWith('ts1.')&&v.length>=16};" +
  "export function isPurpose(v){return v==='verify'||v==='setup'};" +
  "export async function setTwoStepChallenge(t){jar.challenge=t};" +
  "export async function getTwoStepChallenge(){return jar.challenge};" +
  "export async function clearTwoStepChallenge(){jar.challenge=null;jar.cleared++}";
const lib = (p: string) => new URL(`../../../../lib/${p}`, import.meta.url).href;
const hooks = registerHooks({
  resolve(specifier, context, next) {
    if (specifier === "next/server") return next("next/server.js", context);
    if (specifier === "server-only") return next("data:text/javascript,", context);
    if (specifier === "@/lib/session") return next(sessionStub, context);
    if (specifier === "@/lib/two-step-cookie") return next(challengeStub, context);
    if (specifier === "@/lib/api-base") return next(lib("api-base.ts"), context);
    if (specifier === "@/lib/auth-proxy") return next(lib("auth-proxy.ts"), context);
    if (specifier === "@/lib/same-origin-request") return next(lib("same-origin-request.ts"), context);
    if (specifier === "./auth-proxy-ip") return next(lib("auth-proxy-ip.ts"), context);
    return next(specifier, context);
  },
});
const twoStep = await import("./[action]/route.ts");
const login = await import("../login/route.ts");
const exchange = await import("../magic/exchange/route.ts");
const session = await import(sessionStub);
const challenge = await import(challengeStub);
hooks.deregister();

const CHALLENGE = "ts1.eyJ1Ijo3fQ.c2lnbmF0dXJlLXNpZ25hdHVyZQ";
const SESSION = "s".repeat(40);

function req(path: string, method = "POST", body: unknown = {}) {
  return new Request(`http://localhost${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: method === "GET" ? undefined : JSON.stringify(body),
  });
}

test("login with two-step owed keeps the challenge in the cookie, never in the body, and sets no session", async () => {
  process.env.API_BASE = "http://127.0.0.1:8000";
  session.jar.session = null;
  challenge.jar.challenge = null;
  const fetchMock = mock.method(globalThis, "fetch", async () =>
    Response.json({ user: { id: 7 }, two_step: "verify", challenge: CHALLENGE }),
  );
  try {
    const res = await login.POST(req("/api/auth/login", "POST", { email: "a@b.co", password: "x" }));
    const body = await res.json();
    assert.equal(res.status, 200);
    assert.deepEqual(body, { two_step: "verify" });
    assert.equal(challenge.jar.challenge, CHALLENGE);
    assert.equal(session.jar.session, null);
    assert.equal(res.headers.get("cache-control"), "no-store");
  } finally {
    fetchMock.mock.restore();
  }
});

test("login without two-step is unchanged: the session cookie is set and no challenge", async () => {
  session.jar.session = null;
  challenge.jar.challenge = null;
  const fetchMock = mock.method(globalThis, "fetch", async () => Response.json({ user: { id: 7 }, session: SESSION }));
  try {
    const res = await login.POST(req("/api/auth/login", "POST", { email: "a@b.co", password: "x" }));
    assert.deepEqual(await res.json(), { user: { id: 7 } });
    assert.equal(session.jar.session, SESSION);
    assert.equal(challenge.jar.challenge, null);
  } finally {
    fetchMock.mock.restore();
  }
});

test("email link with two-step owed sends the person to the code page without a session", async () => {
  session.jar.session = null;
  challenge.jar.challenge = null;
  const fetchMock = mock.method(globalThis, "fetch", async () =>
    Response.json({ two_step: "setup", challenge: CHALLENGE, redirect: "/login/two-step" }),
  );
  try {
    const res = await exchange.POST(req("/api/auth/magic/exchange", "POST", { token: "t".repeat(64) }));
    assert.deepEqual(await res.json(), { two_step: "setup", redirect: "/login/two-step" });
    assert.equal(challenge.jar.challenge, CHALLENGE);
    assert.equal(session.jar.session, null);
  } finally {
    fetchMock.mock.restore();
  }
});

test("verify sends the cookie's challenge, sets the session itself and strips the token", async () => {
  session.jar.session = null;
  challenge.jar.challenge = CHALLENGE;
  challenge.jar.cleared = 0;
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchMock = mock.method(globalThis, "fetch", async (url: unknown, init: RequestInit) => {
    calls.push({ url: String(url), init });
    return Response.json({ user: { id: 7 }, session: SESSION, used: "code", recovery_codes_left: 10 });
  });
  try {
    const res = await twoStep.POST(req("/api/auth/two-step/verify", "POST", { code: "123456", challenge: "forged", session: "forged" }), {
      params: Promise.resolve({ action: "verify" }),
    });
    const body = await res.json();
    assert.equal(res.status, 200);
    assert.ok(!("session" in body) && !("challenge" in body));
    assert.equal(body.used, "code");
    assert.equal(session.jar.session, SESSION);
    assert.equal(challenge.jar.cleared, 1);
    assert.equal(calls[0].url, "http://127.0.0.1:8000/auth/two-step/challenge/verify");
    // The browser can't substitute its own challenge: the cookie's is sent.
    assert.deepEqual(JSON.parse(String(calls[0].init.body)), { code: "123456", challenge: CHALLENGE });
  } finally {
    fetchMock.mock.restore();
  }
});

test("a wrong code keeps the challenge; an expired one is dropped", async () => {
  challenge.jar.challenge = CHALLENGE;
  let reply = () => Response.json({ detail: { code: "two_step_code_wrong", message: "That code didn't match." } }, { status: 400 });
  const fetchMock = mock.method(globalThis, "fetch", async () => reply());
  try {
    let res = await twoStep.POST(req("/api/auth/two-step/verify", "POST", { code: "000000" }), { params: Promise.resolve({ action: "verify" }) });
    assert.equal(res.status, 400);
    assert.equal(challenge.jar.challenge, CHALLENGE);
    reply = () => Response.json({ detail: { code: "two_step_challenge_invalid", message: "Sign in again." } }, { status: 401 });
    res = await twoStep.POST(req("/api/auth/two-step/verify", "POST", { code: "000000" }), { params: Promise.resolve({ action: "verify" }) });
    assert.equal(res.status, 401);
    assert.equal(challenge.jar.challenge, null);
    // The app's own (flattened) error body is read the same way.
    challenge.jar.challenge = CHALLENGE;
    reply = () => Response.json({ code: "two_step_challenge_invalid", message: "Sign in again." }, { status: 401 });
    res = await twoStep.POST(req("/api/auth/two-step/verify", "POST", { code: "000000" }), { params: Promise.resolve({ action: "verify" }) });
    assert.equal(challenge.jar.challenge, null);
  } finally {
    fetchMock.mock.restore();
  }
});

test("account actions forward the session, and a re-issued session never reaches the browser", async () => {
  session.jar.session = null;
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchMock = mock.method(globalThis, "fetch", async (url: unknown, init: RequestInit) => {
    calls.push({ url: String(url), init });
    return Response.json({ ok: true, session: SESSION });
  });
  try {
    const res = await twoStep.POST(req("/api/auth/two-step/sign-out-others"), { params: Promise.resolve({ action: "sign-out-others" }) });
    assert.deepEqual(await res.json(), { ok: true });
    assert.equal(session.jar.session, SESSION);
    assert.equal(calls[0].url, "http://127.0.0.1:8000/auth/sessions/sign-out-others");
    assert.equal(new Headers(calls[0].init.headers).get("cookie"), `dash_session=${session.jar.token}`);
    const unknown = await twoStep.POST(req("/api/auth/two-step/whatever"), { params: Promise.resolve({ action: "whatever" }) });
    assert.equal(unknown.status, 404);
    const wrongMethod = await twoStep.GET(req("/api/auth/two-step/verify", "GET"), { params: Promise.resolve({ action: "verify" }) });
    assert.equal(wrongMethod.status, 405);
    assert.equal(calls.length, 1);
  } finally {
    fetchMock.mock.restore();
  }
});

test("a cross-site page can't drive the two-step actions", async () => {
  const fetchMock = mock.method(globalThis, "fetch", async () => Response.json({}));
  try {
    const res = await twoStep.POST(
      new Request("http://localhost/api/auth/two-step/disable", {
        method: "POST",
        headers: { "content-type": "application/json", origin: "https://evil.example" },
        body: "{}",
      }),
      { params: Promise.resolve({ action: "disable" }) },
    );
    assert.equal(res.status, 403);
    assert.equal(fetchMock.mock.callCount(), 0);
  } finally {
    fetchMock.mock.restore();
  }
});
