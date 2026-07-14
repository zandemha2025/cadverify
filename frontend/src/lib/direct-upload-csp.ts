const DEV_RELEASES = new Set(["", "dev", "development", "local", "test", "ci"]);

/**
 * Return one exact CSP origin for browser-to-object-store uploads.
 *
 * Presigned URLs are credentials, so this deliberately rejects paths,
 * wildcards, userinfo, and non-HTTPS production origins. Local HTTP is allowed
 * only for loopback-backed human-simulation runs (Moto/MinIO).
 */
export function directUploadConnectOrigin(
  raw: string | undefined,
  release: string | undefined = process.env.RELEASE,
): string | null {
  const value = (raw || "").trim();
  if (!value) return null;

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("DIRECT_UPLOAD_ORIGIN must be an absolute URL origin");
  }

  if (
    parsed.hostname.includes("*") ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    parsed.origin !== value
  ) {
    throw new Error("DIRECT_UPLOAD_ORIGIN must be one canonical URL origin");
  }

  const isReleased = !DEV_RELEASES.has((release || "dev").trim().toLowerCase());
  const loopback = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" || parsed.hostname === "[::1]";
  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && !isReleased && loopback)) {
    throw new Error("DIRECT_UPLOAD_ORIGIN must use HTTPS outside local development");
  }

  return parsed.origin;
}
