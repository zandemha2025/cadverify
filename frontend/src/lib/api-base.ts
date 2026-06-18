const DEFAULT_BACKEND_ORIGIN = "http://localhost:8000";
const LIVE_BACKEND_ORIGIN = "https://cadvrfy-api.fly.dev";

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

export function publicBackendOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE;
  if (configured) {
    return cleanOrigin(configured);
  }
  return process.env.NODE_ENV === "development"
    ? DEFAULT_BACKEND_ORIGIN
    : LIVE_BACKEND_ORIGIN;
}

export const API_BASE = `${publicBackendOrigin()}/api/v1`;

export function backendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${backendOrigin()}${normalizedPath}`;
}

export function browserOrBackendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return typeof window === "undefined"
    ? backendUrl(normalizedPath)
    : `${publicBackendOrigin()}${normalizedPath}`;
}
