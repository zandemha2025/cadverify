/** Pure guards for durable records returned alongside accepted-operation errors. */

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

export interface AcceptedBatchIdentity {
  batch_id: string;
  status: string;
  status_url: string;
}

export function acceptedBatchFromErrorPayload(
  payload: unknown,
): AcceptedBatchIdentity | undefined {
  const body = record(payload);
  const detail = record(body?.detail);
  // The full backend's structured HTTP handler emits code-bearing errors at
  // the top level, while isolated FastAPI routers retain the conventional
  // {detail: {...}} envelope. Accept both wire shapes so an already-created
  // failed batch is never hidden from the recovery UI.
  const batch = record(detail?.accepted_batch ?? body?.accepted_batch);
  if (
    typeof batch?.batch_id !== "string" ||
    typeof batch.status !== "string" ||
    typeof batch.status_url !== "string"
  ) {
    return undefined;
  }
  return {
    batch_id: batch.batch_id,
    status: batch.status,
    status_url: batch.status_url,
  };
}

export function durableDesignFromErrorPayload<T extends { id: string }>(
  payload: unknown,
): T | undefined {
  const design = record(record(payload)?.design);
  return typeof design?.id === "string" ? design as T : undefined;
}

export function analysisPageHref(analysisUrl: string | null): string | null {
  if (!analysisUrl?.startsWith("/api/v1/analyses/")) return null;
  return analysisUrl.slice("/api/v1".length);
}

export function batchProgressSettled(status: string, pendingItems: number): boolean {
  return ["completed", "failed", "cancelled"].includes(status) && pendingItems === 0;
}
