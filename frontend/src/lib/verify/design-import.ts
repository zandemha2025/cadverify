const DESIGN_ID = /^[0-9A-Za-z]{26}$/;
export const MAX_GENERATED_STEP_BYTES = 100 * 1024 * 1024;

export function designIdFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get("design");
  return value && DESIGN_ID.test(value) ? value : null;
}

export function designRevisionFromSearch(search: string): number | null {
  const raw = new URLSearchParams(search).get("revision");
  if (raw == null) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 1 && value <= 1_000_000
    ? value
    : null;
}

export function designFilename(contentDisposition: string | null): string {
  const raw = contentDisposition?.match(/filename="?([^";]+)"?/i)?.[1] ?? "";
  const leaf = raw.split(/[\\/]/).pop() ?? "";
  const safe = leaf.replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^\.+/, "");
  return safe.toLowerCase().endsWith(".step") && safe.length <= 120
    ? safe
    : "proofshape-design.step";
}

export async function importDesignStep(
  designId: string,
  fetcher: typeof fetch = fetch,
  revisionNo: number | null = null,
): Promise<File> {
  if (!DESIGN_ID.test(designId)) throw new Error("That Design Studio link is invalid.");
  if (
    revisionNo !== null &&
    (!Number.isSafeInteger(revisionNo) || revisionNo < 1 || revisionNo > 1_000_000)
  ) {
    throw new Error("That design revision is invalid.");
  }
  const artifactPath = revisionNo === null
    ? `/api/proxy/designs/${encodeURIComponent(designId)}/download.step`
    : `/api/proxy/designs/${encodeURIComponent(designId)}/revisions/${revisionNo}/download.step`;
  const response = await fetcher(
    artifactPath,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`The design artifact is not ready (${response.status}).`);
  }
  const declaredSize = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredSize) && declaredSize > MAX_GENERATED_STEP_BYTES) {
    throw new Error("The generated STEP artifact exceeds the 100 MB verification limit.");
  }
  const blob = await response.blob();
  if (blob.size === 0) throw new Error("The generated STEP artifact was empty.");
  if (blob.size > MAX_GENERATED_STEP_BYTES) {
    throw new Error("The generated STEP artifact exceeds the 100 MB verification limit.");
  }
  const expectedHash = response.headers.get("x-geometry-sha256")?.toLowerCase() ?? "";
  if (!/^[a-f0-9]{64}$/.test(expectedHash)) {
    throw new Error("The generated STEP artifact is missing its integrity proof.");
  }
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  const actualHash = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  if (actualHash !== expectedHash) {
    throw new Error("The generated STEP artifact failed its integrity check.");
  }
  return new File(
    [blob],
    designFilename(response.headers.get("content-disposition")),
    { type: "model/step" },
  );
}
