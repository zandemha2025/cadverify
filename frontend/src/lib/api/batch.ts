/**
 * Batch API client -- create, progress, items, CSV export, cancel, list.
 *
 * Reuses the centralized apiClient from @/lib/api for auth headers,
 * rate-limit extraction, retries, and error handling.
 */

import { API_BASE } from "../api-base";
import {
  apiRecoveryMessage,
  networkRecoveryMessage,
} from "../api-recovery";
import {
  acceptedBatchFromErrorPayload,
  analysisPageHref,
} from "../recovery-records";

export { analysisPageHref };

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface BatchCreateResponse {
  batch_id: string;
  status: string;
  status_url: string;
}

export class BatchApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly acceptedBatch?: BatchCreateResponse;

  constructor(
    message: string,
    status: number,
    code?: string,
    acceptedBatch?: BatchCreateResponse,
  ) {
    super(message);
    this.name = "BatchApiError";
    this.status = status;
    this.code = code;
    this.acceptedBatch = acceptedBatch;
  }
}

export interface BatchProgress {
  batch_ulid: string;
  status:
    | "pending"
    | "extracting"
    | "processing"
    | "completed"
    | "failed"
    | "cancelled";
  input_mode: "zip" | "s3";
  total_items: number;
  completed_items: number;
  failed_items: number;
  skipped_items: number;
  pending_items: number;
  concurrency_limit: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface BatchItem {
  item_ulid: string;
  filename: string;
  status: string;
  priority: string;
  analysis_id: number | null;
  analysis_url: string | null;
  verdict: string | null;
  best_process: string | null;
  issue_count: number | null;
  error_message: string | null;
  duration_ms: number | null;
  created_at: string | null;
}

export interface BatchItemsResponse {
  batch_id: string;
  items: BatchItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface BatchSummaryRow {
  batch_ulid: string;
  status: string;
  total_items: number;
  completed_items: number;
  failed_items: number;
  skipped_items: number;
  created_at: string | null;
}

export interface BatchListResponse {
  batches: BatchSummaryRow[];
  next_cursor: string | null;
  has_more: boolean;
}

/* ------------------------------------------------------------------ */
/*  Fetch helper — same-origin proxy (session cookie sent automatically) */
/* ------------------------------------------------------------------ */

async function apiFetch(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, options);
  } catch {
    throw new Error(networkRecoveryMessage("batch"));
  }

  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: res.statusText }));
    const body = payload as {
      detail?: {
        code?: string;
      } | string;
      code?: string;
    };
    const detail = body.detail;
    const code = detail && typeof detail === "object" ? detail.code : body.code;
    const acceptedBatch = acceptedBatchFromErrorPayload(payload);
    throw new BatchApiError(
      apiRecoveryMessage({
        status: res.status,
        payload,
        resource: "batch",
        retryAfter: res.headers.get("retry-after"),
      }),
      res.status,
      code,
      acceptedBatch,
    );
  }

  return res;
}

async function apiFetchJson<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await apiFetch(url, options);
  return res.json() as Promise<T>;
}

/* ------------------------------------------------------------------ */
/*  API functions                                                      */
/* ------------------------------------------------------------------ */

/**
 * Create a batch from a ZIP file upload.
 * Uses FormData -- browser sets Content-Type with boundary automatically.
 */
export async function createBatch(
  file: File,
  options?: {
    webhookUrl?: string;
    manifest?: File;
    concurrencyLimit?: number;
  },
): Promise<BatchCreateResponse> {
  const formData = new FormData();
  formData.append("file", file);

  if (options?.webhookUrl) {
    formData.append("webhook_url", options.webhookUrl);
  }
  if (options?.manifest) {
    formData.append("manifest", options.manifest);
  }
  if (options?.concurrencyLimit != null) {
    formData.append("concurrency_limit", String(options.concurrencyLimit));
  }

  return apiFetchJson<BatchCreateResponse>(`${API_BASE}/batch`, {
    method: "POST",
    body: formData,
  });
}

/**
 * Get batch progress with exact durable item-state counters.
 */
export async function getBatchProgress(
  batchId: string,
): Promise<BatchProgress> {
  return apiFetchJson<BatchProgress>(`${API_BASE}/batch/${batchId}`);
}

/**
 * Get paginated batch items with optional status filter.
 */
export async function getBatchItems(
  batchId: string,
  options?: { status?: string; cursor?: string; limit?: number },
): Promise<BatchItemsResponse> {
  const url = new URL(`${API_BASE}/batch/${batchId}/items`, window.location.origin);
  if (options?.status) url.searchParams.set("status", options.status);
  if (options?.cursor) url.searchParams.set("cursor", options.cursor);
  if (options?.limit) url.searchParams.set("limit", String(options.limit));

  return apiFetchJson<BatchItemsResponse>(url.toString());
}

/**
 * Download batch results as CSV blob.
 */
export async function downloadBatchCsv(batchId: string): Promise<Blob> {
  const res = await apiFetch(`${API_BASE}/batch/${batchId}/results/csv`);
  return res.blob();
}

/**
 * Cancel a batch -- skips pending items.
 */
export async function cancelBatch(
  batchId: string,
): Promise<{ batch_id: string; status: string }> {
  return apiFetchJson<{ batch_id: string; status: string }>(
    `${API_BASE}/batch/${batchId}/cancel`,
    { method: "POST" },
  );
}

/**
 * List user's batches (paginated, most recent first).
 */
export async function listBatches(options?: {
  cursor?: string;
  limit?: number;
}): Promise<BatchListResponse> {
  const url = new URL(`${API_BASE}/batches`, window.location.origin);
  if (options?.cursor) url.searchParams.set("cursor", options.cursor);
  if (options?.limit) url.searchParams.set("limit", String(options.limit));

  return apiFetchJson<BatchListResponse>(url.toString());
}
