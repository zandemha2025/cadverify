/**
 * The API address people outside this server use: scripts with an API key,
 * and identity providers posting to the sign-on endpoints.
 *
 * Sources, in order:
 *  1. `API_ORIGIN` — the deployment's explicit public address (the same
 *     setting the API uses for its sign-on callbacks). Always wins.
 *  2. `API_BASE` — how this web server itself reaches the API. Usually an
 *     internal address (a compose service name, a cluster-internal host),
 *     and then it is NOT publishable and reads as unknown. But on a
 *     single-provider deployment where the web tier calls the API at its
 *     public HTTPS origin, that origin is exactly the address scripts
 *     outside can use too, so it publishes itself with no extra setting.
 *
 * Loopback, private-network, and non-HTTP(S) values are never publishable;
 * they read as unknown (null) and the page says so instead of printing an
 * address nobody else can reach.
 */
const LOOPBACK = /^(localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[?::1\]?)$/i;
const PRIVATE = /^(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|.+\.internal|.+\.local|.+\.localdomain)$/i;

export function publicOriginFrom(raw: string | undefined | null): string | null {
  if (!raw) return null;
  const cleaned = raw.replace(/\\[rn]/g, "").trim().replace(/\/api\/v1\/?$/, "").replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(cleaned)) return null;   // a scheme is required
  let url: URL;
  try {
    url = new URL(cleaned);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  if (LOOPBACK.test(url.hostname) || PRIVATE.test(url.hostname)) return null;
  if (!url.hostname.includes(".")) return null;      // bare service names ("backend") are internal
  return url.origin;
}

export function publicApiOrigin(explicit?: string | undefined | null, base?: string | undefined | null): string | null {
  const fromExplicit = publicOriginFrom(explicit ?? process.env.API_ORIGIN);
  if (fromExplicit) return fromExplicit;
  return publicOriginFrom(base ?? process.env.API_BASE);
}
