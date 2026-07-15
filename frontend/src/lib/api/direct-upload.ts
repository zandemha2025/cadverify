import { API_BASE } from "../api-base";
import {
  apiRecoveryMessage,
  networkRecoveryMessage,
} from "../api-recovery";

export const MULTIPART_UPLOAD_CONCURRENCY = 4;
export const MULTIPART_UPLOAD_MAX_ATTEMPTS = 4;
export const MULTIPART_RETRY_BASE_MS = 500;
export const MULTIPART_PART_URL_MAX_REFRESHES = 3;
export const MULTIPART_PART_URL_REFRESH_SKEW_MS = 60_000;

export type UploadStage =
  | "checking"
  | "hashing"
  | "preparing"
  | "uploading"
  | "retrying"
  | "completing"
  | "complete"
  | "proxying"
  | "creating";

export interface UploadProgress {
  stage: UploadStage;
  /** Acknowledged byte progress. Null means the browser cannot measure it. */
  percent: number | null;
  uploadedBytes: number;
  totalBytes: number;
  completedParts?: number;
  totalParts?: number;
  partNumber?: number;
  nextAttempt?: number;
  maxAttempts?: number;
  retryDelayMs?: number;
}

export interface UploadCapabilities {
  direct_upload: boolean;
}

export interface MultipartUploadPart {
  part_number: number;
  url: string;
  expires_at?: string;
}

export interface MultipartUploadSession {
  upload_id: string;
  part_size_bytes: number;
  parts: MultipartUploadPart[];
  expires_at: string;
  /** Optional rollout alias; accepted only when it points back through /api/v1. */
  complete_url?: string;
  /** Optional rollout alias; accepted only when it points back through /api/v1. */
  refresh_parts_url?: string;
}

export interface CompletedMultipartPart {
  part_number: number;
  etag: string;
}

type DirectUploadFailureStage =
  | "capabilities"
  | "initiate"
  | "refresh"
  | "part"
  | "complete";

export class DirectUploadError extends Error {
  readonly status?: number;
  readonly stage: DirectUploadFailureStage;

  constructor(
    message: string,
    stage: DirectUploadFailureStage,
    status?: number,
  ) {
    super(message);
    this.name = "DirectUploadError";
    this.stage = stage;
    this.status = status;
  }
}

type Fetcher = typeof fetch;
type Sleeper = (delayMs: number) => Promise<void>;

export interface DirectUploadOptions {
  onProgress?: (progress: UploadProgress) => void;
  /** Test seam; production callers use window.fetch. */
  fetcher?: Fetcher;
  /** Test seam; production callers use a real exponential-backoff timer. */
  sleep?: Sleeper;
  /** Test seam; production hashes incrementally with hash-wasm. */
  checksum?: (file: File) => Promise<string>;
}

const HASH_CHUNK_BYTES = 8 * 1024 * 1024;
const INITIATE_MAX_ATTEMPTS = 3;
const COMPLETE_RECOVERY_ATTEMPTS = 3;
const SUCCESSFUL_UPLOAD_STATUSES = new Set([
  "completed",
  "attached",
  "preparing",
  "prepared",
  "consumed",
]);
const TERMINAL_UPLOAD_STATUSES = new Set(["aborted", "expired", "failed"]);
const attemptStorageByFile = new WeakMap<File, string>();

class CompletionOutcomeUnknownError extends DirectUploadError {
  constructor(message: string) {
    super(message, "complete");
    this.name = "CompletionOutcomeUnknownError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function reportProgress(
  callback: DirectUploadOptions["onProgress"],
  progress: UploadProgress,
): void {
  // Upload correctness and cleanup must not depend on presentation callbacks.
  try {
    callback?.(progress);
  } catch {
    // Ignore UI callback failures.
  }
}

async function defaultSleep(delayMs: number): Promise<void> {
  await new Promise<void>((resolve) => globalThis.setTimeout(resolve, delayMs));
}

async function sha256File(
  file: File,
  onProgress: DirectUploadOptions["onProgress"],
): Promise<string> {
  const { createSHA256 } = await import("hash-wasm");
  const hasher = await createSHA256();
  let processed = 0;

  reportProgress(onProgress, {
    stage: "hashing",
    percent: 0,
    uploadedBytes: 0,
    totalBytes: file.size,
  });
  while (processed < file.size) {
    const end = Math.min(processed + HASH_CHUNK_BYTES, file.size);
    const bytes = new Uint8Array(await file.slice(processed, end).arrayBuffer());
    hasher.update(bytes);
    processed = end;
    reportProgress(onProgress, {
      stage: "hashing",
      percent: Math.floor((processed / file.size) * 100),
      uploadedBytes: 0,
      totalBytes: file.size,
    });
  }
  return hasher.digest("hex");
}

function storageKeyForAttempt(file: File, checksum: string): string {
  return `proofshape:direct-upload:v1:${checksum}:${file.size}:${file.lastModified}:${encodeURIComponent(file.name)}`;
}

function randomIdempotencyKey(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `browser-${uuid}`;
  const bytes = new Uint8Array(24);
  globalThis.crypto.getRandomValues(bytes);
  return `browser-${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function idempotencyAttempt(file: File, checksum: string): {
  key: string;
  storageKey: string;
} {
  const storageKey = storageKeyForAttempt(file, checksum);
  let key: string | null = null;
  try {
    key = globalThis.sessionStorage?.getItem(storageKey) ?? null;
  } catch {
    // Storage may be disabled; same-call retries still reuse the generated key.
  }
  if (!key) {
    key = randomIdempotencyKey();
    try {
      globalThis.sessionStorage?.setItem(storageKey, key);
    } catch {
      // The backend idempotency contract still protects automatic retries.
    }
  }
  attemptStorageByFile.set(file, storageKey);
  return { key, storageKey };
}

function clearAttemptStorage(storageKey: string): void {
  try {
    globalThis.sessionStorage?.removeItem(storageKey);
  } catch {
    // Best-effort browser cleanup; server expiry remains authoritative.
  }
}

/** Clear the reload-recovery key only after POST /batch is confirmed. */
export function finalizeDirectUploadAttempt(file: File): void {
  const storageKey = attemptStorageByFile.get(file);
  if (storageKey) clearAttemptStorage(storageKey);
  attemptStorageByFile.delete(file);
}

async function waitForRetry(
  sleep: Sleeper,
  delayMs: number,
  signal: AbortSignal,
): Promise<void> {
  if (signal.aborted) {
    throw new DirectUploadError("The upload was stopped.", "part");
  }

  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      reject(new DirectUploadError("The upload was stopped.", "part"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    Promise.resolve()
      .then(() => sleep(delayMs))
      .then(
        () => {
          signal.removeEventListener("abort", onAbort);
          resolve();
        },
        (error: unknown) => {
          signal.removeEventListener("abort", onAbort);
          reject(error);
        },
      );
  });
}

async function apiRequest(
  url: string,
  options: RequestInit,
  stage: DirectUploadFailureStage,
  fetcher: Fetcher,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetcher(url, options);
  } catch {
    throw new DirectUploadError(
      networkRecoveryMessage("upload"),
      stage,
    );
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => undefined);
    throw new DirectUploadError(
      apiRecoveryMessage({
        status: response.status,
        payload,
        resource: "upload",
        retryAfter: response.headers.get("retry-after"),
      }),
      stage,
      response.status,
    );
  }

  return response;
}

async function apiRequestJson(
  url: string,
  options: RequestInit,
  stage: DirectUploadFailureStage,
  fetcher: Fetcher,
): Promise<unknown> {
  const response = await apiRequest(url, options, stage, fetcher);
  try {
    return await response.json();
  } catch {
    throw new DirectUploadError(
      "The upload service returned an invalid response. Retry the ZIP.",
      stage,
      response.status,
    );
  }
}

export async function getUploadCapabilities(
  fetcher: Fetcher = fetch,
): Promise<UploadCapabilities> {
  const payload = await apiRequestJson(
    `${API_BASE}/uploads/capabilities`,
    { method: "GET", cache: "no-store" },
    "capabilities",
    fetcher,
  );

  if (!isRecord(payload)) {
    throw new DirectUploadError(
      "The upload service returned invalid capabilities. Retry the ZIP.",
      "capabilities",
    );
  }

  const directUpload =
    typeof payload.direct_upload === "boolean"
      ? payload.direct_upload
      : typeof payload.available === "boolean"
        ? payload.available
        : null;
  if (directUpload == null) {
    throw new DirectUploadError(
      "The upload service returned invalid capabilities. Retry the ZIP.",
      "capabilities",
    );
  }

  return { direct_upload: directUpload };
}

function sameOriginApiUrl(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  if (value.startsWith("/api/v1/")) {
    return `${API_BASE}/${value.slice("/api/v1/".length)}`;
  }
  if (value.startsWith(`${API_BASE}/`)) return value;
  return undefined;
}

function parseMultipartPart(
  rawPart: unknown,
  stage: "initiate" | "refresh",
): MultipartUploadPart {
  if (
    !isRecord(rawPart) ||
    !Number.isSafeInteger(rawPart.part_number) ||
    (rawPart.part_number as number) <= 0 ||
    typeof rawPart.url !== "string"
  ) {
    throw new DirectUploadError(
      "The upload service returned an invalid part plan. Retry the ZIP.",
      stage,
    );
  }

  try {
    const protocol = new URL(rawPart.url).protocol;
    if (protocol !== "https:" && protocol !== "http:") throw new Error();
  } catch {
    throw new DirectUploadError(
      "The upload service returned an invalid part destination. Retry the ZIP.",
      stage,
    );
  }

  const rawExpiry = rawPart.expires_at;
  if (
    rawExpiry !== undefined &&
    (typeof rawExpiry !== "string" || Number.isNaN(Date.parse(rawExpiry)))
  ) {
    throw new DirectUploadError(
      "The upload service returned an invalid part expiry. Retry the ZIP.",
      stage,
    );
  }

  return {
    part_number: rawPart.part_number as number,
    url: rawPart.url,
    expires_at: rawExpiry as string | undefined,
  };
}

function parseMultipartSession(
  payload: unknown,
  fileSize: number,
): MultipartUploadSession {
  if (!isRecord(payload)) {
    throw new DirectUploadError(
      "The upload service did not create a valid upload. Retry the ZIP.",
      "initiate",
    );
  }

  const uploadId =
    typeof payload.upload_id === "string"
      ? payload.upload_id
      : typeof payload.direct_upload_id === "string"
        ? payload.direct_upload_id
        : null;
  if (!uploadId?.trim()) {
    throw new DirectUploadError(
      "The upload service did not create a valid upload. Retry the ZIP.",
      "initiate",
    );
  }

  const partSize = payload.part_size_bytes;
  const expiresAt = payload.expires_at;
  const rawParts = payload.parts;
  if (
    !Number.isSafeInteger(partSize) ||
    (partSize as number) <= 0 ||
    typeof expiresAt !== "string" ||
    !Array.isArray(rawParts)
  ) {
    throw new DirectUploadError(
      "The upload service returned an invalid part plan. Retry the ZIP.",
      "initiate",
    );
  }

  const parts = rawParts.map((rawPart) =>
    parseMultipartPart(rawPart, "initiate"),
  );

  parts.sort((left, right) => left.part_number - right.part_number);
  const expectedPartCount = Math.max(1, Math.ceil(fileSize / (partSize as number)));
  const hasExactPartPlan =
    parts.length === expectedPartCount &&
    parts.every((part, index) => part.part_number === index + 1);
  if (!hasExactPartPlan) {
    throw new DirectUploadError(
      "The upload service returned an incomplete part plan. Retry the ZIP.",
      "initiate",
    );
  }

  return {
    upload_id: uploadId,
    part_size_bytes: partSize as number,
    parts,
    expires_at: expiresAt,
    complete_url: sameOriginApiUrl(payload.complete_url),
    refresh_parts_url: sameOriginApiUrl(payload.refresh_parts_url),
  };
}

function partUrlNeedsRefresh(part: MultipartUploadPart): boolean {
  if (!part.expires_at) return false;
  return (
    Date.parse(part.expires_at) <=
    Date.now() + MULTIPART_PART_URL_REFRESH_SKEW_MS
  );
}

async function refreshMultipartPartUrl(
  session: MultipartUploadSession,
  partNumber: number,
  fetcher: Fetcher,
): Promise<MultipartUploadPart> {
  const payload = await apiRequestJson(
    session.refresh_parts_url ??
      `${API_BASE}/uploads/${encodeURIComponent(session.upload_id)}/parts`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ part_numbers: [partNumber] }),
    },
    "refresh",
    fetcher,
  );

  if (!isRecord(payload) || !Array.isArray(payload.parts) || payload.parts.length !== 1) {
    throw new DirectUploadError(
      "The upload service returned an invalid refreshed part. Retry the ZIP.",
      "refresh",
    );
  }
  const returnedUploadId =
    typeof payload.upload_id === "string"
      ? payload.upload_id
      : typeof payload.direct_upload_id === "string"
        ? payload.direct_upload_id
        : undefined;
  if (returnedUploadId !== undefined && returnedUploadId !== session.upload_id) {
    throw new DirectUploadError(
      "The upload service returned a refreshed part for the wrong upload. Retry the ZIP.",
      "refresh",
    );
  }

  const refreshedPart = parseMultipartPart(payload.parts[0], "refresh");
  if (refreshedPart.part_number !== partNumber) {
    throw new DirectUploadError(
      "The upload service returned the wrong refreshed part. Retry the ZIP.",
      "refresh",
    );
  }
  return refreshedPart;
}

function isTransientStatus(status: number): boolean {
  return (
    status === 408 ||
    status === 409 ||
    status === 425 ||
    status === 429 ||
    status >= 500
  );
}

function batchZipContentType(file: File): string {
  const normalized = file.type.split(";", 1)[0].trim().toLowerCase();
  return normalized === "application/x-zip-compressed"
    ? normalized
    : "application/zip";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function uploadPart(
  initialPart: MultipartUploadPart,
  body: Blob,
  fetcher: Fetcher,
  sleep: Sleeper,
  signal: AbortSignal,
  refreshUrl: (partNumber: number) => Promise<MultipartUploadPart>,
  onRetry: (nextAttempt: number, delayMs: number) => void,
): Promise<CompletedMultipartPart> {
  let part = initialPart;
  let lastStatus: number | undefined;
  let refreshCount = 0;

  const refresh = async () => {
    if (refreshCount >= MULTIPART_PART_URL_MAX_REFRESHES) {
      throw new DirectUploadError(
        `Part ${initialPart.part_number} could not obtain a fresh upload URL. Retry the ZIP.`,
        "refresh",
      );
    }
    part = await refreshUrl(initialPart.part_number);
    refreshCount += 1;
  };

  for (let attempt = 1; attempt <= MULTIPART_UPLOAD_MAX_ATTEMPTS; attempt += 1) {
    if (signal.aborted) {
      throw new DirectUploadError("The upload was stopped.", "part");
    }
    if (partUrlNeedsRefresh(part)) await refresh();

    let response: Response | undefined;
    let networkFailure = false;
    try {
      response = await fetcher(part.url, {
        method: "PUT",
        body,
        credentials: "omit",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal,
      });
    } catch (error) {
      if (signal.aborted || isAbortError(error)) {
        throw new DirectUploadError("The upload was stopped.", "part");
      }
      networkFailure = true;
    }

    if (response?.ok) {
      const etag = response.headers.get("etag")?.trim();
      if (!etag) {
        throw new DirectUploadError(
          `Part ${part.part_number} uploaded without a verifiable receipt. Retry the ZIP.`,
          "part",
          response.status,
        );
      }
      return { part_number: initialPart.part_number, etag };
    }

    if (response) lastStatus = response.status;
    const refreshableForbidden =
      response?.status === 403 &&
      refreshCount < MULTIPART_PART_URL_MAX_REFRESHES;
    const transient =
      networkFailure ||
      refreshableForbidden ||
      Boolean(response && isTransientStatus(response.status));
    if (transient && attempt < MULTIPART_UPLOAD_MAX_ATTEMPTS) {
      const delayMs = MULTIPART_RETRY_BASE_MS * 2 ** (attempt - 1);
      onRetry(attempt + 1, delayMs);
      await waitForRetry(sleep, delayMs, signal);
      if (refreshableForbidden) await refresh();
      continue;
    }

    if (transient) {
      throw new DirectUploadError(
        `Part ${initialPart.part_number} could not be uploaded after ${MULTIPART_UPLOAD_MAX_ATTEMPTS} attempts. Check your connection and retry the ZIP.`,
        "part",
        lastStatus,
      );
    }

    throw new DirectUploadError(
      `Part ${initialPart.part_number} was rejected during upload${lastStatus ? ` (${lastStatus})` : ""}. Retry the ZIP.`,
      "part",
      lastStatus,
    );
  }

  throw new DirectUploadError(
    `Part ${initialPart.part_number} could not be uploaded. Retry the ZIP.`,
    "part",
    lastStatus,
  );
}

async function abortMultipartUpload(
  uploadId: string,
  fetcher: Fetcher,
): Promise<void> {
  const response = await fetcher(
    `${API_BASE}/uploads/${encodeURIComponent(uploadId)}/abort`,
    { method: "POST" },
  );
  if (!response.ok) {
    // Compatibility for the earlier multipart-prefixed DELETE contract. The
    // canonical action route always goes first, so current deployments do not
    // incur a browser-visible probe failure.
    if (response.status === 404 || response.status === 405) {
      const compatibilityResponse = await fetcher(
        `${API_BASE}/uploads/multipart/${encodeURIComponent(uploadId)}`,
        { method: "DELETE" },
      );
      if (compatibilityResponse.ok) return;
    }
    throw new Error("Multipart abort was not acknowledged");
  }
}

function uploadStatus(payload: unknown): string | null {
  return isRecord(payload) && typeof payload.status === "string"
    ? payload.status.toLowerCase()
    : null;
}

async function initiateMultipartUpload(
  file: File,
  checksum: string,
  idempotencyKey: string,
  fetcher: Fetcher,
  sleep: Sleeper,
): Promise<unknown> {
  let lastError: DirectUploadError | null = null;
  for (let attempt = 1; attempt <= INITIATE_MAX_ATTEMPTS; attempt += 1) {
    try {
      return await apiRequestJson(
        `${API_BASE}/uploads/multipart`,
        {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify({
            purpose: "batch_zip",
            filename: file.name,
            size_bytes: file.size,
            content_type: batchZipContentType(file),
            checksum_sha256: checksum,
          }),
        },
        "initiate",
        fetcher,
      );
    } catch (error) {
      if (!(error instanceof DirectUploadError)) throw error;
      lastError = error;
      const retryable =
        error.status === undefined || isTransientStatus(error.status);
      if (!retryable || attempt === INITIATE_MAX_ATTEMPTS) throw error;
      await sleep(MULTIPART_RETRY_BASE_MS * 2 ** (attempt - 1));
    }
  }
  throw lastError ?? new DirectUploadError(
    "The upload could not be initiated. Retry the ZIP.",
    "initiate",
  );
}

async function completeMultipartWithRecovery(
  session: MultipartUploadSession,
  receipts: CompletedMultipartPart[],
  fetcher: Fetcher,
  sleep: Sleeper,
): Promise<void> {
  const completeOptions: RequestInit = {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ parts: receipts }),
  };
  const canonicalCompleteUrl =
    session.complete_url ??
    `${API_BASE}/uploads/${encodeURIComponent(session.upload_id)}/complete`;

  const completeOnce = async () => {
    try {
      await apiRequest(
        canonicalCompleteUrl,
        completeOptions,
        "complete",
        fetcher,
      );
    } catch (error) {
      if (
        error instanceof DirectUploadError &&
        (error.status === 404 || error.status === 405)
      ) {
        await apiRequest(
          `${API_BASE}/uploads/multipart/${encodeURIComponent(session.upload_id)}/complete`,
          completeOptions,
          "complete",
          fetcher,
        );
        return;
      }
      throw error;
    }
  };

  try {
    await completeOnce();
    return;
  } catch (initialError) {
    let lastError = initialError;
    for (let attempt = 1; attempt <= COMPLETE_RECOVERY_ATTEMPTS; attempt += 1) {
      let statusPayload: unknown;
      try {
        statusPayload = await apiRequestJson(
          `${API_BASE}/uploads/${encodeURIComponent(session.upload_id)}`,
          { method: "GET", cache: "no-store" },
          "complete",
          fetcher,
        );
      } catch (statusError) {
        lastError = statusError;
        if (attempt < COMPLETE_RECOVERY_ATTEMPTS) {
          await sleep(MULTIPART_RETRY_BASE_MS * 2 ** (attempt - 1));
          continue;
        }
        break;
      }

      const status = uploadStatus(statusPayload);
      if (status && SUCCESSFUL_UPLOAD_STATUSES.has(status)) return;
      if (status && TERMINAL_UPLOAD_STATUSES.has(status)) {
        throw new DirectUploadError(
          "The upload reached a terminal state before completion. Retry the ZIP.",
          "complete",
        );
      }
      if (status !== "initiated" && status !== "completing") {
        lastError = new DirectUploadError(
          "The upload service returned an unknown recovery state. Retry the ZIP.",
          "complete",
        );
        break;
      }

      try {
        await completeOnce();
        return;
      } catch (retryError) {
        lastError = retryError;
        if (attempt < COMPLETE_RECOVERY_ATTEMPTS) {
          await sleep(MULTIPART_RETRY_BASE_MS * 2 ** (attempt - 1));
        }
      }
    }

    const detail =
      lastError instanceof Error ? lastError.message : "completion was not confirmed";
    throw new CompletionOutcomeUnknownError(
      `The ZIP reached storage, but completion could not be confirmed (${detail}). Retry the same ZIP; ProofShape will resume the same upload instead of creating a duplicate.`,
    );
  }
}

/**
 * Upload a batch ZIP through presigned multipart URLs and return the opaque
 * direct-upload ID accepted by POST /batch. Presigned URLs stay in this call's
 * local scope and are never exposed through progress events or browser storage.
 */
export async function uploadBatchZipDirect(
  file: File,
  options: DirectUploadOptions = {},
): Promise<string> {
  const fetcher = options.fetcher ?? fetch;
  const sleep = options.sleep ?? defaultSleep;
  let uploadId: string | null = null;
  let attemptStorageKey: string | null = null;
  let preserveForRetry = false;

  try {
    const checksum = options.checksum
      ? await options.checksum(file)
      : await sha256File(file, options.onProgress);
    if (!/^[0-9a-f]{64}$/.test(checksum)) {
      throw new DirectUploadError(
        "The ZIP checksum could not be calculated safely. Retry the ZIP.",
        "initiate",
      );
    }
    let attempt = idempotencyAttempt(file, checksum);
    attemptStorageKey = attempt.storageKey;

    reportProgress(options.onProgress, {
      stage: "preparing",
      percent: 0,
      uploadedBytes: 0,
      totalBytes: file.size,
    });

    let sessionPayload: unknown;
    for (let generation = 0; generation < 2; generation += 1) {
      try {
        sessionPayload = await initiateMultipartUpload(
          file,
          checksum,
          attempt.key,
          fetcher,
          sleep,
        );
      } catch (error) {
        // A missing initiation response is exactly what Idempotency-Key is for.
        // Keep the reload-safe key so the user's retry resolves the same row.
        if (error instanceof DirectUploadError && error.status === undefined) {
          preserveForRetry = true;
        }
        throw error;
      }

      const replayStatus = uploadStatus(sessionPayload);
      if (replayStatus && TERMINAL_UPLOAD_STATUSES.has(replayStatus)) {
        clearAttemptStorage(attempt.storageKey);
        if (generation === 0) {
          attempt = idempotencyAttempt(file, checksum);
          attemptStorageKey = attempt.storageKey;
          continue;
        }
      }
      break;
    }

    if (isRecord(sessionPayload)) {
      const rawUploadId =
        typeof sessionPayload.upload_id === "string"
          ? sessionPayload.upload_id
          : typeof sessionPayload.direct_upload_id === "string"
            ? sessionPayload.direct_upload_id
            : null;
      if (rawUploadId?.trim()) uploadId = rawUploadId;
    }
    const replayStatus = uploadStatus(sessionPayload);
    if (
      uploadId &&
      replayStatus &&
      SUCCESSFUL_UPLOAD_STATUSES.has(replayStatus)
    ) {
      reportProgress(options.onProgress, {
        stage: "complete",
        percent: 100,
        uploadedBytes: file.size,
        totalBytes: file.size,
      });
      return uploadId;
    }
    if (replayStatus && TERMINAL_UPLOAD_STATUSES.has(replayStatus)) {
      throw new DirectUploadError(
        "The previous upload attempt is no longer usable. Retry the ZIP.",
        "initiate",
      );
    }
    const session = parseMultipartSession(sessionPayload, file.size);
    uploadId = session.upload_id;

    let nextPartIndex = 0;
    let uploadedBytes = 0;
    let completedParts = 0;
    const receipts: CompletedMultipartPart[] = [];
    const failures: DirectUploadError[] = [];
    const controller = new AbortController();

    const emit = (
      stage: UploadStage,
      retry?: {
        partNumber: number;
        nextAttempt: number;
        retryDelayMs: number;
      },
    ) => {
      reportProgress(options.onProgress, {
        stage,
        percent:
          file.size === 0 || uploadedBytes >= file.size
            ? 100
            : Math.floor((uploadedBytes / file.size) * 100),
        uploadedBytes,
        totalBytes: file.size,
        completedParts,
        totalParts: session.parts.length,
        partNumber: retry?.partNumber,
        nextAttempt: retry?.nextAttempt,
        maxAttempts: retry ? MULTIPART_UPLOAD_MAX_ATTEMPTS : undefined,
        retryDelayMs: retry?.retryDelayMs,
      });
    };

    emit("uploading");

    const worker = async () => {
      while (failures.length === 0) {
        const index = nextPartIndex;
        nextPartIndex += 1;
        if (index >= session.parts.length) return;

        const part = session.parts[index];
        const start = (part.part_number - 1) * session.part_size_bytes;
        const body = file.slice(start, Math.min(start + session.part_size_bytes, file.size));

        try {
          const receipt = await uploadPart(
            part,
            body,
            fetcher,
            sleep,
            controller.signal,
            (partNumber) =>
              refreshMultipartPartUrl(session, partNumber, fetcher),
            (nextAttempt, retryDelayMs) => {
              emit("retrying", {
                partNumber: part.part_number,
                nextAttempt,
                retryDelayMs,
              });
            },
          );
          if (failures.length > 0) return;
          receipts.push(receipt);
          uploadedBytes += body.size;
          completedParts += 1;
          emit("uploading");
        } catch (error) {
          if (failures.length === 0) {
            failures.push(
              error instanceof DirectUploadError
                ? error
                : new DirectUploadError(
                    "The ZIP upload could not finish. Retry the ZIP.",
                    "part",
                  ),
            );
            controller.abort();
          }
        }
      }
    };

    const workerCount = Math.min(
      MULTIPART_UPLOAD_CONCURRENCY,
      session.parts.length,
    );
    await Promise.all(Array.from({ length: workerCount }, worker));
    if (failures.length > 0) throw failures[0];

    receipts.sort((left, right) => left.part_number - right.part_number);
    emit("completing");
    try {
      await completeMultipartWithRecovery(
        session,
        receipts,
        fetcher,
        sleep,
      );
    } catch (error) {
      if (error instanceof CompletionOutcomeUnknownError) {
        preserveForRetry = true;
      }
      throw error;
    }
    emit("complete");
    return session.upload_id;
  } catch (error) {
    if (uploadId && !preserveForRetry) {
      try {
        await abortMultipartUpload(uploadId, fetcher);
        if (attemptStorageKey) clearAttemptStorage(attemptStorageKey);
      } catch {
        // Preserve the actionable upload failure. The backend expiry remains a
        // cleanup backstop when an abort request itself cannot be acknowledged.
      }
    }
    if (error instanceof DirectUploadError) throw error;
    throw new DirectUploadError(
      "The ZIP upload could not finish. Retry the ZIP.",
      "part",
    );
  }
}
