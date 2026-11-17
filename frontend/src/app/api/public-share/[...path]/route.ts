/** Narrow same-origin proxy for unauthenticated, sanitized share payloads. */
import { type NextRequest } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";
import { BASE62, publicSharePath } from "@/lib/public-share-paths";

export const dynamic = "force-dynamic";

/** The one write the public share surface accepts: a vendor's quote-back
 * (price + optional lead time) on a part's share link. Same narrow allowlist,
 * same IP signing; everything else stays read-only. */
export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const isQuote =
    path.length === 4 && path[0] === "s" && path[1] === "cost" && path[3] === "quote" && BASE62.test(path[2] ?? "");
  if (!isQuote) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }
  const backendPath = `/${path.join("/")}`;
  const body = await request.text();
  const upstream = await fetch(backendUrl(backendPath), {
    method: "POST",
    headers: { ...signedAuthProxyHeaders(request, backendPath), "content-type": "application/json" },
    body,
    cache: "no-store",
    redirect: "error",
  });
  const headers = new Headers();
  const retryAfter = upstream.headers.get("retry-after");
  if (retryAfter) headers.set("retry-after", retryAfter);
  headers.set("cache-control", "private, no-store");
  return new Response(await upstream.text(), { status: upstream.status, headers });
}

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  if (!publicSharePath(path)) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }

  // The API limits share views per visitor IP; this server is one caller, so it
  // signs the visitor's IP for this exact path (as the auth proxies do).
  const backendPath = `/${path.join("/")}`;
  const upstream = await fetch(backendUrl(backendPath), {
    headers: signedAuthProxyHeaders(request, backendPath),
    cache: "no-store",
    redirect: "error",
  });
  const headers = new Headers();
  const contentType = upstream.headers.get("content-type");
  const retryAfter = upstream.headers.get("retry-after");
  // A CAD file or the package ZIP downloads under its own name.
  const disposition = upstream.headers.get("content-disposition");
  if (contentType) headers.set("content-type", contentType);
  if (retryAfter) headers.set("retry-after", retryAfter);
  if (disposition && /^attachment; filename="[A-Za-z0-9_.-]+"$/.test(disposition)) headers.set("content-disposition", disposition);
  headers.set("x-robots-tag", "noindex");
  headers.set("cache-control", "private, no-store");
  return new Response(upstream.body, { status: upstream.status, headers });
}
