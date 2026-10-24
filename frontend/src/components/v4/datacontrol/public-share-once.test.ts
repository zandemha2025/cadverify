/**
 * One view of a share page is one read of the share (and one count against the
 * visitor's 120-an-hour bucket at the API), though generateMetadata and the page
 * both ask for it: readPublicShare is React `cache`d for the request.
 *
 * React's cache only holds inside a React server render, so this renders with the
 * React Server Components renderer Next uses (its vendored react-server-dom-webpack),
 * with `react` and `react-dom` resolved to their react-server builds, as Next does.
 */
import assert from "node:assert/strict";
import { createRequire, registerHooks } from "node:module";
import { Writable } from "node:stream";
import { fileURLToPath } from "node:url";
import { mock, test } from "node:test";

const root = new URL("../../../../", import.meta.url);
const lib = (p: string) => new URL(`../../../lib/${p}`, import.meta.url).href;
const headersStub = "data:text/javascript,export async function headers(){return globalThis.__visitorHeaders ?? new Headers()}";
const hooks = registerHooks({
  resolve(specifier, context, next) {
    // A filesystem path (not a file: URL), so require() and import resolve it alike.
    if (specifier === "react") return next(fileURLToPath(new URL("node_modules/react/react.react-server.js", root)), context);
    if (specifier === "react-dom") return next(fileURLToPath(new URL("node_modules/react-dom/react-dom.react-server.js", root)), context);
    if (specifier === "server-only") return next("data:text/javascript,", context);
    if (specifier === "next/headers") return next(headersStub, context);
    if (specifier === "./auth-proxy-ip") return next(lib("auth-proxy-ip.ts"), context);
    if (specifier.startsWith("@/lib/")) return next(lib(`${specifier.slice(6)}.ts`), context);
    return next(specifier, context);
  },
});
const require = createRequire(import.meta.url);
const React = require("react") as typeof import("react");
const RSC = require("next/dist/compiled/react-server-dom-webpack/server.node") as {
  renderToPipeableStream: (model: unknown, webpackMap: unknown, options?: { onError?: (e: unknown) => void }) => { pipe: (w: Writable) => void };
};
const { readPublicShare } = await import("./public-share.ts");
hooks.deregister();

process.env.API_BASE = "https://api.example.test";
process.env.AUTH_PROXY_SECRET = Buffer.alloc(32, 7).toString("base64");
process.env.AUTH_PROXY_CLIENT_IP_SOURCE = "fly";

/** One request: render the model to the end, as Next renders a page. */
function render(model: unknown): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    const out = new Writable({
      write(c, _e, cb) {
        chunks.push(Buffer.from(c));
        cb();
      },
      final(cb) {
        resolve(Buffer.concat(chunks).toString("utf8"));
        cb();
      },
    });
    RSC.renderToPipeableStream(model, {}, { onError: reject }).pipe(out);
  });
}

const PATH = "/s/pkg/AAAAAAAAAAAA" as const;

/** What Next does for /s/pkg/{id}: generateMetadata's read, then the page's, in the same request. */
async function SharePage() {
  const meta = await readPublicShare<{ title: string }>(PATH);
  const page = await readPublicShare<{ title: string }>(PATH);
  return React.createElement("p", null, `${meta.ok ? meta.data.title : "off"} / ${page.ok ? page.data.title : "off"}`);
}

test("one render of a share page reads the share once, for the metadata and the page", async () => {
  const ips: string[] = [];
  const m = mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    ips.push(new Headers(init?.headers).get("x-cadverify-client-ip") ?? "");
    return Response.json({ title: "Bracket RFQ", parts: [] });
  });
  try {
    (globalThis as { __visitorHeaders?: Headers }).__visitorHeaders = new Headers({ "fly-client-ip": "203.0.113.7" });
    const html = await render(React.createElement(SharePage));
    assert.match(html, /Bracket RFQ \/ Bracket RFQ/);
    assert.equal(ips.length, 1, "one view, one read");
    // The next view is its own request: read again (never another visitor's answer), with its own IP.
    (globalThis as { __visitorHeaders?: Headers }).__visitorHeaders = new Headers({ "fly-client-ip": "198.51.100.23" });
    await render(React.createElement(SharePage));
    assert.deepEqual(ips, ["203.0.113.7", "198.51.100.23"]);
  } finally {
    m.mock.restore();
    delete (globalThis as { __visitorHeaders?: Headers }).__visitorHeaders;
  }
});

test("an ended link is read once per view too, and still reads as ended", async () => {
  let calls = 0;
  const m = mock.method(globalThis, "fetch", async () => {
    calls += 1;
    return Response.json({ code: "share_expired", ended_at: "2026-10-01T00:00:00Z" }, { status: 410 });
  });
  try {
    const html = await render(React.createElement(SharePage));
    assert.match(html, /off \/ off/);
    assert.equal(calls, 1);
  } finally {
    m.mock.restore();
  }
});

test("each share page's metadata and page ask for the same path, so the cache merges them", async () => {
  const { readFileSync } = await import("node:fs");
  const app = new URL("../../../app/", import.meta.url);
  for (const page of ["s/[shortId]/page.tsx", "s/cost/[shortId]/page.tsx", "s/pkg/[shortId]/page.tsx"]) {
    const text = readFileSync(new URL(page, app), "utf8");
    const paths = [...text.matchAll(/readPublicShare<[^>]+>\((`[^`]+`)\)/g)].map((m) => m[1]);
    assert.equal(paths.length, 2, `${page}: generateMetadata and the page each read once`);
    assert.equal(paths[0], paths[1], page);
    assert.match(text, /export async function generateMetadata/, page);
  }
});
