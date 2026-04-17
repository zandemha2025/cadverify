"use client";

import { useEffect, useRef, useState } from "react";
import { getJobStatus } from "@/lib/api";

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
    <div className="flex flex-col items-center space-y-6 py-12">
      {/* Spinner */}
      <div className="h-12 w-12 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600" />

      {/* Status text */}
      <div className="text-center" aria-live="polite">
        <p className="text-lg font-medium text-gray-800">{label}</p>
        <p className="mt-1 text-sm text-gray-500">
          {elapsed}s elapsed
          {estimatedSeconds > 0 && (
            <span className="ml-2 text-gray-400">
              (estimated ~{estimatedSeconds}s)
            </span>
          )}
        </p>
      </div>

      {/* Progress bar (estimated) */}
      <div className="w-full max-w-xs">
        <div className="h-2 overflow-hidden rounded-full bg-gray-200">
          <div
            className="h-full rounded-full bg-blue-600 transition-all duration-1000"
            style={{
              width: `${Math.min((elapsed / Math.max(estimatedSeconds, 1)) * 100, 95)}%`,
            }}
          />
        </div>
      </div>

      <p className="text-xs text-gray-400">
        Job ID: <span className="font-mono">{jobId.slice(0, 12)}</span>
      </p>
    </div>
  );
}
