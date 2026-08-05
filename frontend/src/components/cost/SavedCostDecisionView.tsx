"use client";

/**
 * SavedCostDecisionView — re-renders a PERSISTED should-cost decision read-only
 * from its verbatim `result_json`. Answer-first (the make-vs-buy headline + the
 * honest confidence band), then the full glass-box breakdown via the shared
 * CostDecisionCard. It never re-costs (that is the live instrument's job); this
 * is the durable artifact the buyer saved.
 *
 * Honesty is preserved: the confidence band renders the engine's own
 * validated/label verbatim, and the CostHonestyNote states it is not a quote.
 */

import type { CostReport } from "@/lib/api";
import { procLabel } from "@/lib/status";
import { pickEstimate } from "@/lib/cost-views";
import { Card, CardContent } from "@/components/ui/card";
import CostDecisionCard from "@/components/CostDecisionCard";
import { CostHonestyNote } from "@/components/cost/CostHonestyNote";
import {
  DecisionHeadline,
  ConfidenceInterval,
} from "@/components/glass-box";

function crossoverSentence(report: CostReport): string {
  const dec = report.decision;
  if (!dec) return "";
  if (dec.crossover_qty != null) {
    const n = Math.round(dec.crossover_qty).toLocaleString();
    const make = procLabel(dec.make_now_process);
    if (dec.tooling_process) {
      return `Make below ~${n} units with ${make}; tool up with ${procLabel(
        dec.tooling_process
      )} above it.`;
    }
    return `${make} wins below ~${n} units; tooling amortizes above it.`;
  }
  return `${procLabel(dec.make_now_process)} stays cheapest at every quantity tested.`;
}

export function SavedCostDecisionView({ report }: { report: CostReport }) {
  const dec = report.decision;

  // GEOMETRY_INVALID / no decision → CostDecisionCard renders the repair card.
  if (report.status !== "OK" || !dec) {
    return (
      <div className="space-y-4">
        <CostHonestyNote />
        <CostDecisionCard report={report} />
      </div>
    );
  }

  // Representative estimate behind the make-now process → the confidence band.
  const headEstimate = pickEstimate(report, dec.make_now_process);
  const conf = headEstimate?.confidence ?? null;

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <DecisionHeadline
          title={`Make by ${procLabel(dec.make_now_process)}`}
          dfmReady={headEstimate?.dfm_ready ?? false}
          sentence={crossoverSentence(report)}
        />
        <CardContent compact className="space-y-3">
          {conf ? (
            <ConfidenceInterval confidence={conf} />
          ) : (
            <p className="text-xs text-muted-foreground">
              Assumption-based should-cost — not yet validated on your parts.
            </p>
          )}
        </CardContent>
      </Card>

      <CostHonestyNote />

      <CostDecisionCard report={report} />
    </div>
  );
}
