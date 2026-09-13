"use client";

import type { RateLimits } from "@/lib/api";
import { Progress } from "@/components/ui/progress";
import { usageTone } from "@/lib/status";

export interface TrialUsage {
  plan: string;
  unlimited: boolean;
  used: number | null;
  cap: number | null;
  remaining: number | null;
}

interface Props {
  rateLimits?: RateLimits;
  usage?: TrialUsage;
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
          {used} of {total} used
        </span>
      </div>
      <Progress value={pct} tone={usageTone(used, total)} className="h-2" />
    </div>
  );
}

export default function QuotaDisplay({ rateLimits, usage }: Props) {
  // The product trial cap is the honest quota; the rate-limit throttle is
  // only a burst control and never presented as the allowance.
  if (usage) {
    if (usage.unlimited) {
      return (
        <p className="text-sm text-muted-foreground">
          Pilot plan - unlimited checks.
        </p>
      );
    }
    if (usage.used != null && usage.cap != null) {
      const exhausted = usage.remaining === 0;
      return (
        <div className="space-y-3">
          <QuotaBar
            used={usage.used}
            total={usage.cap}
            label={`${usage.used} of ${usage.cap} trial checks used`}
          />
          {exhausted && (
            <p className="text-sm text-muted-foreground">
              You&apos;ve used your {usage.cap} trial checks.{" "}
              <a
                className="underline"
                href="mailto:nazeemahmed2023@gmail.com"
              >
                Talk to the ProofShape team
              </a>{" "}
              to keep going.
            </p>
          )}
        </div>
      );
    }
  }

  if (!rateLimits) {
    return (
      <p className="text-sm text-muted-foreground">Quota data unavailable</p>
    );
  }

  const used = rateLimits.limit - rateLimits.remaining;
  const resetInSec = rateLimits.reset - Math.floor(Date.now() / 1000);

  return (
    <div className="space-y-3">
      <QuotaBar used={used} total={rateLimits.limit} label="Rate limit usage" />
      {resetInSec > 0 && (
        <p className="text-xs text-muted-foreground">
          Resets in {Math.ceil(resetInSec / 60)} min
        </p>
      )}
    </div>
  );
}
