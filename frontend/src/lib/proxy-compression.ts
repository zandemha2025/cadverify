/**
 * The same-origin proxy's response compression (buyer-15). The API gzips its
 * responses (GZipMiddleware, 1 KB and up), but the proxy's fetch decodes them and
 * relayed the bodies uncompressed: opening one part on a phone downloaded a 601 KB
 * record and a 238 KB analysis that travel as about a tenth of that. The proxy now
 * gzips again what the API sent compressed, when the browser accepts gzip.
 * Pure, for node --test.
 */

/** Types worth compressing: JSON, text, SVG/XML and GLB meshes. Never an event stream (it would be held back). */
const COMPRESSIBLE = /^(application\/(json|problem\+json|javascript|xml)|text\/(?!event-stream)|image\/svg\+xml|model\/gltf-binary)\b/i;

/** Does the browser accept gzip ("gzip", "gzip;q=0.8", "*"), and not refuse it ("gzip;q=0")? */
export function acceptsGzip(acceptEncoding: string | null | undefined): boolean {
  if (!acceptEncoding) return false;
  let star = false;
  for (const part of acceptEncoding.split(",")) {
    const [name, ...params] = part.trim().toLowerCase().split(";");
    const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
    const weight = q ? Number(q.slice(2)) : 1;
    if (name === "gzip") return weight > 0;
    if (name === "*") star = weight > 0;
  }
  return star;
}

/** The response varies by Accept-Encoding whenever its type is one the proxy may compress. */
export function variesByEncoding(contentType: string | null | undefined): boolean {
  return !!contentType && COMPRESSIBLE.test(contentType);
}

/**
 * Gzip the relayed body: the API compressed it (so it is big enough to be worth it), its type compresses,
 * and the browser accepts gzip. A body the API sent plain (small, or a type it doesn't compress) stays plain.
 */
export function shouldRecompress(acceptEncoding: string | null | undefined, upstream: Headers): boolean {
  const enc = (upstream.get("content-encoding") ?? "").toLowerCase();
  if (!enc || enc === "identity") return false;
  return variesByEncoding(upstream.get("content-type")) && acceptsGzip(acceptEncoding);
}
