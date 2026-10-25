const DEFAULT_RETURN_PATH = "/verify";
const BASE = "https://proofshape.invalid";

/** A path the browser opens on this site: one leading slash, no host, no backslash. */
function plainLocal(path: string): boolean {
  return path.startsWith("/") && !path.startsWith("//") && !path.startsWith("/\\");
}

/**
 * Accept only a same-origin application path for post-auth navigation.
 * Absolute, protocol-relative, and malformed destinations fall back locally so
 * preserving a protected route never creates an open redirect.
 *
 * The check runs on the raw value AND on what the URL parser makes of it:
 * dot segments, `%2e` and stripped tabs or newlines can turn `/.//evil.example`
 * into `//evil.example`, which `location.href` and `router.push` open as
 * another site. Every post-sign-in `next` goes through this one helper.
 */
export function safeLocalPath(raw: unknown, fallback = DEFAULT_RETURN_PATH): string {
  if (typeof raw !== "string" || !plainLocal(raw) || raw.includes("\\") || /[\u0000-\u001f\u007f]/.test(raw)) {
    return fallback;
  }
  try {
    const base = new URL(BASE);
    const parsed = new URL(raw, base);
    if (parsed.origin !== base.origin) return fallback;
    const out = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    // The normalised path must still be a plain local one, and stay here when opened.
    if (!plainLocal(out) || out.includes("\\") || new URL(out, base).origin !== base.origin) return fallback;
    return out;
  } catch {
    return fallback;
  }
}

export function loginHrefForReturnPath(raw: string | null | undefined): string {
  const next = safeLocalPath(raw, "");
  return next ? `/login?next=${encodeURIComponent(next)}` : "/login";
}
