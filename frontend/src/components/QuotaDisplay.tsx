"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import type { RateLimits } from "@/lib/api";
import { Progress } from "@/components/ui/progress";
import { usageTone } from "@/lib/status";
import { ManageBillingButton, UpgradeButton } from "@/components/billing/upgrade-button";

export interface TrialUsage {
  plan: string;
  tier?: string;
  unlimited: boolean;
  used: number | null;
  cap: number | null;
  remaining: number | null;
  reserved?: number;
  window_days?: number;
  resets_at?: string | null;
  phone_verification_required?: boolean;
}

function resetDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: "UTC" });
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

export default function QuotaDisplay(props: Props) {
  const usage = props.usage;
  return <div className="space-y-3">
    <QuotaUsage {...props} />
    {usage && !usage.unlimited && (usage.plan === "pro" ? <div className="text-sm text-muted-foreground">
      <ManageBillingButton className="font-medium text-primary underline" />{" "}
      to change or cancel Pro.
    </div> : <div className="text-sm text-muted-foreground">
      <UpgradeButton className="font-medium text-primary underline" />{" "}
      for monthly checks. Your saved results stay available.
    </div>)}
  </div>;
}

function QuotaUsage({ rateLimits, usage }: Props) {
  // The product trial cap is the honest quota; the rate-limit throttle is
  // only a burst control and never presented as the allowance.
  if (usage) {
    if (usage.unlimited) {
      return (
        <p className="text-sm text-muted-foreground">
          Approved access — unlimited checks.
        </p>
      );
    }
    if (usage.used != null && usage.cap != null) {
      const exhausted = usage.remaining === 0;
      const pro = usage.plan === "pro";
      const resets = resetDate(usage.resets_at);
      return (
        <div className="space-y-3">
          <QuotaBar
            used={usage.used}
            total={usage.cap}
            label={pro ? "Pro checks this month" : "Free checks"}
          />
          {!!usage.reserved && <p className="text-sm text-muted-foreground">{usage.reserved} checks in progress. Unfinished previews release their reserved slots after an hour.</p>}
          {pro && resets && <p className="text-sm text-muted-foreground">Resets on {resets}.</p>}
          {exhausted && !usage.reserved && <p className="text-sm text-muted-foreground">{pro ? `You've used this month's ${usage.cap} Pro checks.` : `You've used your ${usage.cap} free checks.`}</p>}
          {!!usage.window_days && <p className="text-sm text-muted-foreground">Checks are counted over a rolling {usage.window_days}-day window.</p>}
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


/** The allowance stays visible wherever the user starts a new operation. */
export function TrialAllowance() {
  const pathname = usePathname();
  const [usage, setUsage] = useState<TrialUsage | null>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      fetch("/api/auth/me/usage")
        .then((response) => response.ok ? response.json() : null)
        .then((value) => { if (active) { setUsage(value); setLoaded(true); } })
        .catch(() => { if (active) { setUsage(null); setLoaded(true); } });
    };
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener("proofshape:usage-changed", refresh);
    return () => {
      active = false;
      window.removeEventListener("focus", refresh);
      window.removeEventListener("proofshape:usage-changed", refresh);
    };
  }, [pathname]);
  if (usage?.unlimited) return null;
  const pro = usage?.plan === "pro";
  return <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border bg-background px-4 py-2 text-xs" role="status">
    <span>{usage ? `${usage.remaining} of ${usage.cap} ${pro ? "Pro checks left this month" : "free checks left"}` : loaded ? "Allowance temporarily unavailable" : "Checking your allowance…"}</span>
    {usage && (pro
      ? <ManageBillingButton className="font-medium text-primary underline" />
      : <UpgradeButton className="font-medium text-primary underline" />)}
  </div>;
}
