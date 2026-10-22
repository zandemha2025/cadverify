/**
 * Upload limits, the API's own, in one place. Every screen states these numbers.
 *
 * - One CAD file: up to 2 GB on every plan (backend
 *   `direct_upload_service.DEFAULT_PART_MAX_BYTES`). A file this large goes
 *   straight to storage in parts (resumable) and is checked on the worker, never
 *   in a web request; see `lib/api/part-upload.ts`. A file over it is stopped in
 *   the browser with this number instead of after the upload.
 * - From `STORED_CHECK_FROM_MB` (and any `.gz` or `.zip` part, which the worker
 *   unpacks) a check takes that route; smaller files keep the one-request check.
 * - The web request's own limit, `MAX_UPLOAD_MB` (100 MB: backend `routes.py`
 *   `_max_upload_bytes` and `fly.toml`), still applies to the steps that send the
 *   file itself again: a re-check from a file in this tab, fixes, Fit in assembly,
 *   a part held over sign-in.
 *
 * How large a file the worker can then check depends on its memory; over that,
 * the check says how much the file needs (the server's message, shown as is).
 *
 * upload-limit.test.ts pins these to the backend. Pure: no React, no fetch.
 */
import { isCompressedCad } from "./cad-file.ts";

const MIB = 1024 * 1024;

export const CAD_MAX_MB = 2048;
export const CAD_MAX_BYTES = CAD_MAX_MB * MIB;

/** "up to 2 GB" */
export const CAD_LIMIT = "up to 2 GB";

/** From this size a check uploads straight to storage and runs on the worker. */
export const STORED_CHECK_FROM_MB = 20;
export const STORED_CHECK_FROM_BYTES = STORED_CHECK_FROM_MB * MIB;

/** A web request's own upload limit (MAX_UPLOAD_MB). */
export const FORM_MAX_MB = 100;
export const FORM_MAX_BYTES = FORM_MAX_MB * MIB;

/** "1.4 GB", "650 MB", "0.4 MB" (binary units, as the API counts). */
export function sizeText(bytes: number): string {
  if (bytes >= 1024 * MIB) {
    const g = bytes / (1024 * MIB);
    return `${g >= 10 ? Math.round(g) : g.toFixed(1)} GB`;
  }
  const mb = bytes / MIB;
  return `${mb >= 10 ? Math.round(mb) : mb.toFixed(1)} MB`;
}

export function overCadLimit(size: number): boolean {
  return size > CAD_MAX_BYTES;
}

/** The line for a picked file that's too large. */
export function overCadLimitText(sizeBytes: number): string {
  return `${sizeText(sizeBytes)}, over the 2 GB limit for one file`;
}

/** Whether a check of this file uploads to storage and runs on the worker. */
export function needsStoredCheck(file: { name: string; size: number }): boolean {
  return file.size >= STORED_CHECK_FROM_BYTES || isCompressedCad(file.name);
}

/** Over what a web request takes (for the steps that send the file again). */
export function overFormLimit(size: number): boolean {
  return size > FORM_MAX_BYTES;
}
