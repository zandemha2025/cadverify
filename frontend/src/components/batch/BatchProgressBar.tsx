"use client";

import { useEffect, useRef, useState } from "react";
import { getBatchProgress, type BatchProgress } from "@/lib/api/batch";
import { Card } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { Progress } from "@/components/ui/progress";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { batchStatusTone } from "@/lib/status";

const POLL_INTERVAL_MS = 5_000;

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

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

    poll();
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
    return <ErrorState title="Could not load progress" message={error} />;
  }

  if (!progress) {
    return (
      <Card className="p-4">
        <Skeleton className="h-16 w-full" />
      </Card>
    );
  }

  const {
    total_items,
    completed_items,
    failed_items,
    pending_items,
    status,
    concurrency_limit,
  } = progress;
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
      etaLabel =
        etaSec < 60 ? `~${etaSec}s remaining` : `~${Math.round(etaSec / 60)}m remaining`;
    }
  }

  return (
    <Card className="space-y-3 p-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusBadge status={status} size="sm" />
          <span className="text-sm text-muted-foreground">
            Processing {concurrency_limit} items in parallel
          </span>
        </div>
        {etaLabel && (
          <span className="num text-xs text-muted-foreground">{etaLabel}</span>
        )}
      </div>

      {/* Progress bar */}
      <Progress value={pct} tone={batchStatusTone(status)} className="h-3" />

      {/* Counters */}
      <div className="flex items-center justify-between text-sm">
        <span className="num font-medium text-foreground">
          {processed} / {total_items} ({pct}%)
        </span>
        <div className="num flex gap-3 text-xs text-muted-foreground">
          {failed_items > 0 && (
            <span className="text-fail">{failed_items} failed</span>
          )}
          {pending_items > 0 && !TERMINAL_STATUSES.has(status) && (
            <span>{pending_items} pending</span>
          )}
        </div>
      </div>
    </Card>
  );
}
