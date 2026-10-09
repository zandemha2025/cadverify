import assert from "node:assert/strict";
import test from "node:test";
import {
  OAuthError,
  buildAuthorizationUrl,
  exchangeAuthorizationCode,
  refreshAccessToken,
  createTokenStore,
} from "../src/oauth.js";

const tokenResponse = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("builds the authorization URL with code grant, scopes and state", () => {
  const url = new URL(buildAuthorizationUrl({ clientId: "cid", redirectUri: "http://localhost:8787/cb", state: "s1" }));
  assert.equal(url.origin + url.pathname, "https://oauth.onshape.com/oauth/authorize");
  assert.equal(url.searchParams.get("response_type"), "code");
  assert.equal(url.searchParams.get("client_id"), "cid");
  assert.equal(url.searchParams.get("redirect_uri"), "http://localhost:8787/cb");
  assert.equal(url.searchParams.get("scope"), "OAuth2Read OAuth2Write");
  assert.equal(url.searchParams.get("state"), "s1");
  assert.throws(() => buildAuthorizationUrl({ clientId: "cid", redirectUri: "http://x" }), TypeError);
});

test("exchanges an authorization code with a form POST and basic auth", async () => {
  const calls = [];
  const token = await exchangeAuthorizationCode({
    code: "code1",
    clientId: "cid",
    clientSecret: "secret",
    redirectUri: "http://localhost:8787/cb",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return tokenResponse({ access_token: "at1", refresh_token: "rt1", expires_in: 3600, token_type: "Bearer" });
    },
  });
  assert.equal(calls[0].url, "https://oauth.onshape.com/oauth/token");
  assert.equal(calls[0].init.method, "POST");
  assert.match(calls[0].init.headers.Authorization, /^Basic /);
  const body = new URLSearchParams(calls[0].init.body);
  assert.equal(body.get("grant_type"), "authorization_code");
  assert.equal(body.get("code"), "code1");
  assert.equal(token.access_token, "at1");
  assert.equal(token.refresh_token, "rt1");
  assert.ok(token.expires_at > Date.now());
});

test("public clients (no secret) send client_id in the body instead of basic auth", async () => {
  const calls = [];
  await exchangeAuthorizationCode({
    code: "c", clientId: "cid", redirectUri: "http://x/cb",
    fetchImpl: async (url, init) => { calls.push(init); return tokenResponse({ access_token: "at" }); },
  });
  assert.equal(calls[0].headers.Authorization, undefined);
  assert.equal(new URLSearchParams(calls[0].body).get("client_id"), "cid");
});

test("refresh uses the refresh_token grant", async () => {
  const calls = [];
  const token = await refreshAccessToken({
    refreshToken: "rt1", clientId: "cid", clientSecret: "secret",
    fetchImpl: async (url, init) => { calls.push(init); return tokenResponse({ access_token: "at2", refresh_token: "rt2", expires_in: 60 }); },
  });
  const body = new URLSearchParams(calls[0].body);
  assert.equal(body.get("grant_type"), "refresh_token");
  assert.equal(body.get("refresh_token"), "rt1");
  assert.equal(token.access_token, "at2");
});

test("token endpoint errors surface as OAuthError with status", async () => {
  await assert.rejects(
    () => exchangeAuthorizationCode({
      code: "bad", clientId: "cid", redirectUri: "http://x",
      fetchImpl: async () => tokenResponse({ error: "invalid_grant", error_description: "expired code" }, 400),
    }),
    (error) => error instanceof OAuthError && error.status === 400 && /expired code/.test(error.message),
  );
});

test("token store tracks expiry with leeway", () => {
  let now = 1_000_000;
  const store = createTokenStore({ now: () => now, leewayMs: 1_000 });
  assert.ok(store.isExpired());
  store.set({ access_token: "at", refresh_token: "rt", expires_in: 10 });
  assert.equal(store.isExpired(), false);
  now += 9_500;
  assert.equal(store.isExpired(), true); // inside leeway
  assert.equal(store.needsRefresh(), true);
  store.clear();
  assert.ok(store.isExpired());
});
