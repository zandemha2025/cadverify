"use client";

/**
 * RoutingCard + DfmMatrix — "is it made the right way" (Mfg lens). The routing
 * card foregrounds the engine's REASONING paragraph (the trust object for this
 * persona) over the MEASURED drivers that decided it. The DFM matrix is
 * actionable, not red flags: each blocker states the measured value and links to
 * geometry. costed=false rows are feasibility-only — honestly de-weighted.
 */

import * as React from "react";
import { ArrowRight, Info, MousePointerClick } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CostRouting, CostFeasibility } from "@/lib/api";
import { procLabel } from "@/lib/status";
import { StatusBadge } from "@/components/ui/status-badge";
import { ProvenanceDot } from "./provenance";

function fmtDriver(v: number | boolean): string {
  if (typeof v === "boolean") return v ? "yes" : "no";
  return Math.abs(v) >= 100 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v.toFixed(2);
}

// the routing drivers worth surfacing, in reading order
const DRIVER_KEYS = ["rotational", "sheet_like", "planar_aspect", "nominal_wall_mm", "sheet_gauge_mm", "bend_count"] as const;

export function RoutingCard({
  routing,
  className,
}: {
  routing: CostRouting;
  className?: string;
}) {
  return (
    <div className={cn("rounded-[var(--radius-lg)] border border-border bg-card", className)}>
      <div className="border-b border-border bg-accent-subtle/60 px-4 py-3">
        <span className="cv-eyebrow">Geometric routing</span>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <ArrowRight className="size-5 text-accent-text" aria-hidden />
          <h3 className="text-display font-semibold leading-7 text-foreground">
            {procLabel(routing.recommended_process)}
          </h3>
          <span className="num rounded-sm border border-border bg-card px-1.5 py-0.5 text-micro text-muted-foreground">
            archetype: {routing.archetype}
          </span>
          <span className="num rounded-sm border border-border bg-card px-1.5 py-0.5 text-micro text-muted-foreground">
            confidence {routing.confidence.toFixed(2)}
          </span>
        </div>
      </div>

      <div className="space-y-3 px-4 py-3.5">
        <p className="border-l-2 border-accent-subtle-border pl-3 text-sm leading-relaxed text-foreground">
          {routing.reasoning}
        </p>

        {routing.alternatives.length > 0 && (
          <p className="text-xs text-muted-foreground">
            alternatives:{" "}
            {routing.alternatives.map((a, i) => (
              <span key={a} className="text-foreground">
                {i > 0 && " · "}
                {procLabel(a)}
              </span>
            ))}
          </p>
        )}

        <div className="space-y-1.5">
          <span className="cv-eyebrow">Decided by</span>
          <div className="flex flex-wrap gap-1.5">
            {DRIVER_KEYS.filter((k) => k in routing.drivers).map((k) => (
              <span
                key={k}
                className="inline-flex items-center gap-1.5 rounded-sm border border-prov-measured-border bg-prov-measured-bg px-2 py-1 text-xs"
              >
                <ProvenanceDot provenance="MEASURED" />
                <span className="text-foreground">{k}</span>
                <span className="num font-medium text-prov-measured">{fmtDriver(routing.drivers[k])}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function DfmMatrix({
  feasibility,
  blockers,
  costPick,
  onHighlight,
  className,
}: {
  feasibility: CostFeasibility[];
  /** process → human blocker string (from estimates[].dfm_blockers) */
  blockers?: Record<string, string>;
  /** the cost-cheapest process, annotated when it differs from the geometry pick */
  costPick?: string;
  onHighlight?: (process: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)}>
      <span className="cv-eyebrow">DFM matrix · all processes</span>
      <div className="overflow-hidden rounded-[var(--radius)] border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted">
            <tr className="border-b border-border text-left">
              <th className="px-3 py-2 text-micro font-semibold uppercase tracking-wide text-muted-foreground">Process</th>
              <th className="px-3 py-2 text-micro font-semibold uppercase tracking-wide text-muted-foreground">Verdict</th>
              <th className="px-3 py-2 text-right text-micro font-semibold uppercase tracking-wide text-muted-foreground">Score</th>
              <th className="px-3 py-2 text-micro font-semibold uppercase tracking-wide text-muted-foreground">Blocker</th>
            </tr>
          </thead>
          <tbody>
            {feasibility.map((f) => {
              const blocker = blockers?.[f.process];
              return (
                <tr
                  key={f.process}
                  className={cn(
                    "border-b border-border last:border-0",
                    !f.costed && "opacity-55"
                  )}
                >
                  <td className="px-3 py-2 align-top">
                    <span className="text-foreground">{procLabel(f.process)}</span>
                    {f.process === costPick && (
                      <span className="ml-1.5 text-micro text-prov-shop">cost pick</span>
                    )}
                    {!f.costed && (
                      <span className="ml-1.5 text-micro text-muted-foreground">feasibility-only</span>
                    )}
                  </td>
                  <td className="px-3 py-2 align-top">
                    <StatusBadge verdict={f.verdict} size="sm" />
                  </td>
                  <td className="num px-3 py-2 text-right align-top text-muted-foreground">
                    {f.score.toFixed(1)}
                  </td>
                  <td className="px-3 py-2 align-top">
                    {blocker ? (
                      <button
                        type="button"
                        onClick={() => onHighlight?.(f.process)}
                        className="group inline-flex items-start gap-1.5 text-left text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <span>{blocker}</span>
                        {onHighlight && (
                          <MousePointerClick className="mt-0.5 size-3.5 shrink-0 text-accent-text opacity-0 transition-opacity group-hover:opacity-100" />
                        )}
                      </button>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {costPick && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden />
          Cost-cheapest make differs from the geometry-recommended route — pick on intent, not the
          marginal dollar. Both are costed.
        </p>
      )}
    </div>
  );
}
