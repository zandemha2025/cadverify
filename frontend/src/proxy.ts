/**
 * Proxy (Next.js 16's renamed Middleware) — server-side route protection.
 *
 * Optimistic presence check on every gated route: a request to a platform URL
 * with no session cookie is redirected to /login BEFORE the page renders (this
 * is the server-side gate the security audit requires — not a client hide).
 * Authed users hitting /login or /signup are bounced to the platform.
 *
 * The HMAC signature cannot be validated here (Next forbids crypto/DB in proxy),
 * so this is the cheap optimistic check; the authoritative validator is the DAL
 * (`verifySession` → backend /auth/me), which runs in the (app) layout and in
 * every authed API route handler.
 */
import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "dash_session";

const GATED = [
  "/analyze",
  "/cost",
  "/batch",
  "/history",
  "/analyses",
  "/label",
  "/reconstruct",
  "/keys",
  "/settings",
  "/design-system",
];
const AUTH_PAGES = ["/login", "/signup"];

export default function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const hasSession = Boolean(req.cookies.get(SESSION_COOKIE)?.value);

  const gated = GATED.some(
    (p) => pathname === p || pathname.startsWith(p + "/")
  );
  if (gated && !hasSession) {
    const url = new URL("/login", req.nextUrl);
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  if (AUTH_PAGES.includes(pathname) && hasSession) {
    return NextResponse.redirect(new URL("/analyze", req.nextUrl));
  }

  return NextResponse.next();
}

export const config = {
  // Run on everything except API routes (they self-authorize), Next internals,
  // and static assets. Public marketing pages (/, /method, /docs, /s/...) match
  // but fall through to NextResponse.next() since they are neither gated nor
  // auth pages.
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico).*)"],
};
