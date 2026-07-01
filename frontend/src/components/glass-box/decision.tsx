"use client";

/**
 * DecisionHeadline + RedesignBanner — the decision, not the dollar. The hero is
 * the make-vs-buy verdict + the quantity crossover, never a fake-exact price.
 * RedesignBanner is the non-negotiable honesty: when the tooling route currently
 * FAILS DFM, the crossover is real but conditional — say "if redesigned," and
 * never assert a process the part currently fails.
 */

import * as React from "react";
import { TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/ui/status-badge";

export function DecisionHeadline({
  title,
  dfmReady,
  sentence,
  className,
}: {
  title: string;
  dfmReady: boolean;
  sentence: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-t-[var(--radius-lg)] border-b border-accent-subtle-border bg-accent-subtle/70 px-5 py-4",
        className
      )}
    >
      <span className="cv-eyebrow">Recommended decision · make-vs-buy</span>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <h2 className="text-display font-semibold leading-8 text-foreground">{title}</h2>
        <StatusBadge
          tone={dfmReady ? "pass" : "warn"}
          label={dfmReady ? "DFM-ready" : "needs redesign"}
        />
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{sentence}</p>
    </div>
  );
}

export function RedesignBanner({
  process,
  blocker,
  onSeeRouting,
  className,
}: {
  process: string;
  blocker?: string;
  onSeeRouting?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-[var(--radius)] border border-warn-border bg-warn-bg px-3 py-2.5 text-sm",
        className
      )}
    >
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <p className="text-foreground">
        <span className="font-semibold text-warn">{process} requires design-for-process</span>
        {blocker ? ` (${blocker})` : ""} — the cost shown is{" "}
        <span className="font-semibold">“if redesigned,”</span> not a current quote.
        {onSeeRouting && (
          <>
            {" "}
            <button
              type="button"
              onClick={onSeeRouting}
              className="font-medium text-accent-text underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              See Routing &amp; DFM
            </button>
          </>
        )}
      </p>
    </div>
  );
}
