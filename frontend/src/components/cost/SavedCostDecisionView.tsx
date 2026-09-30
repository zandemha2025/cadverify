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
import { crossoverSummary } from "@/lib/cost-decision";
import { Card, CardContent } from "@/components/ui/card";
import CostDecisionCard from "@/components/CostDecisionCard";
import { CostHonestyNote } from "@/components/cost/CostHonestyNote";
import {
  DecisionHeadline,
  ConfidenceInterval,
} from "@/components/glass-box";

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
  const costStamp = headEstimate?.dfm_ready
    ? {
        text: `Manufacturable by ${procLabel(dec.make_now_process)} at $${headEstimate.unit_cost_usd.toFixed(2)}/unit`,
        quantity: headEstimate.quantity,
        validated: headEstimate.confidence?.validated ?? false,
        label: headEstimate.confidence?.label ?? "Assumption-based should-cost, not yet validated",
      }
    : null;

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <DecisionHeadline
          title={`Make by ${procLabel(dec.make_now_process)}`}
          dfmReady={headEstimate?.dfm_ready ?? false}
          sentence={crossoverSummary(dec)}
        />
        <CardContent compact className="space-y-3">
          {costStamp ? (
            <div className="rounded-md border border-pass/30 bg-pass-bg p-3" data-testid="cost-stamp">
              <p className="font-semibold text-foreground">{costStamp.text}</p>
              <p className="text-xs text-muted-foreground">
                At quantity {costStamp.quantity.toLocaleString()} · {costStamp.validated ? "VALIDATED" : "ESTIMATE"} · {costStamp.label}
              </p>
            </div>
          ) : (
            <p className="text-sm font-medium text-fail">Manufacturability/cost stamp withheld: the selected route has DFM blockers.</p>
          )}
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
