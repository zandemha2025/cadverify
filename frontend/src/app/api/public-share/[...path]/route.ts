/** Narrow same-origin proxy for unauthenticated, sanitized share payloads. */
import { type NextRequest } from "next/server";
import { backendUrl } from "@/lib/api-base";

export const dynamic = "force-dynamic";

const BASE62_ID = /^[A-Za-z0-9]{12}$/;

export async function GET(
  _request: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const valid =
    (path.length === 2 && path[0] === "s" && BASE62_ID.test(path[1])) ||
    (path.length === 3 &&
      path[0] === "s" &&
      path[1] === "cost" &&
      BASE62_ID.test(path[2]));
  if (!valid) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }

  const upstream = await fetch(backendUrl(`/${path.join("/")}`), {
    cache: "no-store",
    redirect: "error",
  });
  const headers = new Headers();
  const contentType = upstream.headers.get("content-type");
  const retryAfter = upstream.headers.get("retry-after");
  if (contentType) headers.set("content-type", contentType);
  if (retryAfter) headers.set("retry-after", retryAfter);
  headers.set("cache-control", "private, no-store");
  return new Response(upstream.body, { status: upstream.status, headers });
}
