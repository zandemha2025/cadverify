/**
 * "ScaleCAD is busy": a server that has no room right now answers 429 `server_busy`
 * (or 503 busy) with Retry-After. That is about the server, never about the file, so
 * a check waits and asks again by itself instead of stopping (capacity test D1–D3).
 *
 * - `busySignal` tells a busy refusal from every other one (an allowance used up,
 *   a rate limit, a file the engine can't read): only busy is retried.
 * - `busyDelayMs` waits what the server asked, plus a little jitter so the people
 *   who were refused together don't all come back in the same second.
 * - `retryWhileBusy` asks again until the answer isn't busy, for up to about three
 *   minutes in all, and reports each wait so the page can count it down.
 *
 * Pure (no DOM, no React), for node --test.
 */

/** Whose room ran out: the whole server's, or this organization's share of it. */
export type BusyKind = "server" | "org";

/** The request of a check that was refused as busy. */
export type BusyStep = "probe" | "preview" | "validate" | "cost";

export interface BusySignal {
  kind: BusyKind;
  /** Seconds the server asked to wait (Retry-After), or null when it didn't say. */
  retryAfterS: number | null;
}

/** One wait between a busy answer and the next try. */
export interface BusyWait {
  kind: BusyKind;
  /** Tries so far, all answered busy. */
  attempt: number;
  /** When this request first went out (ms since epoch): the wait the person has had so far. */
  since: number;
  /** When the next try goes out (ms since epoch). */
  until: number;
}

/** How long a check keeps asking before it says "Still busy" and offers a button. */
export const BUSY_BOUND_MS = 180_000;
/** The wait when the server doesn't say (the server's own busy answers say 5 s). */
export const BUSY_DEFAULT_WAIT_S = 5;
export const BUSY_MIN_WAIT_S = 1;
export const BUSY_MAX_WAIT_S = 30;
/** Up to this share is added to each wait, never taken off it: never sooner than asked. */
export const BUSY_JITTER = 0.25;

function codeOf(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const b = body as { code?: unknown; detail?: unknown };
  const nested = b.detail && typeof b.detail === "object" ? (b.detail as { code?: unknown }).code : undefined;
  const code = nested ?? b.code;
  return typeof code === "string" ? code : null;
}

function textOf(body: unknown): string {
  if (typeof body === "string") return body;
  if (!body || typeof body !== "object") return "";
  const b = body as { message?: unknown; detail?: unknown };
  if (typeof b.detail === "string") return b.detail;
  const nested = b.detail && typeof b.detail === "object" ? (b.detail as { message?: unknown }).message : undefined;
  const text = nested ?? b.message;
  return typeof text === "string" ? text : "";
}

/** Retry-After as seconds from `now`: delta-seconds or an HTTP date; null when absent or unreadable. */
export function parseRetryAfter(header: string | null | undefined, now: number = Date.now()): number | null {
  if (header == null) return null;
  const t = header.trim();
  if (!t) return null;
  if (/^\d+$/.test(t)) return Number(t);
  const at = Date.parse(t);
  return Number.isFinite(at) ? Math.max(0, Math.ceil((at - now) / 1000)) : null;
}

/**
 * A refusal that means "no room right now, ask again": 429 or 503 with the server's
 * busy code (`server_busy`, `org_at_capacity`, or another `*_busy`), or, from an older
 * server without a code, its busy words. Anything else (an allowance used up, a rate
 * limit, a file the engine refused) is null and is never retried.
 */
export function busySignal(status: number, body: unknown, retryAfter?: string | null, now: number = Date.now()): BusySignal | null {
  if (status !== 429 && status !== 503) return null;
  const code = codeOf(body);
  let kind: BusyKind | null = null;
  if (code === "org_at_capacity") kind = "org";
  else if (code === "server_busy" || (code != null && /(?:^|_)busy$/.test(code))) kind = "server";
  else if (code == null) {
    const text = textOf(body);
    if (/server is at capacity/i.test(text)) kind = "server";
    else if (/concurrent-analysis limit/i.test(text)) kind = "org";
  }
  return kind ? { kind, retryAfterS: parseRetryAfter(retryAfter, now) } : null;
}

/** The wait before the next try: what the server asked (bounded), plus up to 25% jitter. */
export function busyDelayMs(signal: BusySignal, random: () => number = Math.random): number {
  const asked = signal.retryAfterS ?? BUSY_DEFAULT_WAIT_S;
  const base = Math.min(Math.max(asked, BUSY_MIN_WAIT_S), BUSY_MAX_WAIT_S);
  const r = Math.min(Math.max(random(), 0), 1);
  return Math.round(base * 1000 * (1 + BUSY_JITTER * r));
}

/** Whole seconds until `until`, for "Checking again in 8 s…" (0 once the try has gone out). */
export function secondsUntil(until: number, now: number): number {
  return Math.max(0, Math.ceil((until - now) / 1000));
}

/** What one try returned: busy (ask again), or the answer to keep. */
export type BusyAttempt<T> = { busy: BusySignal; value?: T } | { busy?: undefined; value: T };

export type BusyOutcome<T> =
  | { ok: true; value: T; attempts: number }
  /** Still busy after the bound; `value` is the last try's own answer when it had one. */
  | { ok: false; busy: BusySignal; value: T | undefined; since: number; attempts: number };

export interface RetryWhileBusyOptions {
  /** Each wait as it starts, and null once the waiting is over (answered, or given up). */
  onWait?: (wait: BusyWait | null) => void;
  /** How long to keep asking, from the first busy answer. 0: one try only. */
  boundMs?: number;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
  random?: () => number;
}

/**
 * Run `attempt` until its answer isn't busy. Each busy answer waits `busyDelayMs`
 * and tries again, as long as that next try still starts within `boundMs` of the
 * first try (a busy answer can itself take a while: the server waits for room
 * before it says busy); after that the outcome is "still busy" for the page to
 * offer a button. A try that throws ends the waiting and the error goes to the caller.
 */
export async function retryWhileBusy<T>(attempt: () => Promise<BusyAttempt<T>>, opts: RetryWhileBusyOptions = {}): Promise<BusyOutcome<T>> {
  const now = opts.now ?? Date.now;
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const bound = opts.boundMs ?? BUSY_BOUND_MS;
  const first = now();
  let since: number | null = null;
  let attempts = 0;
  try {
    for (;;) {
      const r = await attempt();
      attempts += 1;
      if (!r.busy) return { ok: true, value: r.value as T, attempts };
      const t = now();
      since = first;
      const delay = busyDelayMs(r.busy, opts.random);
      if (t + delay - since > bound) return { ok: false, busy: r.busy, value: r.value, since, attempts };
      opts.onWait?.({ kind: r.busy.kind, attempt: attempts, since, until: t + delay });
      await sleep(delay);
    }
  } finally {
    if (since != null) opts.onWait?.(null);
  }
}
