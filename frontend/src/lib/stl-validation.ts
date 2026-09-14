export const PUBLIC_DEMO_MAX_STL_TRIANGLES = 500_000;
export const CLIENT_STL_CORRUPT_MESSAGE =
  "this STL looks truncated or corrupt - re-export it";

/**
 * Validate enough of an STL locally to keep malformed bytes away from three's
 * STLLoader. Binary STL has an exact, declared length (84 + 50 bytes/triangle),
 * so a short body is a definite truncation rather than a server-side parse
 * concern. ASCII STL has no count field; accept only a recognisable text header
 * here and let the CAD parser provide the deeper validity verdict.
 */
export async function clientStlIntegrityError(file: File): Promise<string | null> {
  const prefixBytes = new Uint8Array(
    await file.slice(0, Math.min(file.size, 512)).arrayBuffer(),
  );
  const prefix = new TextDecoder("utf-8", { fatal: false }).decode(prefixBytes);
  const looksAscii = /^\s*solid(?:\s|$)/i.test(prefix) && /\bfacet\s+normal\b/i.test(prefix);
  if (looksAscii) return null;

  if (file.size < 84) return CLIENT_STL_CORRUPT_MESSAGE;
  const countBuffer = await file.slice(80, 84).arrayBuffer();
  if (countBuffer.byteLength !== 4) return CLIENT_STL_CORRUPT_MESSAGE;

  const triangleCount = new DataView(countBuffer).getUint32(0, true);
  // Avoid arithmetic ambiguity: a binary STL body must be exactly 50 bytes per
  // declared triangle. Extra or missing bytes both mean this is not that STL.
  const expectedSize = 84 + triangleCount * 50;
  return file.size === expectedSize ? null : CLIENT_STL_CORRUPT_MESSAGE;
}

export async function exactBinaryStlTriangleCount(
  file: File
): Promise<number | null> {
  if (file.size < 84) return null;

  const countBuffer = await file.slice(80, 84).arrayBuffer();
  if (countBuffer.byteLength !== 4) return null;

  const triangleCount = new DataView(countBuffer).getUint32(0, true);
  const expectedSize = 84 + triangleCount * 50;

  return file.size === expectedSize ? triangleCount : null;
}

export function publicDemoStlLimitMessage(
  filename: string,
  triangleCount: number
): string {
  return (
    `Public demo STL files are limited to ` +
    `${PUBLIC_DEMO_MAX_STL_TRIANGLES.toLocaleString()} triangles. ` +
    `${filename} has ${triangleCount.toLocaleString()} triangles. ` +
    `Reduce mesh resolution or create an API key for larger analyses.`
  );
}
