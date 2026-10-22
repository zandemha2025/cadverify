/** Narrow same-origin proxy for unauthenticated, sanitized share payloads. */
import { type NextRequest } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";
import { publicSharePath } from "@/lib/public-share-paths";

export const dynamic = "force-dynamic";

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
