export const PUBLIC_DEMO_MAX_STL_TRIANGLES = 500_000;

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
