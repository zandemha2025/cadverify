/**
 * A big CAD file, uploaded straight to storage in parts, resumable.
 *
 * POST /uploads/multipart (purpose "part", the file's SHA-256, an Idempotency-Key)
 * returns the upload's part plan and a URL per part: presigned S3 URLs in
 * production ("s3"), or the API's own part path on a local-storage server
 * ("relay", PUT through the same-origin proxy). Up to three parts go at once,
 * each retried with backoff; a dropped connection only re-sends that part.
 *
 * Resume: the upload is remembered in this browser (localStorage, keyed by the
 * file's name, size and modified time) with its Idempotency-Key. Picking the
 * same file again, after a reload or on a flaky connection, re-initiates with
 * the same key (the server returns the same upload), asks which parts arrived
 * (GET /uploads/{id}/parts) and sends only the rest. The server checks the
 * SHA-256 of the whole file on the worker before anything is checked.
 */
import { createSHA256 } from "hash-wasm";
import { API_BASE } from "@/lib/api-base";
import { RESUME_PREFIX, backoffMs, freshRecord, partRange, partTarget as target, resumeKey, retryableStatus, type ResumeRecord } from "./part-upload-plan";

export { resumeKey, type ResumeRecord } from "./part-upload-plan";

export const HASH_CHUNK_BYTES = 8 * 1024 * 1024;
const PARALLEL = 3;
const TRIES = 5;
const partTarget = (url: string) => target(url, API_BASE);

export type UploadPhase = "hashing" | "uploading" | "finishing";

export interface UploadProgress {
  phase: UploadPhase;
  /** Bytes hashed or uploaded so far (of ``total``). */
  done: number;
  total: number;
  /** Parts already in storage from an earlier attempt. */
  resumed?: number;
}

export interface UploadedPart {
  uploadId: string;
  sha256: string;
  resumeKey: string;
}

export class PartUploadError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryable: boolean;
  constructor(message: string, status: number, code: string | null, retryable: boolean) {
    super(message);
    this.name = "PartUploadError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

/* ---------------------------------------------------------------- */
/*  Resume records                                                   */
/* ---------------------------------------------------------------- */

export function readResume(key: string): ResumeRecord | null {
  try {
    const raw = window.localStorage.getItem(key);
    return freshRecord(raw ? (JSON.parse(raw) as ResumeRecord) : null);
  } catch {
    return null;
  }
}

function writeResume(r: ResumeRecord): void {
  try {
    window.localStorage.setItem(r.key, JSON.stringify(r));
  } catch {
    /* private mode: the upload still works, it just won't resume after a reload */
  }
}

export function forgetResume(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* nothing kept */
  }
}

/** Uploads this browser started and hasn't finished (for "pick it again to finish"). */
export function pendingUploads(): ResumeRecord[] {
  const out: ResumeRecord[] = [];
  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (!k || !k.startsWith(RESUME_PREFIX)) continue;
      const r = readResume(k);
      if (r?.uploadId) out.push(r);
      else if (!r) window.localStorage.removeItem(k);
    }
  } catch {
    /* none */
  }
  return out;
}

/* ---------------------------------------------------------------- */
/*  Requests                                                         */
/* ---------------------------------------------------------------- */

async function problem(res: Response, fallback: string): Promise<PartUploadError> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  const d = body?.detail;
  if (d && typeof d === "object") {
    const o = d as { message?: unknown; code?: unknown };
    return new PartUploadError(typeof o.message === "string" ? o.message : fallback, res.status, typeof o.code === "string" ? o.code : null, retryableStatus(res.status));
  }
  return new PartUploadError(typeof d === "string" ? d : fallback, res.status, null, retryableStatus(res.status));
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    }, { once: true });
  });
}

/** SHA-256 of the whole file, read in 8 MiB slices (never the whole file in memory). */
export async function hashFile(file: Blob, onBytes?: (n: number) => void, signal?: AbortSignal): Promise<string> {
  const h = await createSHA256();
  h.init();
  let done = 0;
  for (let start = 0; start < file.size; start += HASH_CHUNK_BYTES) {
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    const buf = new Uint8Array(await file.slice(start, Math.min(file.size, start + HASH_CHUNK_BYTES)).arrayBuffer());
    h.update(buf);
    done += buf.byteLength;
    onBytes?.(done);
  }
  return h.digest("hex");
}

interface Initiated {
  upload_id: string;
  status: string;
  transport: "s3" | "relay" | null;
  part_size_bytes: number;
  part_count: number;
  parts: { part_number: number; url: string }[];
  complete_url: string;
}

function putPart(url: string, body: Blob, onBytes: (n: number) => void, signal?: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", partTarget(url));
    xhr.upload.onprogress = (e) => onBytes(e.loaded);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        let etag = xhr.getResponseHeader("ETag");
        if (!etag) {
          try {
            etag = (JSON.parse(xhr.responseText) as { etag?: string }).etag ?? null;
          } catch {
            etag = null;
          }
        }
        if (etag) resolve(etag);
        else reject(new PartUploadError("Storage didn't confirm a part of the upload.", xhr.status, "NO_ETAG", false));
        return;
      }
      let message = `A part of the upload was refused (${xhr.status}).`;
      let code: string | null = null;
      try {
        const d = (JSON.parse(xhr.responseText) as { detail?: { message?: string; code?: string } }).detail;
        if (d?.message) message = d.message;
        if (d?.code) code = d.code;
      } catch {
        /* S3 answers XML */
      }
      reject(new PartUploadError(message, xhr.status, code, retryableStatus(xhr.status) || xhr.status === 403));
    };
    xhr.onerror = () => reject(new PartUploadError("The connection dropped during the upload.", 0, "network", true));
    xhr.ontimeout = () => reject(new PartUploadError("A part of the upload timed out.", 0, "timeout", true));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
    xhr.send(body);
  });
}

async function freshUrl(uploadId: string, partNumber: number): Promise<string> {
  const res = await fetch(`${API_BASE}/uploads/${encodeURIComponent(uploadId)}/parts`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ part_numbers: [partNumber] }),
  });
  if (!res.ok) throw await problem(res, "The upload's part links couldn't be renewed.");
  const body = (await res.json()) as { parts: { part_number: number; url: string }[] };
  return body.parts[0].url;
}

/**
 * Upload ``file`` as one part for a check. Resolves when storage holds the whole
 * file (status "completed"); the caller then starts the check with ``uploadId``.
 */
export async function uploadPart(
  file: File,
  onProgress?: (p: UploadProgress) => void,
  signal?: AbortSignal,
  purpose: "part" | "batch_zip" = "part",
): Promise<UploadedPart> {
  const key = resumeKey(file) + (purpose === "part" ? "" : `\u0000${purpose}`);
  let record = readResume(key);
  if (!record) {
    const sha256 = await hashFile(file, (n) => onProgress?.({ phase: "hashing", done: n, total: file.size }), signal);
    record = {
      key,
      idem: `part-${crypto.randomUUID()}`,
      sha256,
      uploadId: null,
      name: file.name,
      size: file.size,
      savedAt: Date.now(),
    };
    writeResume(record);
  }
  onProgress?.({ phase: "uploading", done: 0, total: file.size });

  const init = await fetch(`${API_BASE}/uploads/multipart`, {
    method: "POST",
    headers: { "content-type": "application/json", "Idempotency-Key": record.idem },
    body: JSON.stringify({
      purpose,
      filename: file.name,
      content_type: purpose === "batch_zip" ? "application/zip" : file.type || "",
      size_bytes: file.size,
      checksum_sha256: record.sha256,
    }),
    signal,
  });
  if (!init.ok) {
    const err = await problem(init, "The upload didn't start.");
    // A reused key the server no longer recognises (expired, or other parameters): start clean next time.
    if (init.status === 409 || init.status === 410) forgetResume(key);
    throw err;
  }
  const up = (await init.json()) as Initiated;
  record = { ...record, uploadId: up.upload_id, savedAt: Date.now() };
  writeResume(record);
  if (up.status === "completed") return { uploadId: up.upload_id, sha256: record.sha256, resumeKey: key };

  const etags = new Map<number, string>();
  try {
    const got = await fetch(`${API_BASE}/uploads/${encodeURIComponent(up.upload_id)}/parts`, { cache: "no-store", signal });
    if (got.ok) {
      const body = (await got.json()) as { parts: { part_number: number; etag: string; size_bytes: number }[] };
      for (const p of body.parts) {
        const [a, b] = partRange(p.part_number, up.part_size_bytes, file.size);
        if (p.size_bytes === b - a && p.etag) etags.set(p.part_number, p.etag);
      }
    }
  } catch {
    /* send them all */
  }
  const resumed = etags.size;
  const sent = new Map<number, number>();
  for (const n of etags.keys()) {
    const [a, b] = partRange(n, up.part_size_bytes, file.size);
    sent.set(n, b - a);
  }
  const report = () => onProgress?.({ phase: "uploading", done: [...sent.values()].reduce((x, y) => x + y, 0), total: file.size, resumed });
  report();

  const queue = up.parts.filter((p) => !etags.has(p.part_number));
  const worker = async () => {
    for (let next = queue.shift(); next; next = queue.shift()) {
      const n = next.part_number;
      const [a, b] = partRange(n, up.part_size_bytes, file.size);
      let url = next.url;
      for (let attempt = 1; ; attempt++) {
        try {
          const etag = await putPart(url, file.slice(a, b), (x) => {
            sent.set(n, x);
            report();
          }, signal);
          etags.set(n, etag);
          sent.set(n, b - a);
          report();
          break;
        } catch (e) {
          sent.set(n, 0);
          if (e instanceof DOMException && e.name === "AbortError") throw e;
          if (!(e instanceof PartUploadError) || !e.retryable || attempt >= TRIES) throw e;
          await sleep(backoffMs(attempt), signal);
          // An expired presigned URL answers 403: ask for a fresh one.
          if (e.status === 403 && up.transport === "s3") url = await freshUrl(up.upload_id, n);
        }
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(PARALLEL, Math.max(1, queue.length)) }, worker));

  onProgress?.({ phase: "finishing", done: file.size, total: file.size, resumed });
  const parts = [...etags.entries()].sort((x, y) => x[0] - y[0]).map(([part_number, etag]) => ({ part_number, etag }));
  for (let attempt = 1; ; attempt++) {
    const res = await fetch(`${API_BASE}/uploads/${encodeURIComponent(up.upload_id)}/complete`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parts }),
      signal,
    });
    if (res.ok) break;
    const err = await problem(res, "The upload didn't finish.");
    if (!err.retryable || attempt >= TRIES) throw err;
    await sleep(backoffMs(attempt), signal);
  }
  return { uploadId: up.upload_id, sha256: record.sha256, resumeKey: key };
}
