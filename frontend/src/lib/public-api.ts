/**
 * The API address people outside this server use: scripts with an API key,
 * and identity providers posting to the sign-on endpoints.
 *
 * It comes from the deployment's own configuration, `API_ORIGIN` (the same
 * setting the API uses for its sign-on callbacks), never from `API_BASE`, which
 * is how this web server reaches the API and may be an internal address. A
 * loopback or unset value isn't a public address, so it reads as unknown
 * (null) and the page says so instead of printing an address nobody else can
 * reach.
 */
const LOOPBACK = /^(localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[?::1\]?)$/i;

export function publicOriginFrom(raw: string | undefined | null): string | null {
  if (!raw) return null;
  const cleaned = raw.replace(/\\[rn]/g, "").trim().replace(/\/api\/v1\/?$/, "").replace(/\/+$/, "");
  let url: URL;
  try {
    url = new URL(cleaned);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  if (LOOPBACK.test(url.hostname)) return null;
  return url.origin;
}

export function publicApiOrigin(): string | null {
  return publicOriginFrom(process.env.API_ORIGIN);
}
