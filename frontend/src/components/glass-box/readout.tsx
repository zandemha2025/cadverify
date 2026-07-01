"use client";

/**
 * NumberReadout — the instrument-grade hero metric. The answer (unit cost, lead
 * time, quantity) is a big tabular-mono "readout" with a tick-prefixed eyebrow
 * and, optionally, its confidence band right beneath — so even the hero number
 * is shown with its bounds, never fake-exact.
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import type { CostConfidence } from "@/lib/api";
import { ConfidenceTrack, ConfidenceLabel } from "./confidence";

export function NumberReadout({
  label,
  value,
  unit,
  accent = false,
  size = "lg",
  confidence,
  hint,
  className,
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  accent?: boolean;
  size?: "md" | "lg";
  confidence?: CostConfidence;
  hint?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <span className="cv-eyebrow">{label}</span>
      <p className="mt-1.5 flex items-baseline gap-1">
        <span
          className={cn(
            "readout font-semibold leading-none",
            size === "lg" ? "text-readout" : "text-display",
            accent ? "text-accent-text" : "text-foreground"
          )}
        >
          {value}
        </span>
        {unit && <span className="num text-sm text-muted-foreground">{unit}</span>}
      </p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      {confidence && (
        <div className="mt-3 space-y-1.5">
          <ConfidenceTrack confidence={confidence} />
          <ConfidenceLabel confidence={confidence} />
        </div>
      )}
    </div>
  );
}
