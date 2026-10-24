/**
 * The pure parts of a resumable part upload (lib/api/part-upload.ts): the
 * browser-side identity of a file, the byte range of each part, where a part
 * goes, and when to retry. No DOM, no fetch (node --test).
 */
export const RESUME_PREFIX = "scalecad.upload.v1:";
export const RESUME_TTL_MS = 23 * 60 * 60 * 1000;

/** The browser-side identity of a picked file: same name, size and modified time. */
export function resumeKey(file: { name: string; size: number; lastModified: number }): string {
  return `${RESUME_PREFIX}${file.name}\u0000${file.size}\u0000${file.lastModified}`;
}

/** Byte range of one part (1-based), as the server sliced the file. */
export function partRange(partNumber: number, partSize: number, total: number): [number, number] {
  const start = (partNumber - 1) * partSize;
  return [start, Math.min(total, start + partSize)];
}

/** Where to PUT a part: S3's presigned URL as is, the API's relay path through the proxy at ``apiBase``. */
export function partTarget(url: string, apiBase: string): string {
  if (url.startsWith("/api/v1/")) return `${apiBase}/${url.slice("/api/v1/".length)}`;
  return url;
}

/** Wait before retry ``attempt`` (1-based): 1 s, 2 s, 4 s, 8 s ... with jitter, capped at 20 s. */
export function backoffMs(attempt: number, rand: () => number = Math.random): number {
  return Math.min(20_000, 1000 * 2 ** (attempt - 1)) * (0.75 + rand() * 0.5);
}

/** Whether a failed part PUT is worth trying again. */
export function retryableStatus(status: number): boolean {
  return status === 0 || status === 408 || status === 429 || status >= 500;
}

export interface ResumeRecord {
  key: string;
  idem: string;
  sha256: string;
  uploadId: string | null;
  name: string;
  size: number;
  savedAt: number;
}

export function freshRecord(r: ResumeRecord | null, now: number = Date.now()): ResumeRecord | null {
  return r && now - r.savedAt < RESUME_TTL_MS ? r : null;
}

