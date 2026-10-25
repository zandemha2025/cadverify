/**
 * API keys on the v4 API page: the secret comes back in the action's result
 * (never a cookie), a key whose secret didn't come back is revoked at once,
 * and the access/expiry wording.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/account/api-keys.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mintWith, type Backend } from "./key-mint.ts";
import { keyAccessLabel, keyExpiryLabel, keyStatus, scopeChoices, scopeName, KEY_EXPIRY_DEFAULT } from "./derive.ts";

const SECRET = "cv_live_AbCd1234_0123456789abcdefghijABCDEFGHIJ01";

type Call = { url: string; method: string; body: unknown; cookie: string | null };
function backend(answers: Array<Response | Error>): { b: Backend; calls: Call[] } {
  const calls: Call[] = [];
  const f = (async (url: string, init?: RequestInit) => {
    const h = new Headers(init?.headers);
    calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : null, cookie: h.get("cookie") });
    const next = answers.shift();
    if (!next) throw new Error("unexpected call");
    if (next instanceof Error) throw next;
    return next;
  }) as typeof fetch;
  return { b: { url: (p) => `http://api.test${p}`, fetch: f }, calls };
}
const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

test("create sends name, access and expiry, and returns the secret from the body", async () => {
  const { b, calls } = backend([json(200, { id: 7, prefix: "AbCd1234", name: "PLM", scope: "read", effective_scope: "read", expires_at: "2027-01-20T00:00:00+00:00", secret: SECRET })]);
  const r = await mintWith(b, "sess", { kind: "create", name: "  PLM  ", scope: "read", expiresInDays: 90 });
  assert.equal(r.ok, true);
  assert.ok(r.ok && r.key.secret === SECRET && r.key.id === 7 && r.key.expiresAt === "2027-01-20T00:00:00+00:00");
  assert.deepEqual(calls[0].body, { name: "PLM", scope: "read", expires_in_days: 90 });
  assert.equal(calls[0].cookie, "dash_session=sess");
});

test("a key made without its secret is revoked at once, and the message says so", async () => {
  const { b, calls } = backend([json(200, { id: 9, prefix: "Zz9yXx8w" }), new Response(null, { status: 204 })]);
  const r = await mintWith(b, "sess", { kind: "create", name: "x", scope: "read", expiresInDays: null });
  assert.equal(r.ok, false);
  assert.ok(!r.ok && r.made?.revoked === true && r.made.id === 9);
  assert.equal(calls[1].method, "DELETE");
  assert.equal(calls[1].url, "http://api.test/api/v1/keys/9");
  assert.ok(!r.ok && /revoked the key \(cv_live_Zz9yXx8w_…\)/.test(r.error), !r.ok ? r.error : "");
});

test("if that revoke fails too, the message names the key to revoke", async () => {
  const { b } = backend([json(200, { id: 9, prefix: "Zz9yXx8w" }), new Error("down")]);
  const r = await mintWith(b, "sess", { kind: "rotate", id: 3 });
  assert.ok(!r.ok && r.made?.revoked === false);
  assert.ok(!r.ok && r.error.includes("revoking it failed. Revoke cv_live_Zz9yXx8w_… below."));
});

test("an older backend's reveal cookie still works server-side", async () => {
  const { b } = backend([json(200, { id: 4, prefix: "AbCd1234" }, { "set-cookie": `cv_mint_once=${SECRET}; Path=/settings/developer; Max-Age=60` })]);
  const r = await mintWith(b, "sess", { kind: "rotate", id: 3 });
  assert.ok(r.ok && r.key.secret === SECRET);
});

test("a refusal changes nothing and gives the server's words", async () => {
  const { b, calls } = backend([json(403, { detail: { code: "api_key_scope_not_allowed", message: "Viewers can make read-only keys only." } })]);
  const r = await mintWith(b, "sess", { kind: "create", name: "x", scope: "read_write", expiresInDays: 30 });
  assert.ok(!r.ok && r.made === null && r.error === "Viewers can make read-only keys only.");
  assert.equal(calls.length, 1);
});

test("no answer from ScaleCAD reads as unreachable (the page then looks for a key it made)", async () => {
  const { b } = backend([new Error("reset")]);
  const r = await mintWith(b, "sess", { kind: "create", name: "x", scope: "read", expiresInDays: null });
  assert.ok(!r.ok && r.status === 503 && r.made === null);
  assert.ok(!r.ok && (await mintWith(b, null, { kind: "rotate", id: 1 })).status === 401);
});

test("the secret never travels in a cookie the browser can read", () => {
  const src = readFileSync(new URL("./actions.ts", import.meta.url), "utf8") + readFileSync(new URL("./key-mint.ts", import.meta.url), "utf8");
  assert.ok(!/\.set\(\s*["'`]?cv_mint_once|jar\.set|cookies\(\)\.set/.test(src));
  const page = readFileSync(new URL("./api-screen.tsx", import.meta.url), "utf8");
  assert.ok(!page.includes("document.cookie"));
});

test("access and expiry wording", () => {
  assert.equal(scopeName("read"), "Read only");
  assert.equal(scopeName("read_write"), "Read and write");
  assert.deepEqual(scopeChoices("viewer").map((c) => [c.value, c.disabled]), [["read", false], ["read_write", true]]);
  assert.deepEqual(scopeChoices("member").map((c) => c.disabled), [false, false]);
  assert.equal(KEY_EXPIRY_DEFAULT, 90);
  const now = new Date("2026-10-22T12:00:00Z");
  assert.equal(keyExpiryLabel({ revoked_at: null, expires_at: null }, now), "Never");
  assert.equal(keyExpiryLabel({ revoked_at: null, expires_at: "2027-01-20 12:00:00+00:00" }, now), "Jan 20, 2027");
  assert.equal(keyExpiryLabel({ revoked_at: null, expires_at: "2026-10-01T00:00:00+00:00" }, now), "Expired Oct 1, 2026");
  assert.deepEqual(keyStatus({ revoked_at: null, expires_at: "2026-10-01T00:00:00+00:00" }, now), { tone: "warn", label: "Expired" });
  assert.deepEqual(keyStatus({ revoked_at: "2026-10-02", expires_at: null }, now), { tone: "unk", label: "Revoked" });
  assert.equal(keyAccessLabel({ revoked_at: null, scope: "read_write", effective_scope: "read" }), "Read only (viewer)");
  assert.equal(keyAccessLabel({ revoked_at: null, scope: "read_write", effective_scope: "read_write" }), "Read and write");
});
