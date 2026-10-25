/**
 * Share and invite pages keep a per-visitor rate limit (security review R4, F3).
 *
 * The share pages render on the web server and the invite summary is relayed
 * by it. The API limits both per visitor IP; unsigned, it sees only this
 * server's address, so every visitor of every link shares one bucket (120 an
 * hour for /s/cost, /s/pkg and /s/{id}) and one anonymous client can use it
 * up for everyone. These calls sign the visitor's IP like /api/public-share.
 */
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { mock, test } from "node:test";

const headersStub =
  "data:text/javascript,export async function headers(){return globalThis.__visitorHeaders ?? new Headers()}";
const lib = (p: string) => new URL(`../../../lib/${p}`, import.meta.url).href;
const hooks = registerHooks({
  resolve(specifier, context, next) {
    if (specifier === "server-only") return next("data:text/javascript,", context);
    if (specifier === "next/headers") return next(headersStub, context);
    if (specifier === "next/server") return next("next/server.js", context);
    if (specifier === "./auth-proxy-ip") return next(lib("auth-proxy-ip.ts"), context);
    if (specifier.startsWith("@/lib/")) return next(lib(`${specifier.slice(6)}.ts`), context);
    return next(specifier, context);
  },
});
const { readPublicShare } = await import("./public-share.ts");
const invite = await import("../../../app/api/auth/invite/route.ts");
hooks.deregister();

const SECRET = Buffer.alloc(32, 7);
process.env.API_BASE = "https://api.example.test";
process.env.AUTH_PROXY_SECRET = SECRET.toString("base64");
process.env.AUTH_PROXY_CLIENT_IP_SOURCE = "fly";

type Seen = { url: string; method: string; headers: Record<string, string> };
function recordFetch(body: unknown = { title: "x", parts: [] }) {
  const seen: Seen[] = [];
  const m = mock.method(globalThis, "fetch", async (url: unknown, init?: RequestInit) => {
    seen.push({ url: String(url), method: init?.method ?? "GET", headers: Object.fromEntries(new Headers(init?.headers).entries()) });
    return Response.json(body);
  });
  return { seen, restore: () => m.mock.restore() };
}

function expectedSignature(h: Record<string, string>, method: string, path: string): string {
  const payload = `${h["x-cadverify-proxy-timestamp"]}\n${method}\n${path}\n${h["x-cadverify-client-ip"]}`;
  return createHmac("sha256", SECRET).update(payload).digest("base64url");
}

test("a server-rendered share read carries the visitor's signed IP, not the web server's", async () => {
  const { seen, restore } = recordFetch();
  try {
    for (const ip of ["203.0.113.7", "198.51.100.23"]) {
      (globalThis as { __visitorHeaders?: Headers }).__visitorHeaders = new Headers({ "fly-client-ip": ip, "user-agent": "Supplier browser" });
      const res = await readPublicShare("/s/pkg/AAAAAAAAAAAA");
      assert.equal(res.ok, true);
    }
  } finally {
    restore();
    delete (globalThis as { __visitorHeaders?: Headers }).__visitorHeaders;
  }
  assert.equal(seen.length, 2);
  assert.deepEqual(seen.map((s) => s.url), ["https://api.example.test/s/pkg/AAAAAAAAAAAA", "https://api.example.test/s/pkg/AAAAAAAAAAAA"]);
  // Two visitors, two signed IPs: two buckets at the API.
  assert.deepEqual(seen.map((s) => s.headers["x-cadverify-client-ip"]), ["203.0.113.7", "198.51.100.23"]);
  for (const s of seen) {
    assert.ok(s.headers["x-cadverify-proxy-signature"], `sent only ${JSON.stringify(s.headers)}`);
    assert.equal(s.headers["x-cadverify-proxy-signature"], expectedSignature(s.headers, "GET", "/s/pkg/AAAAAAAAAAAA"));
    assert.equal(s.headers["user-agent"], "Supplier browser");
  }
});

test("with no visitor IP to sign, the read signs nothing (never this server's own address)", async () => {
  const { seen, restore } = recordFetch();
  try {
    (globalThis as { __visitorHeaders?: Headers }).__visitorHeaders = new Headers({ "x-forwarded-for": "203.0.113.9" });
    await readPublicShare("/s/cost/AAAAAAAAAAAA");
  } finally {
    restore();
    delete (globalThis as { __visitorHeaders?: Headers }).__visitorHeaders;
  }
  assert.equal(seen.length, 1);
  assert.equal(seen[0].headers["x-cadverify-proxy-signature"], undefined);
  assert.equal(seen[0].headers["x-cadverify-client-ip"], undefined);
});

test("an ended link still reads as ended through the signed read", async () => {
  const m = mock.method(globalThis, "fetch", async () => Response.json({ code: "share_expired", ended_at: "2026-10-01T00:00:00Z" }, { status: 410 }));
  try {
    assert.deepEqual(await readPublicShare("/s/AAAAAAAAAAAA"), { ok: false, reason: "expired", endedAt: "2026-10-01T00:00:00Z" });
  } finally {
    m.mock.restore();
  }
});

test("the invite summary relay signs the visitor's IP for the summary path", async () => {
  const { seen, restore } = recordFetch({ org_name: "Kestrel", role: "member", email: "dana@kestrel.example" });
  try {
    const req = new Request("http://localhost/api/auth/invite", {
      method: "POST",
      headers: { "content-type": "application/json", "fly-client-ip": "203.0.113.44" },
      body: JSON.stringify({ token: "t".repeat(43) }),
    });
    const res = await invite.POST(req);
    assert.equal(res.status, 200);
  } finally {
    restore();
  }
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, "https://api.example.test/api/v1/orgs/invites/summary");
  assert.equal(seen[0].headers["x-cadverify-client-ip"], "203.0.113.44");
  assert.equal(seen[0].headers["x-cadverify-proxy-signature"], expectedSignature(seen[0].headers, "POST", "/api/v1/orgs/invites/summary"));
});

test("every share page reads through the signed server read", () => {
  const app = new URL("../../../app/", import.meta.url);
  for (const page of ["s/[shortId]/page.tsx", "s/cost/[shortId]/page.tsx", "s/pkg/[shortId]/page.tsx"]) {
    const text = readFileSync(new URL(page, app), "utf8");
    assert.match(text, /import \{ readPublicShare \} from "@\/components\/v4\/datacontrol\/public-share";/, page);
    // The unsigned client helpers would read on this server's address.
    assert.doesNotMatch(text, /fetchShared(Analysis|CostDecision)\(/, page);
  }
  const client = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
  assert.doesNotMatch(client, /export async function readPublicShare/);
});
