/** Redact auth material from browser/server Sentry events before egress. */
const REDACTED = "***REDACTED***";
const SENSITIVE_KEYS = new Set([
  "authorization",
  "cookie",
  "set-cookie",
  "password",
  "token",
  "access_token",
  "refresh_token",
  "id_token",
  "session",
  "dash_session",
  "mint_once",
  "cv_mint_once",
  "cf_turnstile_response",
  "turnstiletoken",
  "secret",
]);

function scrubString(value: string): string {
  return value
    .replace(/cv_live_[A-Za-z0-9_]+/g, "cv_live_***REDACTED***")
    .replace(/\bBearer\s+[^\s"']+/gi, "Bearer ***REDACTED***")
    .replace(
      /([?&#](?:token|session|code|api_key)=)[^&#\s"']+/gi,
      "$1***REDACTED***",
    );
}

function scrub(value: unknown): unknown {
  if (typeof value === "string") return scrubString(value);
  if (Array.isArray(value)) return value.map(scrub);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        SENSITIVE_KEYS.has(key.toLowerCase()) ? REDACTED : scrub(item),
      ]),
    );
  }
  return value;
}

export function scrubSentryEvent<T>(event: T): T {
  return scrub(event) as T;
}
