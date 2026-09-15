/**
 * Onshape OAuth2 helpers.
 *
 * Flow grounded in https://onshape-public.github.io/docs/auth/oauth/:
 *   1. Send the user to the authorization URL with client_id, redirect_uri,
 *      response_type=code, scope and state.
 *   2. Onshape redirects back with ?code=...&state=...
 *   3. Exchange the code at the token endpoint for an access token plus a
 *      refresh token. Store both; every refresh returns a NEW refresh token
 *      that replaces the previous one.
 *   4. Call the Onshape API under /api with `Authorization: Bearer <token>`.
 *      A 401 means the token expired - refresh once and retry.
 *
 * The client secret must never ship to other users. In the browser panel the
 * exchange is performed by the loopback relay (server/oauth-relay.mjs); these
 * helpers are the shared, testable core used by that relay.
 */

export class OAuthError extends Error {
  constructor(message, { status, body } = {}) {
    super(message);
    this.name = "OAuthError";
    this.status = status;
    this.body = body;
  }
}

export const ONSHAPE_AUTHORIZATION_URL = "https://oauth.onshape.com/oauth/authorize";
export const ONSHAPE_TOKEN_URL = "https://oauth.onshape.com/oauth/token";
export const DEFAULT_SCOPES = ["OAuth2Read", "OAuth2Write"];

export function buildAuthorizationUrl({
  authorizationUrl = ONSHAPE_AUTHORIZATION_URL,
  clientId,
  redirectUri,
  scopes = DEFAULT_SCOPES,
  state,
}) {
  if (!clientId) throw new TypeError("clientId is required");
  if (!redirectUri) throw new TypeError("redirectUri is required");
  if (!state) throw new TypeError("state is required to bind the callback to this session");
  const url = new URL(authorizationUrl);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("scope", scopes.join(" "));
  url.searchParams.set("state", state);
  return url.toString();
}

function basicAuthHeader(clientId, clientSecret) {
  return `Basic ${btoa(`${clientId}:${clientSecret}`)}`;
}

async function postTokenRequest({ tokenUrl, formFields, clientId, clientSecret, fetchImpl }) {
  if (typeof fetchImpl !== "function") throw new TypeError("fetch implementation is required");
  const body = new URLSearchParams(formFields);
  const headers = {
    "Content-Type": "application/x-www-form-urlencoded",
    Accept: "application/json",
  };
  if (clientSecret) headers.Authorization = basicAuthHeader(clientId, clientSecret);
  else body.set("client_id", clientId);
  const response = await fetchImpl(tokenUrl, { method: "POST", headers, body });
  const text = await response.text();
  let parsed = null;
  try { parsed = text ? JSON.parse(text) : null; } catch { parsed = null; }
  if (!response.ok) {
    throw new OAuthError(
      `Onshape token endpoint returned ${response.status}: ${parsed?.error_description ?? parsed?.error ?? text ?? "unknown error"}`,
      { status: response.status, body: parsed ?? text },
    );
  }
  if (!parsed?.access_token) {
    throw new OAuthError("Onshape token endpoint response did not include an access_token", { body: parsed });
  }
  return stampExpiry(parsed);
}

function stampExpiry(token, now = Date.now()) {
  const expiresIn = Number(token.expires_in);
  return {
    ...token,
    expires_at: Number.isFinite(expiresIn) && expiresIn > 0 ? now + expiresIn * 1000 : null,
  };
}

export function exchangeAuthorizationCode({
  tokenUrl = ONSHAPE_TOKEN_URL,
  code,
  clientId,
  clientSecret,
  redirectUri,
  fetchImpl,
}) {
  if (!code) throw new TypeError("authorization code is required");
  if (!clientId) throw new TypeError("clientId is required");
  return postTokenRequest({
    tokenUrl,
    clientId,
    clientSecret,
    fetchImpl,
    formFields: {
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
    },
  });
}

export function refreshAccessToken({
  tokenUrl = ONSHAPE_TOKEN_URL,
  refreshToken,
  clientId,
  clientSecret,
  fetchImpl,
}) {
  if (!refreshToken) throw new TypeError("refreshToken is required");
  if (!clientId) throw new TypeError("clientId is required");
  return postTokenRequest({
    tokenUrl,
    clientId,
    clientSecret,
    fetchImpl,
    formFields: {
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    },
  });
}

/**
 * In-memory token holder with expiry awareness. The relay persists nothing to
 * disk; a storage adapter can be supplied by hosts that want persistence.
 */
export function createTokenStore({ now = () => Date.now(), leewayMs = 60_000, storage } = {}) {
  let token = storage?.get?.() ?? null;
  return {
    get() { return token; },
    set(next) {
      token = next ? stampExpiry(next, now()) : null;
      storage?.set?.(token);
      return token;
    },
    clear() {
      token = null;
      storage?.set?.(null);
    },
    isExpired() {
      if (!token?.access_token) return true;
      if (token.expires_at == null) return false;
      return now() >= token.expires_at - leewayMs;
    },
    needsRefresh() {
      return Boolean(token?.refresh_token) && this.isExpired();
    },
  };
}
