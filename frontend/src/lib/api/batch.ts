/**
 * Batch API client -- create, progress, items, CSV export, cancel, list.
 *
 * Reuses the centralized apiClient from @/lib/api for auth headers,
 * rate-limit extraction, retries, and error handling.
 */

import { API_BASE } from "../api-base";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface BatchCreateResponse {
  batch_id: string;
  status: string;
  status_url: string;
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
  const res = await fetch(url, options);

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || body.message || `Request failed: ${res.status}`);
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
 * Get batch progress (denormalized counters).
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
