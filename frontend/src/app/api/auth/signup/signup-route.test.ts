/**
 * Signing up from an invite (security review R4, F2 and F4).
 *
 * Accepting no longer switches the active org by itself, so the sign-up proxy
 * asks for it (`switch: true`: signing up from the invite is that choice). An
 * org that requires two-step sign-in ends the new session at the join; the
 * proxy then signs in again with the credentials just typed, which answers with
 * a setup challenge (httpOnly cookie, never the body), or says `signed_out` so
 * the browser goes to sign in. It never keeps the dead session.
 */
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { mock, test } from "node:test";

const sessionStub =
  "data:text/javascript,export const jar={session:null,cleared:0};" +
  "export async function setSession(t){jar.session=t};export async function clearSession(){jar.session=null;jar.cleared++}";
const challengeStub =
  "data:text/javascript,export const jar={challenge:null};" +
  "export function isChallenge(v){return typeof v==='string'&&v.startsWith('ts1.')&&v.length>=16};" +
  "export async function setTwoStepChallenge(t){jar.challenge=t}";
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
const signup = await import("./route.ts");
const session = await import(sessionStub);
const challenge = await import(challengeStub);
hooks.deregister();

process.env.API_BASE = "http://127.0.0.1:8000";
const SESSION = "s".repeat(40);
const CHALLENGE = "ts1.eyJ1Ijo3fQ.c2lnbmF0dXJlLXNpZ25hdHVyZQ";
const TOKEN = "t".repeat(43);

type Call = { path: string; body: Record<string, unknown> };

function backend(answers: Record<string, () => Response>) {
  const calls: Call[] = [];
  const m = mock.method(globalThis, "fetch", async (url: unknown, init?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : {};
    calls.push({ path, body });
    const answer = answers[path];
    return answer ? answer() : Response.json({ detail: "unexpected" }, { status: 500 });
  });
  return { calls, restore: () => m.mock.restore() };
}

function signUpFromInvite() {
  return signup.POST(
    new Request("http://localhost/api/auth/signup", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: "late@kestrel.example", password: "Passw0rd-1", name: "Late", invite_token: TOKEN }),
    }),
  );
}

const made = () => Response.json({ user: { id: 7, email: "late@kestrel.example" }, session: SESSION });

test("signing up from an invite asks to make the org active, and keeps the session when no code is owed", async () => {
  session.jar.session = null;
  session.jar.cleared = 0;
  const { calls, restore } = backend({
    "/auth/signup": made,
    "/api/v1/orgs/invites/accept": () => Response.json({ org_id: "01ORG", org_role: "member", created: true, switched: true, signed_out: false }),
  });
  try {
    const res = await signUpFromInvite();
    const body = await res.json();
    assert.equal(res.status, 200);
    assert.deepEqual(body.invite, { org_id: "01ORG", org_role: "member", signed_out: false });
    assert.equal(body.two_step, undefined);
    assert.equal(body.signed_out, undefined);
    assert.equal(JSON.stringify(body).includes(SESSION), false);
  } finally {
    restore();
  }
  assert.deepEqual(calls.map((c) => c.path), ["/auth/signup", "/api/v1/orgs/invites/accept"]);
  assert.deepEqual(calls[1].body, { token: TOKEN, switch: true });
  assert.equal(session.jar.session, SESSION);
  assert.equal(session.jar.cleared, 0);
});

test("a join that ended the session signs in again for the setup challenge: cookie set, session gone", async () => {
  session.jar.session = null;
  session.jar.cleared = 0;
  challenge.jar.challenge = null;
  const { calls, restore } = backend({
    "/auth/signup": made,
    "/api/v1/orgs/invites/accept": () => Response.json({ org_id: "01ORG", org_role: "member", created: true, switched: true, signed_out: true }),
    "/auth/login": () => Response.json({ user: { id: 7 }, two_step: "setup", challenge: CHALLENGE }),
  });
  try {
    const res = await signUpFromInvite();
    const body = await res.json();
    assert.equal(body.two_step, "setup");
    assert.equal(body.signed_out, undefined);
    assert.equal(JSON.stringify(body).includes(CHALLENGE), false, "the challenge stays in the httpOnly cookie");
  } finally {
    restore();
  }
  assert.deepEqual(calls.map((c) => c.path), ["/auth/signup", "/api/v1/orgs/invites/accept", "/auth/login"]);
  assert.deepEqual(calls[2].body, { email: "late@kestrel.example", password: "Passw0rd-1" });
  assert.equal(challenge.jar.challenge, CHALLENGE);
  assert.equal(session.jar.session, null);
  assert.equal(session.jar.cleared, 1);
});

test("when that sign-in gives no setup step, the answer says signed_out (never a dead session, never silent)", async () => {
  session.jar.session = null;
  session.jar.cleared = 0;
  challenge.jar.challenge = null;
  const { restore } = backend({
    "/auth/signup": made,
    "/api/v1/orgs/invites/accept": () => Response.json({ org_id: "01ORG", org_role: "member", created: true, switched: true, signed_out: true }),
    "/auth/login": () => Response.json({ detail: { code: "password_login_disabled" } }, { status: 403 }),
  });
  try {
    const body = await (await signUpFromInvite()).json();
    assert.equal(body.signed_out, true);
    assert.equal(body.two_step, undefined);
  } finally {
    restore();
  }
  assert.equal(challenge.jar.challenge, null);
  assert.equal(session.jar.session, null);
});
