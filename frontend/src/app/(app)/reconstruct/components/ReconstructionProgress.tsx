"use client";

import { useEffect, useRef, useState } from "react";
import {
  getJobResult,
  getJobStatus,
  type JobStatusValue,
  type ReconstructionJobResult,
} from "@/lib/api";
import { Spinner } from "@/components/ui/spinner";
import { Progress } from "@/components/ui/progress";
import { startReconstructionPolling } from "../reconstruction-poller";

interface ReconstructionProgressProps {
  jobId: string;
  estimatedSeconds: number;
  onComplete: (
    result: ReconstructionJobResult,
    status: "done" | "partial",
  ) => void;
  onError: (error: string) => void;
}

const STATUS_LABELS: Record<string, string> = {
  queued: "Preparing images...",
  running: "Building 3D model...",
  done: "Reconstruction complete!",
  partial: "Reconstruction completed with limited output",
  failed: "Reconstruction failed",
};

export default function ReconstructionProgress({
  jobId,
  estimatedSeconds,
  onComplete,
  onError,
}: ReconstructionProgressProps) {
  const [status, setStatus] = useState<JobStatusValue>("queued");
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const completeRef = useRef(onComplete);
  const errorRef = useRef(onError);

  useEffect(() => {
    completeRef.current = onComplete;
    errorRef.current = onError;
  }, [onComplete, onError]);

  useEffect(() => {
    // Elapsed seconds timer
    timerRef.current = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1_000);

    const stopPolling = startReconstructionPolling<ReconstructionJobResult>({
      jobId,
      fetchStatus: getJobStatus,
      fetchResult: getJobResult,
      onStatus: setStatus,
      onComplete: (result, terminalStatus) =>
        completeRef.current(result, terminalStatus),
      onError: (message) => errorRef.current(message),
    });

    return () => {
      stopPolling();
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [jobId]);

  const label = STATUS_LABELS[status] ?? "Processing...";

  return (
    <div className="flex flex-col items-center gap-6 py-12">
      <Spinner />

      {/* Status text */}
      <div className="text-center" aria-live="polite">
        <p className="text-base font-medium text-foreground">{label}</p>
        <p className="num mt-1 text-sm text-muted-foreground">
          {elapsed}s elapsed
          {estimatedSeconds > 0 && (
            <span className="ml-2 text-muted-foreground/70">
              (estimated ~{estimatedSeconds}s)
            </span>
          )}
        </p>
      </div>

      {/* Progress bar (estimated) */}
      <Progress
        value={Math.min((elapsed / Math.max(estimatedSeconds, 1)) * 100, 95)}
        className="h-2 w-full max-w-xs"
      />

      <p className="num text-xs text-muted-foreground">
        Job ID: {jobId.slice(0, 12)}
      </p>
    </div>
  );
}
