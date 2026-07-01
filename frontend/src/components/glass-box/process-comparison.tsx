"use client";

/**
 * ProcessComparison — the decision board (Sourcing lens). The one surface where
 * multiple answers coexist on equal footing: process × shop, every cell a BANDED
 * cost (a number with its bounds is more wieldable in a negotiation than a
 * fake-exact point), with the per-row Δ% and a drill into each cell's glass box.
 * Confidence is leverage, never a fabricated validated figure.
 *
 * Multi-shop-in-one-call is a build gap; this component takes the resolved cells
 * so it composes from two single-shop reports today.
 */

import * as React from "react";
import { ChevronRight, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { procLabel } from "@/lib/status";

export interface CompareCell {
  unitCost: number;
  halfWidthPct: number;
  dfmReady: boolean;
  /** cost shown is "if redesigned", not a current quote */
  redesign?: boolean;
}

export interface CompareRow {
  process: string;
  a: CompareCell;
  b: CompareCell;
}

const USD = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function Cell({
  cell,
  onDrill,
}: {
  cell: CompareCell;
  onDrill?: () => void;
}) {
  return (
    <td className="px-3 py-2.5 align-top">
      <div className="flex items-baseline justify-end gap-2">
        <span className="num text-sm font-semibold text-foreground">{USD(cell.unitCost)}</span>
        <span className="num text-micro text-muted-foreground">±{Math.round(cell.halfWidthPct)}%</span>
        {onDrill && (
          <button
            type="button"
            onClick={onDrill}
            aria-label="Open glass box for this cell"
            className="rounded-sm p-0.5 text-muted-foreground hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronRight className="size-3.5" />
          </button>
        )}
      </div>
      {cell.redesign && (
        <p className="mt-0.5 text-right text-micro text-warn">⚠ if redesigned</p>
      )}
    </td>
  );
}

export function ProcessComparison({
  shopA,
  shopB,
  rows,
  qty,
  lever,
  onDrill,
  className,
}: {
  shopA: string;
  shopB: string;
  rows: CompareRow[];
  qty: number;
  /** the most-divergent driver — the negotiation lever (driver-level, not a total) */
  lever?: React.ReactNode;
  onDrill?: (process: string, shop: "a" | "b") => void;
  className?: string;
}) {
  return (
    <div className={cn("space-y-3", className)}>
      <div className="overflow-hidden rounded-[var(--radius-lg)] border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted">
            <tr className="border-b border-border">
              <th className="px-3 py-2 text-left text-micro font-semibold uppercase tracking-wide text-muted-foreground">
                Process · qty {qty.toLocaleString()}
              </th>
              <th className="px-3 py-2 text-right text-micro font-semibold uppercase tracking-wide text-muted-foreground">
                {shopA}
              </th>
              <th className="px-3 py-2 text-right text-micro font-semibold uppercase tracking-wide text-muted-foreground">
                {shopB}
              </th>
              <th className="w-16 px-3 py-2 text-right text-micro font-semibold uppercase tracking-wide text-muted-foreground">
                Δ
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const delta = (r.b.unitCost - r.a.unitCost) / r.a.unitCost;
              const deltaPct = Math.round(delta * 100);
              return (
                <tr key={r.process} className="border-b border-border last:border-0 hover:bg-muted/50">
                  <td className="px-3 py-2.5 align-top">
                    <span className="text-foreground">{procLabel(r.process)}</span>
                    {!r.a.dfmReady && !r.a.redesign && (
                      <span className="ml-2 text-micro text-warn">not DFM-ready</span>
                    )}
                  </td>
                  <Cell cell={r.a} onDrill={onDrill ? () => onDrill(r.process, "a") : undefined} />
                  <Cell cell={r.b} onDrill={onDrill ? () => onDrill(r.process, "b") : undefined} />
                  <td className="px-3 py-2.5 text-right align-top">
                    <span
                      className={cn(
                        "num text-sm font-medium",
                        deltaPct < 0 ? "text-prov-shop" : deltaPct > 0 ? "text-fail" : "text-muted-foreground"
                      )}
                    >
                      {deltaPct > 0 ? "+" : ""}
                      {deltaPct}%
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {lever && (
        <div className="flex items-start gap-2 rounded-[var(--radius)] border border-prov-shop-border bg-prov-shop-bg px-3 py-2.5 text-xs text-foreground">
          <ArrowRight className="mt-0.5 size-3.5 shrink-0 text-prov-shop" aria-hidden />
          <div>
            <span className="font-semibold text-prov-shop">Negotiation lever</span> · {lever}
          </div>
        </div>
      )}
    </div>
  );
}
