const DEFAULT_BACKEND_ORIGIN = "http://localhost:8000";

function cleanOrigin(raw: string): string {
  return raw
    .replace(/\\[rn]/g, "")
    .trim()
    .replace(/\/api\/v1\/?$/, "")
    .replace(/\/$/, "");
}

export function backendOrigin(): string {
  return cleanOrigin(process.env.API_BASE || DEFAULT_BACKEND_ORIGIN);
}

/**
 * Browser data calls go SAME-ORIGIN through the Next authed proxy
 * (`/api/proxy/*` → backend `/api/v1/*` with the httpOnly session cookie
 * forwarded server-side). This is what makes the platform session-authed: the
 * browser never holds an API key, and it works cross-origin in production where
 * a direct browser→backend cookie would not be sent. `backendUrl()` remains
 * for server-side proxying. Public share reads use a
 * narrow same-origin public proxy when invoked in a browser, keeping the image
 * independent of staging/production hostnames.
 */
export const API_BASE = "/api/proxy";

export function backendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${backendOrigin()}${normalizedPath}`;
}

export function browserOrBackendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return typeof window === "undefined"
    ? backendUrl(normalizedPath)
    : `/api/public-share${normalizedPath}`;
}
