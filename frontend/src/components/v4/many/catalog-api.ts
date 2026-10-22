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
  /** null while ScaleCAD's worker unpacks a stored ZIP (``preparing``). */
  parts: number | null;
  preparing?: boolean;
  catalog: { free: true; new: number; reruns: number; cap: number; remaining: number } | { free: boolean; pending: true } | { free: false };
}

/** What the board adds about a run from a stored ZIP: unpacking on the worker, then its parts or why it stopped. */
interface Preparation {
  status: string;
  preparing?: boolean;
  parts?: number | null;
  free?: boolean;
  reservation?: { new: number; reruns: number; cap: number; remaining: number } | null;
  failure?: ({ code?: string; message?: string } & Record<string, unknown>) | null;
}

/**
 * A run from a ZIP uploaded to storage is unpacked on ScaleCAD's worker. Wait for
 * that (polling the board), then give the run its parts and allowance as a
 * posted ZIP's answer has them; a refusal there (the allowance, a damaged
 * upload, a bad ZIP) comes back as the same error the request would have given.
 */
export async function waitUntilUnpacked(run: RunCreated, onTick?: () => void): Promise<RunCreated> {
  if (!run.preparing) return run;
  for (let misses = 0; ; ) {
    await new Promise((r) => setTimeout(r, misses ? Math.min(20_000, 2500 * (misses + 1)) : 2000));
    let b: Preparation;
    try {
      b = (await fetchBoard(run.batch_id, 15_000)) as unknown as Preparation;
      misses = 0;
    } catch (e) {
      if (e instanceof CatalogRunError && e.status === 404) throw e;
      misses += 1;
      continue;
    }
    onTick?.();
    if (b.status === "failed") {
      const f = b.failure ?? {};
      throw new CatalogRunError(typeof f.message === "string" ? f.message : "The ZIP couldn’t be unpacked, so the run stopped. Nothing was counted.", 0, typeof f.code === "string" ? f.code : null, { ...f, batch_id: null });
    }
    if (b.preparing) continue;
    const r = b.reservation;
    return {
      ...run,
      status: b.status,
      preparing: false,
      parts: b.parts ?? 0,
      catalog: r ? { free: true, new: r.new, reruns: r.reruns, cap: r.cap, remaining: r.remaining } : { free: false },
    };
  }
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

/** One cell of a parts list a run can't start with: where, what it says, why, and what it takes. */
export interface ListProblem {
  row: number | null;
  column: string | null;
  value: string | null;
  why: string;
  accepted: string | null;
  message: string;
}

/** A spec the list names that ScaleCAD keeps as written and doesn't price (it never stops a run). */
export interface NotPricedSpec {
  row: number;
  part: string | null;
  column: string;
  value: string;
  why: string;
}

/** POST /catalog-runs/parts-list: the whole list read at once, nothing started or stored. */
export interface ListCheck {
  ok: boolean;
  rows: number | null;
  with_quantity: number | null;
  with_price: number | null;
  problems: ListProblem[];
  not_priced: { count: number; notes: NotPricedSpec[] };
}

/** Read a picked parts list without uploading the ZIP: every problem in it, at once. */
export async function checkPartsList(list: Blob, name: string): Promise<ListCheck> {
  const form = new FormData();
  form.append("manifest", list, name);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/catalog-runs/parts-list`, { method: "POST", body: form, signal: timedSignal(30_000) });
  } catch {
    throw new CatalogRunError("The parts list couldn’t be checked: ScaleCAD wasn’t reached. It is checked again when the run starts.", 0, "network", null);
  }
  if (!res.ok) throw problem(res.status, await res.json().catch(() => null), `The parts list couldn’t be checked (${res.status}).`);
  return (await res.json()) as ListCheck;
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
    // A file changed on disk after it was picked fails the same way as a dropped connection (op-05), so say both.
    xhr.onerror = () => reject(new CatalogRunError("The upload stopped before it reached ScaleCAD; nothing was started. If you changed a file after picking it, pick it again. Otherwise check your connection and try again.", 0, "network", null));
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

/** Check a run's parts again in the run: the ones named, or every part not checked. */
export async function recheckParts(batchId: string, itemIds?: string[]): Promise<{ batch_id: string; rechecking: string[]; files_gone?: string[]; status: string }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/batch/${encodeURIComponent(batchId)}/catalog/recheck`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(itemIds?.length ? { item_ids: itemIds } : {}),
    });
  } catch {
    throw new CatalogRunError("The server couldn’t be reached. Check your connection and try again.", 0, "network", null);
  }
  if (!res.ok) throw problem(res.status, await res.json().catch(() => null), "The parts weren’t checked again.");
  return res.json();
}

/**
 * Invite someone to the organization as a viewer, to look at this run: the email
 * names who sent it, the organization and the run, and accepting opens the run.
 */
export async function inviteToRun(batchId: string, email: string): Promise<{ emailed: boolean; accept_link: string }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/orgs/invites`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, role: "viewer", next: `/app/many/${batchId}` }),
    });
  } catch {
    throw new CatalogRunError("The server couldn’t be reached. Check your connection and try again.", 0, "network", null);
  }
  if (!res.ok) {
    const fallback = res.status === 403 ? "Only an admin of your organization can invite people." : "The invitation wasn’t sent.";
    throw problem(res.status, await res.json().catch(() => null), fallback);
  }
  return res.json();
}
