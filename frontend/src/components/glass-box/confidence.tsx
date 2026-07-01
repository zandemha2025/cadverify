"use client";

/**
 * Confidence — the decision, not the dollar. A cost is never a fake-exact point;
 * it is a point inside a band. The band is drawn with the measurement-tick motif
 * (low · point · high). The honesty rail is structural, not a footnote:
 *   • method "assumption-band"   → the fill is HATCHED — it literally looks
 *     provisional ("not yet validated, no ground truth").
 *   • method "measured-residual" → the fill is SOLID, with the validated count.
 * We never print a fabricated ±X% accuracy figure; we render the engine's own
 * `label` / `validated` / `n_samples` verbatim.
 */

import * as React from "react";
import { CircleDashed, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CostConfidence } from "@/lib/api";

const USD0 = (n: number) =>
  `$${n.toLocaleString("en-US", { maximumFractionDigits: n < 100 ? 2 : 0 })}`;

function pointFraction(c: CostConfidence): number {
  const span = c.high_usd - c.low_usd;
  if (span <= 0) return 0.5;
  return Math.min(1, Math.max(0, (c.point_usd - c.low_usd) / span));
}

/** The interval track: low ── point ── high, hatched when not yet validated. */
export function ConfidenceTrack({
  confidence,
  className,
}: {
  confidence: CostConfidence;
  className?: string;
}) {
  const c = confidence;
  const pf = pointFraction(c);
  return (
    <div className={cn("w-full", className)}>
      <div className="relative h-2 w-full rounded-full bg-band-track">
        {/* the band fill — solid if validated, hatched (provisional) if not */}
        <div
          className={cn(
            "absolute inset-y-0 left-0 right-0 rounded-full",
            c.validated ? "bg-band-fill/80" : "bg-band-fill/20 cv-hatch"
          )}
        />
        {/* the point estimate marker (a measurement tick) */}
        <span
          className="absolute top-1/2 h-3.5 w-[2px] -translate-x-1/2 -translate-y-1/2 rounded-[1px] bg-band-fill"
          style={{ left: `${pf * 100}%` }}
          aria-hidden
        />
      </div>
      <div className="num mt-1 flex justify-between text-micro text-muted-foreground">
        <span>{USD0(c.low_usd)}</span>
        <span className="font-semibold text-foreground">{USD0(c.point_usd)}</span>
        <span>{USD0(c.high_usd)}</span>
      </div>
    </div>
  );
}

/** The honesty label — renders the engine's `validated` / `label` verbatim. */
export function ConfidenceLabel({
  confidence,
  className,
}: {
  confidence: CostConfidence;
  className?: string;
}) {
  const c = confidence;
  if (c.validated) {
    return (
      <p className={cn("flex items-start gap-1.5 text-xs text-prov-shop", className)}>
        <ShieldCheck className="mt-px size-3.5 shrink-0" aria-hidden />
        <span>
          Validated on {c.n_samples} of your part
          {c.n_samples === 1 ? "" : "s"} · {c.basis}
        </span>
      </p>
    );
  }
  return (
    <p className={cn("flex items-start gap-1.5 text-xs text-muted-foreground", className)}>
      <CircleDashed className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>{c.basis}</span>
    </p>
  );
}

/** Full confidence block: level header + band + honesty label. */
export function ConfidenceInterval({
  confidence,
  className,
}: {
  confidence: CostConfidence;
  className?: string;
}) {
  const c = confidence;
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="cv-eyebrow">Confidence · {Math.round(c.level * 100)}%</span>
        <span className="num text-xs text-muted-foreground">
          {USD0(c.low_usd)} – {USD0(c.high_usd)} / unit
          <span className="ml-1 opacity-70">(±{Math.round(c.half_width_pct)}%)</span>
        </span>
      </div>
      <ConfidenceTrack confidence={c} />
      <ConfidenceLabel confidence={c} />
    </div>
  );
}

/** Compact inline pill: "±40% · not yet validated" for dense tables / cells. */
export function ConfidenceChip({
  confidence,
  className,
}: {
  confidence: CostConfidence;
  className?: string;
}) {
  const c = confidence;
  const Icon = c.validated ? ShieldCheck : CircleDashed;
  return (
    <span
      title={c.basis}
      className={cn(
        "num inline-flex items-center gap-1 rounded-xs border px-1.5 py-0.5 text-micro font-medium",
        c.validated
          ? "border-prov-shop-border bg-prov-shop-bg text-prov-shop"
          : "border-border bg-muted text-muted-foreground",
        className
      )}
    >
      <Icon className="size-3" aria-hidden />
      ±{Math.round(c.half_width_pct)}%
      <span className="font-normal opacity-80">
        {c.validated ? `validated · n=${c.n_samples}` : "not yet validated"}
      </span>
    </span>
  );
}
