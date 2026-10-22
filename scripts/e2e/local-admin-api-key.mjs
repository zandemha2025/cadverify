/**
 * Mint an isolated API key through the real local signup and key-management
 * HTTP surfaces. This is intentionally loopback-only: non-local E2E targets
 * must provide an explicit credential and are never mutated automatically.
 */

import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { configuredClientIp } from "./run-scoped-client-ip.mjs";

export function isLoopbackOrigin(apiBase) {
  try {
    const hostname = new URL(apiBase).hostname;
    return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1" || hostname === "[::1]";
  } catch {
    return false;
  }
}

async function jsonResponse(response) {
  const text = await response.text();
  let json = null;
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = { raw: text.slice(0, 500) };
    }
  }
  return { response, json };
}

function revealCookie(response, name) {
  const values = typeof response.headers.getSetCookie === "function"
    ? response.headers.getSetCookie()
    : [response.headers.get("set-cookie") || ""];
  for (const value of values) {
    const match = new RegExp(`(?:^|,\\s*)${name}=([^;,]+)`).exec(value);
    if (match) return decodeURIComponent(match[1]);
  }
  return "";
}

function localAppBase(apiBase) {
  const configured = (process.env.APP_URL || "").trim();
  if (configured) return configured.replace(/\/+$/, "");
  const url = new URL(apiBase);
  url.port = "3000";
  url.pathname = "";
  url.search = "";
  url.hash = "";
  return url.origin;
}

export async function resolveAdminApiKey({ apiBase, configuredToken = "", runId, purpose }) {
  if (configuredToken) {
    return { token: configuredToken, source: "configured credential" };
  }
  const appBase = localAppBase(apiBase);
  if (!isLoopbackOrigin(apiBase) || !isLoopbackOrigin(appBase)) {
    return {
      token: "",
      source: "missing external credential",
      boundary: "Both APP_URL and API_URL must be loopback; non-local targets require an explicit ScaleCad org-admin API key.",
    };
  }

  const nonce = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  const email = `proofshape-${purpose}-${runId}-${nonce}@example.com`
    .toLowerCase()
    .replace(/[^a-z0-9@._+-]/g, "-");
  const password = `ScaleCad-${nonce}-9`;
  // Production auth rejects direct backend signup because only the trusted
  // first-party ingress may attest the client IP. Exercise that real boundary
  // through Next, then use its httpOnly dashboard cookie against the backend.
  const signup = await jsonResponse(await fetch(`${appBase}/api/auth/signup`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "x-real-ip": configuredClientIp(runId, `local-admin-${purpose}`),
    },
    body: JSON.stringify({ email, password }),
  }));
  const session = revealCookie(signup.response, "dash_session");
  if (signup.response.status !== 200 || !signup.json?.user || !session) {
    throw new Error(`local admin signup HTTP ${signup.response.status}: ${JSON.stringify(signup.json)}`);
  }

  await grantLocalPaidAccess(email);
  const created = await jsonResponse(await fetch(`${apiBase}/api/v1/keys`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: `dash_session=${session}`,
    },
    body: JSON.stringify({ name: `E2E ${purpose} ${runId}` }),
  }));
  const token = revealCookie(created.response, "cv_mint_once");
  if (created.response.status !== 200 || !created.json?.id || !token) {
    throw new Error(`local API key creation HTTP ${created.response.status}: ${JSON.stringify(created.json)}`);
  }

  return {
    token,
    source: "throwaway local admin created through real HTTP auth and key-management surfaces",
    accountEmail: email,
    keyPrefix: created.json.prefix,
  };
}


/** Explicit manual entitlement for disposable local paid-feature fixtures only.
 * Public signup and all production targets keep the real ten-check allowance.
 */
export async function grantLocalPaidAccess(email) {
  const app = process.env.APP_URL || "http://localhost:3000";
  const db = process.env.DATABASE_URL || "";
  if (!isLoopbackOrigin(app) || !isLoopbackOrigin(db) || !/@example\.(com|test)$/.test(email)) return false;
  const python = fileURLToPath(new URL("../../backend/.venv/bin/python", import.meta.url));
  await promisify(execFile)(python, ["-c", `
import asyncio, os, sys
import asyncpg
async def main():
    connection = await asyncpg.connect(os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    try:
        result = await connection.execute("UPDATE users SET plan='pilot' WHERE email_lower=$1", sys.argv[1].lower())
        assert result == "UPDATE 1", "Expected exactly one disposable paid fixture"
    finally:
        await connection.close()
asyncio.run(main())
`, email], { timeout: 15000 });
  return true;
}
