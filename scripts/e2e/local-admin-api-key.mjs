/**
 * Mint an isolated API key through the real local signup and key-management
 * HTTP surfaces. This is intentionally loopback-only: non-local E2E targets
 * must provide an explicit credential and are never mutated automatically.
 */

function isLoopbackApi(apiBase) {
  try {
    const hostname = new URL(apiBase).hostname;
    return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
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

function revealCookie(response) {
  const values = typeof response.headers.getSetCookie === "function"
    ? response.headers.getSetCookie()
    : [response.headers.get("set-cookie") || ""];
  for (const value of values) {
    const match = /(?:^|,\s*)cv_mint_once=([^;,]+)/.exec(value);
    if (match) return decodeURIComponent(match[1]);
  }
  return "";
}

export async function resolveAdminApiKey({ apiBase, configuredToken = "", runId, purpose }) {
  if (configuredToken) {
    return { token: configuredToken, source: "configured credential" };
  }
  if (!isLoopbackApi(apiBase)) {
    return {
      token: "",
      source: "missing external credential",
      boundary: "Non-local targets require an explicit ProofShape org-admin API key.",
    };
  }

  const nonce = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  const email = `proofshape-${purpose}-${runId}-${nonce}@example.com`
    .toLowerCase()
    .replace(/[^a-z0-9@._+-]/g, "-");
  const password = `ProofShape-${nonce}-9`;
  const signup = await jsonResponse(await fetch(`${apiBase}/auth/signup`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }));
  if (signup.response.status !== 200 || !signup.json?.session) {
    throw new Error(`local admin signup HTTP ${signup.response.status}: ${JSON.stringify(signup.json)}`);
  }

  const created = await jsonResponse(await fetch(`${apiBase}/api/v1/keys`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: `dash_session=${signup.json.session}`,
    },
    body: JSON.stringify({ name: `E2E ${purpose} ${runId}` }),
  }));
  const token = revealCookie(created.response);
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
