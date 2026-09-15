/**
 * ProofShape Onshape OAuth relay (M2 local install/run path).
 *
 * Onshape requires OAuth2 for app-store apps, and the token exchange needs the
 * app's client secret. The secret and the user's ProofShape API key must never
 * ship to other users, so this loopback relay holds both and performs the
 * exchange:
 *
 *   1. Developer runs:  node plugins/onshape/server/oauth-relay.mjs
 *      with ONSHAPE_CLIENT_ID / ONSHAPE_CLIENT_SECRET / PROOFSHAPE_API_KEY set.
 *   2. Browser opens http://127.0.0.1:8787/ -> redirect into Onshape OAuth.
 *   3. Onshape calls back to /oauth/onshape/callback with ?code&state; the
 *      relay validates state and exchanges the code server-side.
 *   4. The panel loads from /panel/ with ?psession=<id>; it fetches the access
 *      token ONCE from /session/<id>/token (one-time handoff, then the token
 *      is dropped server-side). Refresh goes through /session/<id>/refresh so
 *      the refresh token never reaches the browser.
 *
 * Binds 127.0.0.1 only. State and sessions live in memory with TTLs; nothing
 * is written to disk. For a real Onshape extension the same panel is served
 * over HTTPS and the action URL points at that host - the relay is the local
 * install/test path, not a production service.
 */

import http from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import {
  buildAuthorizationUrl,
  exchangeAuthorizationCode,
  refreshAccessToken,
} from "../src/oauth.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL_DIR = path.join(HERE, "..", "panel");
const SRC_DIR = path.join(HERE, "..", "src");
const CORE_DIR = path.join(HERE, "..", "..", "core");

const MIME = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json" };
const STATE_TTL_MS = 10 * 60_000;
const SESSION_TTL_MS = 30 * 60_000;

export function createRelay({
  env = process.env,
  fetchImpl = globalThis.fetch,
  host = "127.0.0.1",
  now = () => Date.now(),
} = {}) {
  const clientId = env.ONSHAPE_CLIENT_ID;
  const clientSecret = env.ONSHAPE_CLIENT_SECRET;
  const proofshapeApiKey = env.PROOFSHAPE_API_KEY;
  const proofshapeBaseUrl = env.PROOFSHAPE_BASE_URL ?? "https://cadverify-api.onrender.com";
  // Requested scopes are operator-configurable (ONSHAPE_SCOPES, space/comma separated);
  // unset falls back to DEFAULT_SCOPES (OAuth2Read + OAuth2Write) in oauth.js.
  const configuredScopes = (env.ONSHAPE_SCOPES ?? "").split(/[\s,]+/).filter(Boolean);

  /** state -> createdAt (OAuth CSRF bindings) */
  const pendingStates = new Map();
  /** sessionId -> { createdAt, refreshToken, handoff: {access_token, expires_at} | null } */
  const sessions = new Map();

  function sweep() {
    for (const [state, created] of pendingStates) if (now() - created > STATE_TTL_MS) pendingStates.delete(state);
    for (const [id, session] of sessions) if (now() - session.createdAt > SESSION_TTL_MS) sessions.delete(id);
  }

  const json = (res, status, body) => {
    res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
    res.end(JSON.stringify(body));
  };

  async function serveStatic(res, root, urlPath) {
    const rel = path.normalize(decodeURIComponent(urlPath)).replace(/^(\.\.[/\\])+/, "");
    const file = path.join(root, rel);
    if (!file.startsWith(root)) { res.writeHead(403); res.end(); return; }
    try {
      const data = await readFile(file);
      res.writeHead(200, { "content-type": MIME[path.extname(file)] ?? "application/octet-stream" });
      res.end(data);
    } catch {
      res.writeHead(404); res.end("not found");
    }
  }

  const server = http.createServer(async (req, res) => {
    sweep();
    const url = new URL(req.url, `http://${host}`);
    const redirectUri = env.ONSHAPE_REDIRECT_URI ?? `http://${host}:${server.address()?.port ?? 8787}/oauth/onshape/callback`;

    if (url.pathname === "/" || url.pathname === "/oauth/onshape/start") {
      if (!clientId || !clientSecret || !proofshapeApiKey) {
        res.writeHead(500, { "content-type": "text/plain" });
        res.end("Relay not configured. Set ONSHAPE_CLIENT_ID, ONSHAPE_CLIENT_SECRET and PROOFSHAPE_API_KEY.");
        return;
      }
      const state = randomBytes(16).toString("hex");
      pendingStates.set(state, now());
      res.writeHead(302, { location: buildAuthorizationUrl({ clientId, redirectUri, state, ...(configuredScopes.length ? { scopes: configuredScopes } : {}) }) });
      res.end();
      return;
    }

    if (url.pathname === "/oauth/onshape/callback") {
      const state = url.searchParams.get("state");
      const code = url.searchParams.get("code");
      if (!state || !pendingStates.delete(state)) { json(res, 400, { error: "unknown_or_expired_state" }); return; }
      if (!code) { json(res, 400, { error: "missing_code", detail: url.searchParams.get("error_description") ?? url.searchParams.get("error") }); return; }
      try {
        const token = await exchangeAuthorizationCode({ code, clientId, clientSecret, redirectUri, fetchImpl });
        const sessionId = randomBytes(16).toString("hex");
        sessions.set(sessionId, { createdAt: now(), refreshToken: token.refresh_token ?? null, handoff: { access_token: token.access_token, expires_at: token.expires_at } });
        res.writeHead(302, { location: `/panel/index.html?psession=${sessionId}` });
        res.end();
      } catch (error) {
        json(res, 502, { error: "token_exchange_failed", detail: error.message });
      }
      return;
    }

    const sessionMatch = /^\/session\/([a-f0-9]{32})\/(token|refresh)$/.exec(url.pathname);
    if (sessionMatch) {
      const [, sessionId, action] = sessionMatch;
      const session = sessions.get(sessionId);
      if (!session) { json(res, 404, { error: "unknown_or_expired_session" }); return; }
      if (action === "token") {
        if (!session.handoff) { json(res, 410, { error: "token_already_collected" }); return; }
        const handoff = session.handoff;
        session.handoff = null; // one-time handoff
        json(res, 200, handoff);
        return;
      }
      // refresh: relay uses the stored refresh token; it never leaves the server
      if (!session.refreshToken) { json(res, 409, { error: "no_refresh_token" }); return; }
      try {
        const token = await refreshAccessToken({ refreshToken: session.refreshToken, clientId, clientSecret, fetchImpl });
        if (token.refresh_token) session.refreshToken = token.refresh_token; // Onshape rotates refresh tokens
        json(res, 200, { access_token: token.access_token, expires_at: token.expires_at });
      } catch (error) {
        json(res, 502, { error: "refresh_failed", detail: error.message });
      }
      return;
    }

    if (url.pathname === "/panel/config.js") {
      // Runtime config for the panel. Loopback-only install: the developer's
      // own ProofShape key, exactly like the M1 "user-supplied key" contract.
      if (!proofshapeApiKey) { json(res, 500, { error: "relay_not_configured" }); return; }
      res.writeHead(200, { "content-type": "text/javascript", "cache-control": "no-store" });
      res.end(`globalThis.PROOFSHAPE_PLUGIN_CONFIG=${JSON.stringify({ baseUrl: proofshapeBaseUrl, apiKey: proofshapeApiKey })};`);
      return;
    }

    if (url.pathname.startsWith("/panel/")) { await serveStatic(res, PANEL_DIR, url.pathname.slice("/panel/".length)); return; }
    if (url.pathname.startsWith("/src/")) { await serveStatic(res, SRC_DIR, url.pathname.slice("/src/".length)); return; }
    if (url.pathname.startsWith("/core/")) { await serveStatic(res, CORE_DIR, url.pathname.slice("/core/".length)); return; }

    res.writeHead(404); res.end("not found");
  });

  return {
    server,
    /** For tests: inspect pending state without exposing it to HTTP. */
    _internals: { pendingStates, sessions },
    start(port = Number(env.PORT ?? 8787)) {
      return new Promise((resolve) => server.listen(port, host, () => resolve(server.address().port)));
    },
    stop() {
      return new Promise((resolve) => server.close(resolve));
    },
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const relay = createRelay();
  relay.start().then((port) => {
    console.log(`ProofShape Onshape relay listening on http://127.0.0.1:${port}`);
    console.log("Open that URL to start the Onshape OAuth flow.");
  });
}
