"use client";

import type { RateLimits } from "@/lib/api";

interface Props {
  rateLimits?: RateLimits;
}

function usageColor(pct: number): string {
  if (pct >= 80) return "bg-red-500";
  if (pct >= 50) return "bg-yellow-500";
  return "bg-green-500";
}

function ProgressBar({ used, total, label }: { used: number; total: number; label: string }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-gray-600">{label}</span>
        <span className="tabular-nums text-gray-500">
          {used} / {total} used ({pct}%)
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className={`h-full rounded-full transition-all ${usageColor(pct)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function QuotaDisplay({ rateLimits }: Props) {
  if (!rateLimits) {
    return (
      <p className="text-sm text-gray-400">Quota data unavailable</p>
    );
  }

  const used = rateLimits.limit - rateLimits.remaining;

  return (
    <div className="space-y-3">
      <ProgressBar
        used={used}
        total={rateLimits.limit}
        label="RateLimit usage"
      />
      {rateLimits.reset > 0 && (
        <p className="text-xs text-gray-400">
          Resets in {Math.ceil(rateLimits.reset / 60)} min
        </p>
      )}
    </div>
  );
}
