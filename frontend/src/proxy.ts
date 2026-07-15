/**
 * Proxy (Next.js 16's renamed Middleware) — server-side route protection.
 *
 * Optimistic presence check on every gated route: a request to a platform URL
 * with no session cookie is redirected to /login BEFORE the page renders (this
 * is the server-side gate the security audit requires — not a client hide).
 * Auth pages are not bounced on cookie presence alone: the proxy cannot validate
 * the HMAC/session against the backend, and stale cookies would otherwise loop
 * between /login and the gated app.
 *
 * The HMAC signature cannot be validated here (Next forbids crypto/DB in proxy),
 * so this is the cheap optimistic check; the authoritative validator is the DAL
 * (`verifySession` → backend /auth/me), which runs in the (app) layout and in
 * every authed API route handler.
 */
import { NextResponse, type NextRequest } from "next/server";

import { directUploadConnectOrigin } from "./lib/direct-upload-csp";

const SESSION_COOKIE = "dash_session";
const SERVED_BUILD_ID =
  process.env.PROOFSHAPE_BUILD_ID ||
  process.env.VERCEL_GIT_COMMIT_SHA ||
  process.env.GITHUB_SHA ||
  process.env.NEXT_PUBLIC_BUILD_SHA ||
  "unknown";

function applySecurityHeaders(response: NextResponse, csp: string): NextResponse {
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set(
    "Strict-Transport-Security",
    "max-age=63072000; includeSubDomains",
  );
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=()",
  );
  // Release evidence reads this from the actual HTTP process. This prevents a
  // clean checkout from certifying a stale Next build still serving on :3000.
  response.headers.set("X-ProofShape-Build", SERVED_BUILD_ID);
  return response;
}

function contentSecurityPolicy(nonce: string): string {
  const devEval = process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : "";
  const upgrade = process.env.NODE_ENV === "development" ? "" : " upgrade-insecure-requests;";
  const directUploadOrigin = directUploadConnectOrigin(
    process.env.DIRECT_UPLOAD_ORIGIN,
    process.env.RELEASE,
  );
  const directUploadSource = directUploadOrigin ? ` ${directUploadOrigin}` : "";
  return `
    default-src 'self';
    script-src 'self' 'nonce-${nonce}' 'strict-dynamic' 'wasm-unsafe-eval'${devEval} https://challenges.cloudflare.com;
    style-src 'self' 'unsafe-inline';
    img-src 'self' data: blob: https:;
    font-src 'self' data:;
    connect-src 'self' blob:${directUploadSource} https://challenges.cloudflare.com https://*.ingest.sentry.io https://*.ingest.us.sentry.io;
    frame-src https://challenges.cloudflare.com;
    worker-src 'self' blob:;
    media-src 'self' blob:;
    manifest-src 'self';
    object-src 'none';
    base-uri 'self';
    form-action 'self';
    frame-ancestors 'none';${upgrade}
  `
    .replace(/\s{2,}/g, " ")
    .trim();
}

const GATED = [
  "/analyze",
  "/cost",
  "/cost-decisions",
  "/batch",
  "/history",
  "/integrations",
  "/notifications",
  "/rfq-packages",
  "/analyses",
  "/label",
  "/reconstruct",
  "/keys",
  "/settings",
  "/design-system",
  "/designs",
  "/onboarding",
  "/verify",
];
export default function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const hasSession = Boolean(req.cookies.get(SESSION_COOKIE)?.value);
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const requestedPath = `${pathname}${req.nextUrl.search}`;
  requestHeaders.set("x-proofshape-request-path", requestedPath);

  const gated = GATED.some(
    (p) => pathname === p || pathname.startsWith(p + "/")
  );
  if (gated && !hasSession) {
    const url = new URL("/login", req.nextUrl);
    url.searchParams.set("next", requestedPath);
    return applySecurityHeaders(NextResponse.redirect(url), csp);
  }

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  return applySecurityHeaders(response, csp);
}

export const config = {
  // Run on everything except API routes (they self-authorize), Next internals,
  // and static assets. Public marketing pages (/, /method, /docs, /s/...) match
  // but fall through to NextResponse.next() since they are neither gated nor
  // auth pages.
  matcher: [
    {
      source: "/((?!api/|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
