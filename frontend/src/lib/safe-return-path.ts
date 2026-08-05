const DEFAULT_RETURN_PATH = "/verify";

/**
 * Accept only a same-origin application path for post-auth navigation.
 * Absolute, protocol-relative, and malformed destinations fall back locally so
 * preserving a protected route never creates an open redirect.
 */
export function safeLocalPath(
  raw: string | null | undefined,
  fallback = DEFAULT_RETURN_PATH,
): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return fallback;
  try {
    const base = new URL("https://proofshape.invalid");
    const parsed = new URL(raw, base);
    if (parsed.origin !== base.origin) return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

export function loginHrefForReturnPath(raw: string | null | undefined): string {
  const next = safeLocalPath(raw, "");
  return next ? `/login?next=${encodeURIComponent(next)}` : "/login";
}
