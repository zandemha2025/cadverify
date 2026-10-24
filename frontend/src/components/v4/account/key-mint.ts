/**
 * The logic behind the API page's create and rotate (see ./actions.ts), kept
 * free of Next so it unit-tests with a stand-in fetch.
 *
 * The backend returns a new key's secret once, in the response body; this
 * hands it back in the result. If a key was made but no secret came back, the
 * key is revoked at once and the result says so, so a key nobody received
 * never stays live.
 */
export type KeyScope = "read" | "read_write";
export type KeyExpiry = 30 | 90 | 365 | null;

export type MintOp = { kind: "create"; name: string; scope: KeyScope; expiresInDays: KeyExpiry } | { kind: "rotate"; id: number };

export type MintedKey = {
  id: number;
  prefix: string;
  name: string;
  scope: KeyScope;
  effectiveScope: KeyScope;
  expiresAt: string | null;
  secret: string;
};

/** `made` is set when the backend did make (or rotate to) a key: it says whether that key was revoked again. */
export type MintResult =
  | { ok: true; key: MintedKey }
  | { ok: false; status: number; error: string; made: { id: number; prefix: string; revoked: boolean } | null };

const SECRET = /^cv_live_[A-Za-z0-9]+_[A-Za-z0-9]+$/;

function problem(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const d = (body as { detail?: unknown }).detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") return (d as { message: string }).message;
  const m = (body as { message?: unknown }).message;
  return typeof m === "string" ? m : null;
}

/** The secret from the backend's legacy Set-Cookie header, for an older backend. */
function fromCookie(headers: Headers): string | null {
  const all = typeof headers.getSetCookie === "function" ? headers.getSetCookie() : [headers.get("set-cookie") ?? ""];
  for (const line of all) {
    const m = /^\s*cv_mint_once=("?)([A-Za-z0-9_\-]+)\1\s*(;|$)/.exec(line);
    if (m) return m[2];
  }
  return null;
}

function scopeOf(v: unknown, fallback: KeyScope): KeyScope {
  return v === "read" || v === "read_write" ? v : fallback;
}

export type Backend = { url: (path: string) => string; fetch: typeof fetch };

export async function mintWith(backend: Backend, session: string | null | undefined, op: MintOp): Promise<MintResult> {
  if (!session) return { ok: false, status: 401, error: "Sign in again to manage keys.", made: null };
  const auth = { Cookie: `dash_session=${session}` };

  let path: string;
  let body: string | undefined;
  if (op.kind === "create") {
    const name = (typeof op.name === "string" ? op.name : "").trim().slice(0, 80) || "Default";
    const scope = scopeOf(op.scope, "read");
    const expires = op.expiresInDays === 30 || op.expiresInDays === 90 || op.expiresInDays === 365 ? op.expiresInDays : null;
    path = "/api/v1/keys";
    body = JSON.stringify({ name, scope, expires_in_days: expires });
  } else {
    if (!Number.isSafeInteger(op.id) || op.id <= 0) return { ok: false, status: 400, error: "That key isn’t available. Reload and try again.", made: null };
    path = `/api/v1/keys/${op.id}/rotate`;
  }

  let res: Response;
  try {
    res = await backend.fetch(backend.url(path), {
      method: "POST",
      headers: { ...auth, ...(body ? { "content-type": "application/json" } : {}) },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    // No answer: the page checks its key list for a key this request made.
    return { ok: false, status: 503, error: "Couldn’t reach ScaleCAD.", made: null };
  }
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      error: problem(data) ?? (op.kind === "create" ? `No key was made (${res.status}).` : `The key wasn’t rotated (${res.status}).`),
      made: null,
    };
  }
  const id = Number(data?.id);
  const prefix = typeof data?.prefix === "string" ? data.prefix : "";
  const raw = typeof data?.secret === "string" ? data.secret : fromCookie(res.headers);
  const secret = raw && SECRET.test(raw) ? raw : null;
  if (!secret) {
    if (!Number.isSafeInteger(id) || id <= 0) {
      return { ok: false, status: 502, error: "ScaleCAD’s answer was incomplete. Reload to see whether a key was made, and revoke any key you didn’t receive.", made: null };
    }
    let revoked = false;
    try {
      const del = await backend.fetch(backend.url(`/api/v1/keys/${id}`), { method: "DELETE", headers: auth, cache: "no-store", signal: AbortSignal.timeout(15_000) });
      revoked = del.status === 204 || del.status === 404;
    } catch {
      revoked = false;
    }
    const shown = `cv_live_${prefix}_…`;
    return {
      ok: false,
      status: 502,
      error: revoked
        ? `The key’s secret didn’t reach this page, so ScaleCAD revoked the key (${shown}). Nothing can use it. Create another.`
        : `The key’s secret didn’t reach this page, and revoking it failed. Revoke ${shown} below.`,
      made: { id, prefix, revoked },
    };
  }
  const scope = scopeOf(data?.scope, "read");
  return {
    ok: true,
    key: {
      id,
      prefix,
      name: typeof data?.name === "string" ? data.name : "",
      scope,
      effectiveScope: scopeOf(data?.effective_scope, scope),
      expiresAt: typeof data?.expires_at === "string" ? data.expires_at : null,
      secret,
    },
  };
}
