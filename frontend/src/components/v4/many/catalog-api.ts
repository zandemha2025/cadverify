"use client";

/**
 * The catalog run's calls, same-origin through the authed proxy:
 * POST /catalog-runs (with upload progress), the board and its CSV, and the
 * account's usage (the catalog allowance rides on GET /auth/me/usage).
 */
import { API_BASE } from "@/lib/api-base";
import { forgetResume, PartUploadError, uploadPart } from "@/lib/api/part-upload";
import { STORED_CHECK_FROM_BYTES } from "@/lib/upload-limit";
import { pausedUploadKey, removeWork } from "../work/work-bar";
import type { Board, RunError } from "./catalog-model";

export interface RunCreated {
  batch_id: string;
  status: string;
  status_url: string;
  job_type: "catalog";
  board_url: string;
  parts: number;
  catalog: { free: true; new: number; reruns: number; cap: number; remaining: number } | { free: false };
}

export class CatalogRunError extends Error implements RunError {
  readonly code: string | null;
  readonly status: number;
  readonly batchId: string | null;
  readonly detail: Record<string, unknown> | null;
  constructor(message: string, status: number, code: string | null, detail: Record<string, unknown> | null) {
    super(message);
    this.name = "CatalogRunError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.batchId = detail && typeof detail.batch_id === "string" ? detail.batch_id : null;
  }
}

function problem(status: number, body: unknown, fallback: string): CatalogRunError {
  const b = (body ?? {}) as { detail?: unknown; message?: unknown; code?: unknown };
  const d = b.detail;
  if (d && typeof d === "object") {
    const o = d as Record<string, unknown>;
    return new CatalogRunError(typeof o.message === "string" ? o.message : fallback, status, typeof o.code === "string" ? o.code : null, o);
  }
  if (typeof d === "string") return new CatalogRunError(status === 413 ? "These files are larger than one run takes. Split them into smaller runs." : d, status, null, null);
  if (status === 413) return new CatalogRunError("These files are larger than one run takes. Split them into smaller runs.", status, "too_large", null);
  return new CatalogRunError(typeof b.message === "string" ? b.message : fallback, status, typeof b.code === "string" ? b.code : null, null);
}

export interface StartInput {
  zip: Blob;
  zipName: string;
  list?: File | null;
  materialClass?: string;
  quantity?: number | null;
}

/**
 * Starts a run. ``onProgress`` gets the upload's 0..1 (null while the size is unknown).
 *
 * A large ZIP goes straight to storage first, in parts that are retried and
 * resume after a dropped connection (lib/api/part-upload.ts); the run is then
 * started from the stored ZIP. A small one is posted with the request.
 */
export async function startCatalogRun(input: StartInput, onProgress?: (fraction: number | null) => void): Promise<RunCreated> {
  if (input.zip.size < STORED_CHECK_FROM_BYTES) return postCatalogRun(input, null, onProgress);
  const file = input.zip instanceof File ? input.zip : new File([input.zip], input.zipName, { type: "application/zip", lastModified: Date.now() });
  let uploaded;
  try {
    uploaded = await uploadPart(file, (p) => onProgress?.(p.total ? (p.phase === "hashing" ? 0 : p.done / p.total) : null), undefined, "batch_zip");
  } catch (e) {
    if (e instanceof PartUploadError) throw new CatalogRunError(e.message, e.status, e.code, null);
    throw new CatalogRunError("The upload didn’t reach ScaleCAD. Check your connection and try again; nothing was started.", 0, "network", null);
  }
  // The upload finished: a "paused" note about it from before a reload goes.
  removeWork(pausedUploadKey(uploaded.uploadId));
  const run = await postCatalogRun(input, uploaded.uploadId, onProgress);
  forgetResume(uploaded.resumeKey);
  return run;
}

function postCatalogRun(input: StartInput, directUploadId: string | null, onProgress?: (fraction: number | null) => void): Promise<RunCreated> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    if (directUploadId) form.append("direct_upload_id", directUploadId);
    else form.append("file", input.zip, input.zipName);
    if (input.list) form.append("manifest", input.list, input.list.name);
    if (input.materialClass) form.append("material_class", input.materialClass);
    if (input.quantity != null) form.append("quantity", String(input.quantity));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/catalog-runs`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => onProgress?.(e.lengthComputable && e.total ? e.loaded / e.total : null);
    xhr.onload = () => {
      const body = xhr.response ?? (() => {
        try {
          return JSON.parse(xhr.responseText);
        } catch {
          return null;
        }
      })();
      if (xhr.status >= 200 && xhr.status < 300 && body) resolve(body as RunCreated);
      else reject(problem(xhr.status, body, `The run didn’t start (${xhr.status}).`));
    };
    xhr.onerror = () => reject(new CatalogRunError("The upload didn’t reach ScaleCAD. Check your connection and try again; nothing was started.", 0, "network", null));
    xhr.send(form);
  });
}

/** A read that gives up after ``ms``, so a poll never hangs on a stalled request. */
export function timedSignal(ms: number): AbortSignal {
  if (typeof AbortSignal !== "undefined" && "timeout" in AbortSignal) return AbortSignal.timeout(ms);
  const c = new AbortController();
  setTimeout(() => c.abort(), ms);
  return c.signal;
}

export async function fetchBoard(batchId: string, timeoutMs = 25_000): Promise<Board> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/batch/${encodeURIComponent(batchId)}/catalog`, { cache: "no-store", signal: timedSignal(timeoutMs) });
  } catch {
    throw new CatalogRunError("The server couldn’t be reached. Check your connection and try again.", 0, "network", null);
  }
  if (!res.ok) throw problem(res.status, await res.json().catch(() => null), `The board didn’t load (${res.status}).`);
  return (await res.json()) as Board;
}

export async function downloadBoardCsv(batchId: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/batch/${encodeURIComponent(batchId)}/catalog.csv`, { cache: "no-store" });
  if (!res.ok) throw problem(res.status, await res.json().catch(() => null), "The CSV didn’t download.");
  return res.blob();
}

export async function fetchUsage(): Promise<unknown> {
  const res = await fetch("/api/auth/me/usage", { cache: "no-store" });
  if (!res.ok) throw new Error(`usage ${res.status}`);
  return res.json();
}
