/**
 * Same-origin authed proxy for the whole platform.
 *
 * The browser calls `/api/proxy/<path>` (same-origin → the first-party
 * `dash_session` cookie is sent automatically). This handler forwards the call
 * to the backend `/api/v1/<path>` with `Cookie: dash_session=<token>`, so every
 * data call (validate, cost, analyses, batch, corpus, reconstruct meshes, PDFs,
 * CSVs) is authenticated by the session — no API key in the browser, and it
 * works cross-origin in production where a direct browser→backend cookie would
 * not be sent. Status + body + rate-limit headers are relayed verbatim so the
 * client's structured-error handling (e.g. 400 GEOMETRY_INVALID, 429) is
 * preserved.
 *
 * Request and response bodies are streamed. This is required for multi-GB batch
 * uploads: buffering here would bypass the backend's bounded streaming design
 * and exhaust the frontend process before the backend could reject the upload.
 */
import { type NextRequest } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { getSessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";

const RELAY_HEADERS = [
  "content-type",
  "content-disposition",
  "content-length",
  "cache-control",
  "x-ratelimit-limit",
  "x-ratelimit-remaining",
  "x-ratelimit-reset",
  "retry-after",
  // Preview-mesh provenance (honest decimation readout for the Verify stage).
  "x-mesh-original-faces",
  "x-mesh-preview-faces",
  "x-mesh-decimated",
  "x-mesh-source",
  // Immutable Design Studio STEP evidence used by the Verify handoff.
  "x-geometry-sha256",
];

async function handle(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> }
): Promise<Response> {
  const { path } = await ctx.params;
  if (
    path.length === 0 ||
    path.some(
      (segment) =>
        !segment ||
        segment === "." ||
        segment === ".." ||
        segment.includes("\0") ||
        segment.includes("/") ||
        segment.includes("\\") ||
        segment.includes("%") ||
        segment.includes("?") ||
        segment.includes("#"),
    )
  ) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }
  const token = (await getSessionToken()) ?? "";
  const target = backendUrl(`/api/v1/${path.join("/")}${req.nextUrl.search}`);

  const method = req.method;
  const hasBody = method !== "GET" && method !== "HEAD";

  const headers: Record<string, string> = {
    Cookie: `dash_session=${token}`,
  };
  const contentType = req.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;

  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    body: hasBody ? req.body : undefined,
    cache: "no-store",
    redirect: "error",
    signal: req.signal,
  };
  if (hasBody) init.duplex = "half";
  const res = await fetch(target, init);

  const relayed = new Headers();
  for (const h of RELAY_HEADERS) {
    const v = res.headers.get(h);
    if (v) relayed.set(h, v);
  }
  return new Response(res.body, { status: res.status, headers: relayed });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
