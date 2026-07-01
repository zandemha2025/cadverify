"use client";

/**
 * Compare lens — where Sourcing lands: the one surface where multiple answers
 * coexist on equal footing. Built from the engine's REAL per-process estimates:
 * each process priced at the two costed quantities (the volume break — the
 * make-vs-buy crossover made tabular), every cell a banded real number, each
 * drillable into its glass box. The crossover chart is the centrepiece.
 *
 * Shop-A-vs-shop-B in ONE board (Midwest vs Shenzhen) needs multi-shop-in-one-
 * call — a build gap; the engine binds a shop per call, so a true A/B composes
 * from two real reports. Until then this compares volumes on one calibration.
 */

import * as React from "react";
import { Scale, Info } from "lucide-react";
import type { CostReport } from "@/lib/api";
import { procLabel } from "@/lib/status";
import { deriveBreakeven } from "@/lib/breakeven";
import { buildCompareRows, costedQuantities } from "@/lib/cost-views";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ProcessComparison, CrossoverChart } from "@/components/glass-box";

export function CompareView({
  report,
  onDrill,
}: {
  report: CostReport;
  /** drill a cell into its glass box (open the Glass Box lens on that process) */
  onDrill: (process: string) => void;
}) {
  const quantities = React.useMemo(() => costedQuantities(report), [report]);
  const breakeven = React.useMemo(() => deriveBreakeven(report), [report]);

  if (quantities.length === 0 || !report.decision) {
    return (
      <EmptyState
        icon={Scale}
        title="Nothing to compare yet"
        description="Cost a part across at least one quantity to open the decision board."
      />
    );
  }

  const qtyA = quantities[0];
  const qtyB = quantities[quantities.length - 1];
  const rows = buildCompareRows(report, qtyA, qtyB);
  const dec = report.decision;

  const crossover =
    dec.crossover_qty != null
      ? `${procLabel(dec.make_now_process)} is cheapest up to ~${Math.round(
          dec.crossover_qty
        ).toLocaleString()} units${
          dec.tooling_process
            ? `; ${procLabel(dec.tooling_process)} wins above it (tooling amortises)`
            : ""
        }.`
      : `${procLabel(dec.make_now_process)} stays cheapest at every quantity tested — no tooling crossover.`;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Each process priced at both costed quantities — the volume break. Every
        cell is a should-cost <span className="text-foreground">with its band</span>;
        click <span className="num">›</span> to open its glass box.
      </p>

      <ProcessComparison
        shopA={`Qty ${qtyA.toLocaleString()}`}
        shopB={`Qty ${qtyB.toLocaleString()}`}
        qty={qtyB}
        rows={rows}
        onDrill={(process) => onDrill(process)}
        lever={crossover}
      />

      {breakeven && (
        <Card className="space-y-2 p-4">
          <div className="flex items-center justify-between">
            <span className="cv-eyebrow">Make-vs-buy crossover</span>
            <span className="text-micro text-muted-foreground">
              $/unit vs quantity
            </span>
          </div>
          <CrossoverChart
            breakeven={breakeven}
            qty={qtyB}
            recommendedProcess={breakeven.makeNowProcess}
          />
        </Card>
      )}

      <div className="flex items-start gap-2 rounded-[var(--radius)] border border-border bg-muted/40 px-3 py-2.5 text-xs text-muted-foreground">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden />
        <span>
          Shop-vs-shop on one board (e.g. Midwest Precision CNC vs Shenzhen
          Contract Mfg, where the divergent <span className="num">labor_rate</span>{" "}
          becomes the negotiation lever) needs multi-shop-in-one-call — a build
          gap. The engine binds a shop per call today, so a true A/B composes from
          two real reports.
        </span>
      </div>
    </div>
  );
}
