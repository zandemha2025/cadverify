export type PollStatus = "queued" | "running" | "done" | "partial" | "failed";

export interface PollJobStatus {
  status: PollStatus;
  result_url: string | null;
  error: { code: string; message: string } | null;
}

export interface PollJobResult<Result> {
  status: "done" | "partial";
  result: Result;
}

interface PollerOptions<Result> {
  jobId: string;
  fetchStatus: (jobId: string, signal: AbortSignal) => Promise<PollJobStatus>;
  fetchResult: (
    resultUrl: string,
    signal: AbortSignal,
  ) => Promise<PollJobResult<Result>>;
  onStatus: (status: PollStatus) => void;
  onComplete: (result: Result, status: "done" | "partial") => void;
  onError: (message: string) => void;
  baseDelayMs?: number;
  maxDelayMs?: number;
  maxConsecutiveFailures?: number;
  schedule?: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>;
  cancelSchedule?: (timer: ReturnType<typeof setTimeout>) => void;
}

/**
 * Start one-at-a-time recursive polling. A new request is scheduled only after
 * the previous status/result request settles, so slow responses never overlap.
 */
export function startReconstructionPolling<Result>({
  jobId,
  fetchStatus,
  fetchResult,
  onStatus,
  onComplete,
  onError,
  baseDelayMs = 1_500,
  maxDelayMs = 12_000,
  maxConsecutiveFailures = 5,
  schedule = setTimeout,
  cancelSchedule = clearTimeout,
}: PollerOptions<Result>): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let activeController: AbortController | null = null;
  let consecutiveFailures = 0;

  const stop = () => {
    stopped = true;
    activeController?.abort();
    activeController = null;
    if (timer !== null) cancelSchedule(timer);
    timer = null;
  };

  const scheduleNext = (delayMs: number) => {
    if (stopped) return;
    timer = schedule(() => {
      timer = null;
      void poll();
    }, delayMs);
  };

  const poll = async (): Promise<void> => {
    if (stopped) return;
    const controller = new AbortController();
    activeController = controller;
    try {
      const status = await fetchStatus(jobId, controller.signal);
      if (stopped) return;
      onStatus(status.status);

      if (status.status === "failed") {
        stop();
        onError(status.error?.message || "Reconstruction failed");
        return;
      }

      if (status.status === "done" || status.status === "partial") {
        if (!status.result_url) {
          throw new Error("Completed reconstruction did not provide a result URL");
        }
        const result = await fetchResult(status.result_url, controller.signal);
        if (stopped) return;
        if (result.status !== status.status) {
          throw new Error("Reconstruction status changed while loading its result");
        }
        stop();
        onComplete(result.result, result.status);
        return;
      }

      consecutiveFailures = 0;
      scheduleNext(baseDelayMs);
    } catch (error) {
      if (stopped || controller.signal.aborted) return;
      consecutiveFailures += 1;
      if (consecutiveFailures > maxConsecutiveFailures) {
        stop();
        onError(
          error instanceof Error
            ? error.message
            : "Could not load reconstruction progress",
        );
        return;
      }
      const delay = Math.min(
        baseDelayMs * 2 ** (consecutiveFailures - 1),
        maxDelayMs,
      );
      scheduleNext(delay);
    } finally {
      if (activeController === controller) activeController = null;
    }
  };

  void poll();
  return stop;
}
