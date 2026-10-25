/**
 * Upload limits, the API's own, in one place. Every screen states these numbers.
 *
 * - One CAD file: up to 2 GB on every plan (backend
 *   `direct_upload_service.DEFAULT_PART_MAX_BYTES`). A file this large goes
 *   straight to storage in parts (resumable) and is checked on the worker, never
 *   in a web request; see `lib/api/part-upload.ts`. A file over it is stopped in
 *   the browser with this number instead of after the upload.
 * - From `STORED_CHECK_FROM_MB` (and any `.gz` or `.zip` part, which the worker
 *   unpacks) a check takes that route; smaller files keep the one-request check,
 *   except a STEP or IGES file whose estimated memory is over what the web
 *   process gives one check (`overWebCheckMemory`, the backend's own model): on a
 *   4 GB web machine that is from about 9 MB. The web process refuses such a file
 *   (413 CHECK_TOO_LARGE) before parsing it; it goes to the worker instead.
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

/**
 * The memory one STEP or IGES check needs, by file size: the backend's measured
 * model (`stored_check_service.STEP_MEMORY_POINTS`, MB of file -> MB added to a
 * warmed process; IGES is sized like STEP), interpolated, extended at the last
 * slope, with its 10% headroom. No STEP is sized under the 820 MB a small file
 * needs at the mesher's 250,000-face budget. upload-limit.test.ts pins the points
 * to the backend.
 */
export const STEP_MEMORY_POINTS: readonly (readonly [number, number])[] = [
  [0.0, 820.0], [1.52, 820.0], [4.92, 1531.0], [10.07, 2396.0],
];
export const MEMORY_HEADROOM = 1.1;

/**
 * What the web process gives one check: `CHECK_MEMORY_FRACTION` (0.6) of its
 * machine's memory, a 4 GB Fly web machine in production (fly.toml's web `[[vm]]`).
 * A larger web machine only means some files go to the worker that the web
 * process could have taken; the worker checks them the same way.
 */
export const WEB_CHECK_MEMORY_BUDGET_BYTES = Math.floor(0.6 * 4096 * MIB);

export function estimateStepMemoryBytes(sizeBytes: number): number {
  const x = sizeBytes / MIB;
  const pts = STEP_MEMORY_POINTS;
  let mb: number;
  if (x <= pts[0][0]) mb = pts[0][1];
  else {
    let i = pts.findIndex(([px]) => x <= px);
    if (i < 0) i = pts.length - 1;
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    mb = y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
  }
  return Math.floor(mb * MEMORY_HEADROOM * MIB);
}

/** A STEP or IGES file whose check needs more memory than the web process gives one. */
export function overWebCheckMemory(file: { name: string; size: number }): boolean {
  return /\.(step|stp|iges|igs)$/i.test(file.name) && estimateStepMemoryBytes(file.size) > WEB_CHECK_MEMORY_BUDGET_BYTES;
}

/** Whether a check of this file uploads to storage and runs on the worker. */
export function needsStoredCheck(file: { name: string; size: number }): boolean {
  return file.size >= STORED_CHECK_FROM_BYTES || isCompressedCad(file.name) || overWebCheckMemory(file);
}

/** Over what a web request takes (for the steps that send the file again). */
export function overFormLimit(size: number): boolean {
  return size > FORM_MAX_BYTES;
}
