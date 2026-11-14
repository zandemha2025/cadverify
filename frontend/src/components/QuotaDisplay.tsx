"use client";

import type { RateLimits } from "@/lib/api";
import { Progress } from "@/components/ui/progress";
import { usageTone } from "@/lib/status";
import { formatRateLimitReset } from "@/lib/history-format";

interface Props {
  rateLimits?: RateLimits;
}

function QuotaBar({
  used,
  total,
  label,
}: {
  used: number;
  total: number;
  label: string;
}) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="num text-muted-foreground">
          {used} / {total} used ({pct}%)
        </span>
      </div>
      <Progress value={pct} tone={usageTone(used, total)} className="h-2" />
    </div>
  );
}

export default function QuotaDisplay({ rateLimits }: Props) {
  if (!rateLimits) {
    return (
      <p className="text-sm text-muted-foreground">Quota data unavailable</p>
    );
  }

  const used = rateLimits.limit - rateLimits.remaining;
  const resetLabel = formatRateLimitReset(rateLimits.reset);

  return (
    <div className="space-y-3">
      <QuotaBar used={used} total={rateLimits.limit} label="Rate limit usage" />
      {resetLabel && (
        <p className="text-xs text-muted-foreground">{resetLabel}</p>
      )}
    </div>
  );
}
