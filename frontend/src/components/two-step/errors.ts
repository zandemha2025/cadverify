/** Reading the API's two-step refusals (pure; runs under node --test). */

/**
 * The API's error body: the app flattens it to `{ code, message }`; a bare
 * router (and some relays) wrap it as `{ detail: { code, message } }`.
 */
function problem(payload: unknown): { code: string | null; message: string | null } {
  if (!payload || typeof payload !== "object") return { code: null, message: null };
  const top = payload as { code?: unknown; message?: unknown; detail?: unknown };
  const inner = top.detail && typeof top.detail === "object" ? (top.detail as { code?: unknown; message?: unknown }) : null;
  const code = inner?.code ?? top.code;
  const message = inner?.message ?? (typeof top.detail === "string" ? top.detail : top.message);
  return { code: typeof code === "string" ? code : null, message: typeof message === "string" && message.trim() ? message : null };
}

/** The server's own words for a two-step refusal (they carry the real wait). */
export function twoStepError(status: number, payload: unknown, fallback: string): string {
  const { message } = problem(payload);
  if (message && status < 500) return message;
  if (status >= 500) return message && /try again|unavailable/i.test(message) ? message : "The sign-in service couldn't finish this. Try again.";
  return fallback;
}

export function errorCode(payload: unknown): string | null {
  return problem(payload).code;
}
