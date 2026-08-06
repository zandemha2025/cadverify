export interface BatchActivityState {
  status: string;
  totalItems: number;
  pendingItems: number;
  processedItems: number;
  concurrencyLimit: number;
}

/** Human activity copy that never implies CAD items exist before extraction. */
export function batchActivityCopy(state: BatchActivityState): string {
  if (state.status === "extracting") {
    return "Preparing the uploaded ZIP and validating its CAD files";
  }
  if (state.status === "pending" && state.totalItems === 0) {
    return "Waiting for secure ZIP preparation to start";
  }
  if (state.status === "pending") {
    return `${state.pendingItems} item${state.pendingItems === 1 ? "" : "s"} queued for analysis`;
  }
  if (state.status === "processing") {
    return `Processing up to ${state.concurrencyLimit} item${state.concurrencyLimit === 1 ? "" : "s"} in parallel`;
  }
  return `${state.processedItems} terminal item${state.processedItems === 1 ? "" : "s"}`;
}
