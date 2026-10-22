/**
 * The largest single CAD file the API takes: MAX_UPLOAD_MB, 100 MB by default
 * (backend/src/api/routes.py `_max_upload_bytes`) and in the Fly config
 * (backend/fly.toml). Every screen states this one number, and a larger file is
 * stopped in the browser with it instead of after the upload. upload-limit.test.ts
 * pins it to both backend places.
 *
 * Pure: no React, no fetch (runs under node --test).
 */
export const CAD_MAX_MB = 100;
export const CAD_MAX_BYTES = CAD_MAX_MB * 1024 * 1024;

/** "up to 100 MB" */
export const CAD_LIMIT = `up to ${CAD_MAX_MB} MB`;

export function overCadLimit(size: number): boolean {
  return size > CAD_MAX_BYTES;
}

/** The line for a picked file that's too large. */
export function overCadLimitText(sizeBytes: number): string {
  const mb = sizeBytes / 1048576;
  return `${mb >= 10 ? Math.round(mb) : mb.toFixed(1)} MB, over the ${CAD_MAX_MB} MB limit for one file`;
}
