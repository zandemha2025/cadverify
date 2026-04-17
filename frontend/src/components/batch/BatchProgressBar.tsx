"use client";

import { useEffect, useRef, useState } from "react";
import { getBatchProgress, type BatchProgress } from "@/lib/api/batch";

const POLL_INTERVAL_MS = 5_000;

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  extracting: "bg-yellow-100 text-yellow-800",
  processing: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-200 text-gray-600",
};

interface Props {
  batchId: string;
  /** Called whenever progress is refreshed. */
  onProgressUpdate?: (p: BatchProgress) => void;
}

export default function BatchProgressBar({ batchId, onProgressUpdate }: Props) {
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const p = await getBatchProgress(batchId);
        if (cancelled) return;
        setProgress(p);
        onProgressUpdate?.(p);

        if (startTimeRef.current === null && p.started_at) {
          startTimeRef.current = new Date(p.started_at).getTime();
        }

        if (TERMINAL_STATUSES.has(p.status) && intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load progress");
        }
      }
    };

    // Initial fetch
    poll();

    // Start polling
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [batchId, onProgressUpdate]);

  if (error) {
    return <div className="rounded-md bg-red-50 p-4 text-sm text-red-700">{error}</div>;
  }

  if (!progress) {
    return <div className="animate-pulse rounded-md bg-gray-100 p-4 text-sm text-gray-500">Loading progress...</div>;
  }

  const { total_items, completed_items, failed_items, pending_items, status, concurrency_limit } = progress;
  const processed = completed_items + failed_items;
  const pct = total_items > 0 ? Math.round((processed / total_items) * 100) : 0;

  // Estimated time remaining
  let etaLabel = "";
  if (startTimeRef.current && !TERMINAL_STATUSES.has(status) && processed > 0) {
    const elapsed = (Date.now() - startTimeRef.current) / 1000;
    const rate = processed / elapsed;
    const remaining = total_items - processed;
    if (rate > 0) {
      const etaSec = Math.round(remaining / rate);
      if (etaSec < 60) {
        etaLabel = `~${etaSec}s remaining`;
      } else {
        etaLabel = `~${Math.round(etaSec / 60)}m remaining`;
      }
    }
  }

  // Bar color
  const barColor =
    status === "failed" || status === "cancelled"
      ? "bg-red-500"
      : status === "completed"
        ? "bg-green-500"
        : "bg-blue-500";

  return (
    <div className="space-y-3 rounded-md border p-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[status] || "bg-gray-100 text-gray-700"}`}
          >
            {status}
          </span>
          <span className="text-sm text-gray-600">
            Processing {concurrency_limit} items in parallel
          </span>
        </div>
        {etaLabel && (
          <span className="text-xs text-gray-500">{etaLabel}</span>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Counters */}
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-gray-700">
          {processed} / {total_items} ({pct}%)
        </span>
        <div className="flex gap-3 text-xs text-gray-500">
          {failed_items > 0 && (
            <span className="text-red-600">{failed_items} failed</span>
          )}
          {pending_items > 0 && !TERMINAL_STATUSES.has(status) && (
            <span>{pending_items} pending</span>
          )}
        </div>
      </div>
    </div>
  );
}
