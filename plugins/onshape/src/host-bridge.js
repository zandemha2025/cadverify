/**
 * Onshape iframe host bridge (postMessage handshake).
 *
 * Security rules from https://onshape-public.github.io/docs/app-dev/extensions/:
 *   - The extension must post a message (e.g. keepAlive) before Onshape will
 *     post anything to it.
 *   - Every message posted to Onshape must include documentId, workspaceId
 *     and elementId.
 *   - Messages received from the host are only safe when event.origin matches
 *     the `server` query parameter from the iframe src URL.
 */

export function buildKeepAliveMessage(context) {
  if (!context?.documentId || !context?.elementId) {
    throw new TypeError("context with documentId and elementId is required");
  }
  return {
    messageName: "keepAlive",
    documentId: context.documentId,
    workspaceId: context.workspaceOrVersion === "w" ? context.workspaceOrVersionId : undefined,
    elementId: context.elementId,
  };
}

/**
 * createHostBridge({ context, target }) - target is the host window
 * (window.parent inside the iframe). Returns helpers to announce readiness
 * and to validate inbound messages. No state is kept.
 */
export function createHostBridge({ context, target } = {}) {
  if (!context) throw new TypeError("context is required");
  if (!target || typeof target.postMessage !== "function") {
    throw new TypeError("target with postMessage is required (window.parent inside Onshape)");
  }
  const targetOrigin = context.server ?? context.apiOrigin;
  return {
    /** First message to the host; Onshape stays silent until it arrives. */
    announceReady() {
      target.postMessage(buildKeepAliveMessage(context), targetOrigin);
    },
    keepAlive() {
      target.postMessage(buildKeepAliveMessage(context), targetOrigin);
    },
    /** True only when the event origin matches the host `server` parameter. */
    isTrustedMessage(event) {
      if (!context.server) return false;
      return event?.origin === context.server;
    },
  };
}
