/**
 * Invite link facts before sign-in, and the token a sign-up link carries.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/moments/invite-summary.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fetchInviteSummary, inviteTokenFrom, inviterLine, roleMeans, roleWord } from "./invite-summary.ts";

const TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde";

test("the summary names the org, the inviter and the role", async () => {
  const f = (async () =>
    new Response(JSON.stringify({ org_name: "Kestrel Aero", role: "viewer", email: "dana@kestrel.com", invited_by: "sam@kestrel.com", invited_by_name: "Sam Okafor", expires_at: null }), { status: 200 })) as unknown as typeof fetch;
  const r = await fetchInviteSummary(TOKEN, f);
  assert.ok(r.ok && r.summary.org_name === "Kestrel Aero" && r.summary.email === "dana@kestrel.com");
  assert.equal(r.ok && inviterLine(r.summary), "Invited by Sam Okafor (sam@kestrel.com)");
  assert.equal(inviterLine({ invited_by: "sam@kestrel.com", invited_by_name: null }), "Invited by sam@kestrel.com");
  assert.equal(roleWord("viewer"), "Viewer");
});

test("a used or unknown invite says so, with the server's words", async () => {
  const f = (async () => new Response(JSON.stringify({ detail: { message: "This invite has already been used." } }), { status: 409 })) as unknown as typeof fetch;
  assert.deepEqual(await fetchInviteSummary(TOKEN, f), { ok: false, status: 409, message: "This invite has already been used." });
  const down = (async () => { throw new Error("x"); }) as unknown as typeof fetch;
  assert.deepEqual(await fetchInviteSummary(TOKEN, down), { ok: false, status: 503, message: "Could not reach ScaleCAD." });
});

test("a viewer isn't told they'll run checks", () => {
  assert.match(roleMeans("viewer", "Kestrel Aero"), /Viewers don’t check or change parts/);
  assert.doesNotMatch(roleMeans("viewer", "Kestrel Aero"), /machines and rates/);
  assert.match(roleMeans("member", "Kestrel Aero"), /check parts with Kestrel Aero’s machines and rates/);
});

test("the invite token comes from ?invite= or the accept page in next", () => {
  assert.equal(inviteTokenFrom(TOKEN, null), TOKEN);
  assert.equal(inviteTokenFrom(null, `/orgs/accept?token=${TOKEN}&next=%2Fapp%2Fmany%2Fx`), TOKEN);
  assert.equal(inviteTokenFrom(null, "/app/parts"), null);
  assert.equal(inviteTokenFrom("bad token!", "https://evil.example/orgs/accept?token=" + TOKEN), null);
});

test("sign-up from an invite locks the address and drops the free-check pitch and phone", () => {
  const src = readFileSync(new URL("./sign-up.tsx", import.meta.url), "utf8");
  assert.match(src, /readOnly=\{!!invite\}/);
  assert.match(src, /\{inviteToken \? null : <CardField\s+id="phone"/);
  assert.match(src, /invite_token: inviteToken/);
});
