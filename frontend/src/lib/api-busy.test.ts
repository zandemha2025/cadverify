import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { mock, test } from "node:test";

// The red toast's calls, counted (sonner is replaced as api-retry.test.ts does).
const toasts: string[] = [];
(globalThis as { __busyTestToasts?: string[] }).__busyTestToasts = toasts;
const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "sonner") return next("data:text/javascript,export const toast={error(m){globalThis.__busyTestToasts.push(m)}}", context);
  if (specifier === "@sentry/nextjs") return next("data:text/javascript,export function captureException(){};export function captureMessage(){}", context);
  if (specifier === "@/lib/api-recovery") return next(new URL("./api-recovery.ts", import.meta.url).href, context);
  if (["./api-base", "./reconstruction-id", "./analytics"].includes(specifier)) return next(new URL(`${specifier}.ts`, import.meta.url).href, context);
  return next(specifier, context);
} });
const api = await import("./api.ts");
hooks.deregister();

const busy429 = () => Response.json({ detail: { code: "server_busy", message: "server is at capacity, retry shortly" } }, { status: 429, headers: { "retry-after": "5" } });
const busy503 = () => Response.json({ code: "server_busy", message: "server is at capacity, retry shortly" }, { status: 503, headers: { "retry-after": "7" } });

test("a check that waits by itself gets busy back as busy: status, code, Retry-After, and no red toast", async () => {
  const file = new File(["solid x"], "part.stl");
  for (const [reply, status, after] of [[busy429, 429, "5"], [busy503, 503, "7"]] as const) {
    toasts.length = 0;
    let calls = 0;
    const fetchMock = mock.method(globalThis, "fetch", async () => {
      calls += 1;
      return reply();
    });
    try {
      const err = await api.validateFile(file, undefined, undefined, undefined, undefined, "check-1", { quietBusy: true }).then(
        () => null,
        (e: unknown) => e as Error & { status?: number; code?: string | null; retryAfter?: string | null },
      );
      assert.ok(err, "busy is still a refusal");
      assert.equal(err.status, status);
      assert.equal(err.code, "server_busy");
      assert.equal(err.retryAfter, after);
      assert.deepEqual(toasts, [], "no red toast for a server that's only busy");
      assert.equal(calls, 1, "the client itself doesn't resend the upload; the check's own wait does");
    } finally {
      fetchMock.mock.restore();
    }
  }
});

test("without the opt-in, and for refusals that aren't busy, nothing changes", async () => {
  const file = new File(["solid x"], "part.stl");
  const run = async (reply: () => Response, opts?: { quietBusy?: boolean }) => {
    toasts.length = 0;
    const fetchMock = mock.method(globalThis, "fetch", async () => reply());
    try {
      return await api.validateFile(file, undefined, undefined, undefined, undefined, "check-1", opts).then(() => null, (e: unknown) => e as Error & { status?: number });
    } finally {
      fetchMock.mock.restore();
    }
  };
  const plain = await run(busy429);
  assert.match(plain!.message, /Too many verification requests were sent\. Try again in 5 seconds/);
  assert.equal(plain!.status, undefined);
  assert.equal(toasts.length, 1);
  // An allowance used up is not busy: it keeps its words and its toast even when the caller waits out busy.
  const quota = await run(() => Response.json({ detail: { code: "user_validation_cap_exceeded", message: "You've used your 3 free checks." } }, { status: 429 }), { quietBusy: true });
  assert.match(quota!.message, /^Verification allowance used up/);
  assert.equal(toasts.length, 1);
  const rate = await run(() => Response.json({ detail: "Rate limit exceeded" }, { status: 429, headers: { "retry-after": "60" } }), { quietBusy: true });
  assert.match(rate!.message, /Too many verification requests/);
  assert.equal(toasts.length, 1);
});
