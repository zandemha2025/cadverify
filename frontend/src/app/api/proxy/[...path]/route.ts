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
 * Bodies are buffered (arrayBuffer) and re-sent with the original Content-Type
 * so multipart boundaries survive; fine for local dev. (For very large uploads
 * in production this proxy buffers in the serverless function — see notes.)
 */
import { type NextRequest } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { getSessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";

const RELAY_HEADERS = [
  "content-type",
  "content-disposition",
  "content-length",
  "x-ratelimit-limit",
  "x-ratelimit-remaining",
  "x-ratelimit-reset",
  "retry-after",
  // Preview-mesh provenance (honest decimation readout for the Verify stage).
  "x-mesh-original-faces",
  "x-mesh-preview-faces",
  "x-mesh-decimated",
  "x-mesh-source",
];

async function handle(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> }
): Promise<Response> {
  const { path } = await ctx.params;
  const token = (await getSessionToken()) ?? "";
  const target = backendUrl(`/api/v1/${path.join("/")}${req.nextUrl.search}`);

  const method = req.method;
  const hasBody = method !== "GET" && method !== "HEAD";

  const headers: Record<string, string> = {
    Cookie: `dash_session=${token}`,
  };
  const contentType = req.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;

  const res = await fetch(target, {
    method,
    headers,
    body: hasBody ? await req.arrayBuffer() : undefined,
    cache: "no-store",
  });

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
