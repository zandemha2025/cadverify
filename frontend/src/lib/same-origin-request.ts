/**
 * Login CSRF guard for the Next route handlers that set or clear the session
 * cookie. A browser request must come from this app's own origin: its Origin
 * header (when sent) names the host it was sent to, and Fetch Metadata
 * (Sec-Fetch-Site) says same-origin or a direct navigation. A cross-site page
 * can't sign a visitor into an account it controls, or sign them out, through
 * these handlers. Requests with neither header (server-to-server, scripts) are
 * not browser-driven and pass.
 */
import { NextResponse } from "next/server";

function hostOf(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    return new URL(value).host.toLowerCase();
  } catch {
    return null;
  }
}

/** Hosts this app answers on: the request's own Host (as forwarded) and DASHBOARD_ORIGIN. */
function ownHosts(req: Request): Set<string> {
  const hosts = new Set<string>();
  const forwarded = req.headers.get("x-forwarded-host")?.split(",")[0]?.trim();
  for (const h of [forwarded, req.headers.get("host"), hostOf(req.url)]) {
    if (h) hosts.add(h.toLowerCase());
  }
  const configured = hostOf(process.env.DASHBOARD_ORIGIN);
  if (configured) hosts.add(configured);
  return hosts;
}

/** True when a browser sent this request from another site (or an opaque origin). */
export function isCrossSiteRequest(req: Request): boolean {
  const origin = req.headers.get("origin");
  if (origin) {
    const host = origin === "null" ? null : hostOf(origin);
    return host == null || !ownHosts(req).has(host);
  }
  const site = req.headers.get("sec-fetch-site");
  return site != null && site !== "same-origin" && site !== "none";
}

/** A 403 for a cross-site request to a session handler, or null to carry on. */
export function crossSiteRefusal(req: Request): NextResponse | null {
  if (!isCrossSiteRequest(req)) return null;
  return NextResponse.json(
    { detail: { code: "cross_site_request", message: "This request didn't come from ScaleCAD. Open ScaleCAD and try again." } },
    { status: 403, headers: { "cache-control": "no-store" } },
  );
}
