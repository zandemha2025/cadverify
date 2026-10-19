import assert from "node:assert/strict";
import test from "node:test";
import { createRelay } from "../server/oauth-relay.mjs";

const ENV = {
  ONSHAPE_CLIENT_ID: "cid",
  ONSHAPE_CLIENT_SECRET: "secret",
  PROOFSHAPE_API_KEY: "cv_live_test",
  PORT: "0",
};
const tokenJson = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function bootRelay(fetchImpl) {
  const relay = createRelay({ env: { ...ENV }, fetchImpl });
  const port = await relay.start(0);
  return { relay, base: `http://127.0.0.1:${port}` };
}

test("full OAuth round trip: start, callback, one-time token handoff, refresh", async () => {
  const tokenCalls = [];
  const fetchImpl = async (url, init) => {
    tokenCalls.push({ url, init });
    const grant = new URLSearchParams(init.body).get("grant_type");
    return grant === "authorization_code"
      ? tokenJson({ access_token: "at1", refresh_token: "rt1", expires_in: 3600 })
      : tokenJson({ access_token: "at2", refresh_token: "rt2", expires_in: 3600 });
  };
  const { relay, base } = await bootRelay(fetchImpl);
  try {
    // 1. start -> redirect to Onshape authorize with state
    const start = await fetch(`${base}/`, { redirect: "manual" });
    assert.equal(start.status, 302);
    const authorize = new URL(start.headers.get("location"));
    assert.equal(authorize.origin + authorize.pathname, "https://oauth.onshape.com/oauth/authorize");
    const state = authorize.searchParams.get("state");
    assert.ok(state);

    // 2. callback with a wrong state is rejected
    const bad = await fetch(`${base}/oauth/onshape/callback?code=x&state=nope`, { redirect: "manual" });
    assert.equal(bad.status, 400);

    // 3. callback with the real state exchanges the code and starts a session
    const cb = await fetch(`${base}/oauth/onshape/callback?code=code1&state=${state}`, { redirect: "manual" });
    assert.equal(cb.status, 302);
    const panelUrl = new URL(cb.headers.get("location"), base);
    assert.equal(panelUrl.pathname, "/panel/index.html");
    const session = panelUrl.searchParams.get("psession");
    assert.ok(session);
    assert.equal(new URLSearchParams(tokenCalls[0].init.body).get("code"), "code1");

    // 4. one-time token handoff, then gone
    const handoff = await fetch(`${base}/session/${session}/token`);
    assert.equal(handoff.status, 200);
    assert.equal((await handoff.json()).access_token, "at1");
    const again = await fetch(`${base}/session/${session}/token`);
    assert.equal(again.status, 410);

    // 5. refresh goes through the relay; refresh token never leaves the server
    const refreshed = await fetch(`${base}/session/${session}/refresh`, { method: "POST" });
    assert.equal(refreshed.status, 200);
    assert.equal((await refreshed.json()).access_token, "at2");
    assert.equal(new URLSearchParams(tokenCalls[1].init.body).get("refresh_token"), "rt1");
  } finally {
    await relay.stop();
  }
});

test("config.js carries the developer key; panel and module files are served", async () => {
  const { relay, base } = await bootRelay(async () => { throw new Error("no token calls expected"); });
  try {
    const config = await fetch(`${base}/panel/config.js`);
    assert.equal(config.status, 200);
    const text = await config.text();
    assert.match(text, /cv_live_test/);
    assert.match(text, /PROOFSHAPE_PLUGIN_CONFIG/);

    const panel = await fetch(`${base}/panel/index.html`);
    assert.equal(panel.status, 200);
    assert.match(await panel.text(), /Check with ProofShape/);

    const mod = await fetch(`${base}/src/index.js`);
    assert.equal(mod.status, 200);
    const core = await fetch(`${base}/core/src/index.js`);
    assert.equal(core.status, 200);

    // path traversal is refused
    const traversal = await fetch(`${base}/panel/..%2F..%2F..%2Fpackage.json`);
    assert.ok([403, 404].includes(traversal.status));
  } finally {
    await relay.stop();
  }
});

test("unconfigured relay fails loudly instead of starting OAuth", async () => {
  const relay = createRelay({ env: { PORT: "0" }, fetchImpl: async () => { throw new Error("unused"); } });
  const port = await relay.start(0);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/`);
    assert.equal(res.status, 500);
    assert.match(await res.text(), /ONSHAPE_CLIENT_ID/);
  } finally {
    await relay.stop();
  }
});
