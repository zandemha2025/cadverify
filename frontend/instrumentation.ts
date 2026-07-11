/**
 * Server-side Sentry wiring (Next.js `instrumentation.ts` convention).
 *
 * `sentry.server.config.ts` only defines `Sentry.init(...)` — Next.js does not
 * load it automatically unless something imports it from `register()` here.
 * (The browser side is different: `instrumentation-client.ts` IS a native
 * Next.js convention that Next loads itself, no wiring needed.)
 *
 * This app has no edge runtime (no `runtime = "edge"` route/proxy config —
 * `src/proxy.ts` defaults to the Node.js runtime per Next's Proxy docs), so
 * only the nodejs branch is wired; there is no `sentry.edge.config.ts`.
 *
 * `Sentry.init` itself is DSN-gated (`enabled: !!NEXT_PUBLIC_SENTRY_DSN` in
 * sentry.server.config.ts), so this file is a no-op end-to-end whenever
 * NEXT_PUBLIC_SENTRY_DSN is unset — dev/test/local builds are unaffected.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
}

export { captureRequestError as onRequestError } from "@sentry/nextjs";
