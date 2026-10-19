/**
 * Onshape extension context.
 *
 * When Onshape embeds an application extension iframe it passes the document
 * context as query parameters on the iframe src URL. The parameters are
 * documented at https://onshape-public.github.io/docs/app-dev/extensions/
 * ("Action URL parameters" and "Security considerations"):
 *
 *   documentId            - current document id (required)
 *   workspaceOrVersion    - "w" for a workspace, "v" for a version (required)
 *   workspaceOrVersionId  - id of that workspace or version (required)
 *   elementId             - current element (tab) id (required)
 *   partId                - selected part id (only with a part selection)
 *   server                - Onshape origin, e.g. https://cad.onshape.com
 *   microversionId        - current microversion id (optional)
 *   configuration         - active element configuration (optional)
 *
 * Extensions must treat the `server` parameter as the only trusted message
 * origin for postMessage traffic with the host.
 */

export class ContextError extends Error {
  constructor(message, { missing = [] } = {}) {
    super(message);
    this.name = "ContextError";
    this.missing = missing;
  }
}

export const DEFAULT_API_ORIGIN = "https://cad.onshape.com";

export function parseExtensionContext(search, { apiOrigin } = {}) {
  const params = new URLSearchParams(typeof search === "string" ? search : "");
  const get = (name) => {
    const value = params.get(name);
    return value && value.trim() !== "" ? value.trim() : null;
  };

  const missing = [];
  const documentId = get("documentId");
  const workspaceOrVersion = get("workspaceOrVersion");
  const workspaceOrVersionId = get("workspaceOrVersionId");
  const elementId = get("elementId");
  if (!documentId) missing.push("documentId");
  if (!workspaceOrVersionId) missing.push("workspaceOrVersionId");
  if (!elementId) missing.push("elementId");
  if (workspaceOrVersion !== "w" && workspaceOrVersion !== "v") {
    missing.push("workspaceOrVersion (must be 'w' or 'v')");
  }
  if (missing.length > 0) {
    throw new ContextError(
      `Onshape extension context is incomplete; missing or invalid: ${missing.join(", ")}. ` +
        "Open the panel from inside Onshape so the host passes the document context.",
      { missing },
    );
  }

  const server = get("server");
  const origin = apiOrigin ?? server ?? DEFAULT_API_ORIGIN;

  const context = {
    documentId,
    workspaceOrVersion,
    workspaceOrVersionId,
    elementId,
    partId: get("partId"),
    server,
    microversionId: get("microversionId"),
    configuration: get("configuration"),
    apiOrigin: origin,
    /** "w" | "v" path segment pair for element-scoped API routes. */
    wvmType: workspaceOrVersion,
    wvmId: workspaceOrVersionId,
    /**
     * Element-scoped API prefix shared by the parts, partstudio and
     * translation endpoints used by the M2 adapter.
     */
    elementApiPath() {
      return `/api/partstudios/d/${encodeURIComponent(this.documentId)}/${this.wvmType}/${encodeURIComponent(this.wvmId)}/e/${encodeURIComponent(this.elementId)}`;
    },
    partsApiPath() {
      return `/api/parts/d/${encodeURIComponent(this.documentId)}/${this.wvmType}/${encodeURIComponent(this.wvmId)}/e/${encodeURIComponent(this.elementId)}`;
    },
  };
  return Object.freeze(context);
}

/**
 * Read the context from a window-like object. Returns null when the panel is
 * not running inside an Onshape host (the M1 skeleton path stays available).
 */
export function contextFromLocation(locationLike, options) {
  const search = locationLike?.search ?? "";
  if (!search || search === "?") return null;
  try {
    return parseExtensionContext(search, options);
  } catch (error) {
    if (error instanceof ContextError) return null;
    throw error;
  }
}
