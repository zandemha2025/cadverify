/**
 * Active-part resolution + STEP export for the "Check with ProofShape" action.
 *
 * Resolution order:
 *   1. A partId in the extension context (the user selected a part in Onshape).
 *   2. Exactly one visible part in the element -> that part.
 *   3. Zero visible parts or several -> an honest, actionable error. We never
 *      silently export the wrong part.
 */

export class ActivePartError extends Error {
  constructor(message, { parts } = {}) {
    super(message);
    this.name = "ActivePartError";
    this.parts = parts;
  }
}

export async function resolveActivePart({ context, listParts }) {
  if (context.partId) return { partId: context.partId, source: "selection" };
  const raw = await listParts(context);
  const parts = (Array.isArray(raw) ? raw : []).filter((part) => part && !part.isHidden);
  if (parts.length === 1) return { partId: parts[0].partId, name: parts[0].name, source: "only-part" };
  if (parts.length === 0) {
    throw new ActivePartError(
      "This element has no visible parts to check. Open a Part Studio with a part, then run the check again.",
      { parts: [] },
    );
  }
  const names = parts.map((part) => part.name ?? part.partId).slice(0, 10).join(", ");
  throw new ActivePartError(
    `This Part Studio has ${parts.length} parts (${names}${parts.length > 10 ? ", ..." : ""}). ` +
      "Select the part to check in Onshape, then run the check again.",
    { parts },
  );
}

/**
 * Build the exportStep function the shared check controller expects.
 * Returns { bytes, filename, translationId, partId, source }.
 */
export function createOnshapeStepExporter({ client, context }) {
  if (!client) throw new TypeError("client is required");
  if (!context) throw new TypeError("context is required");
  return async function exportActivePartStep() {
    const active = await resolveActivePart({ context, listParts: (ctx) => client.listParts(ctx) });
    const result = await client.exportStepForContext(context, {
      partId: active.partId,
      destinationName: active.name ?? "proofshape-part",
    });
    return { ...result, source: active.source };
  };
}
