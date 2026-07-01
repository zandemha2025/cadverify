"use client";

import { useEffect, useRef, useState } from "react";
import { getJobStatus } from "@/lib/api";
import { Spinner } from "@/components/ui/spinner";
import { Progress } from "@/components/ui/progress";

interface ReconstructionProgressProps {
  jobId: string;
  estimatedSeconds: number;
  onComplete: (result: Record<string, unknown>) => void;
  onError: (error: string) => void;
}

const POLL_INTERVAL_MS = 3_000;

const STATUS_LABELS: Record<string, string> = {
  queued: "Preparing images...",
  running: "Building 3D model...",
  done: "Reconstruction complete!",
  failed: "Reconstruction failed",
};

export default function ReconstructionProgress({
  jobId,
  estimatedSeconds,
  onComplete,
  onError,
}: ReconstructionProgressProps) {
  const [status, setStatus] = useState<string>("queued");
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Elapsed seconds timer
    timerRef.current = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1_000);

    // Poll job status
    let cancelled = false;

    const poll = async () => {
      try {
        const data = await getJobStatus(jobId);
        if (cancelled) return;
        setStatus(data.status);

        if (data.status === "done") {
          onComplete(data.result ?? {});
          cleanup();
        } else if (data.status === "failed") {
          onError(data.error ?? "Reconstruction failed");
          cleanup();
        }
      } catch {
        // Polling error -- retry on next interval
      }
    };

    // Initial poll immediately
    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    function cleanup() {
      cancelled = true;
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
    }

    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
