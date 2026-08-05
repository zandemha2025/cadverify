"use client";

/**
 * Routing & DFM lens — where the Manufacturing engineer lands: "is it made the
 * right way." The geometric routing card foregrounds the engine's REASONING
 * paragraph (this persona's trust object) over the MEASURED drivers that decided
 * it; the DFM matrix is actionable, each blocker linking to geometry in the 3D
 * rail. The full per-process DFM dashboard sits below for the deep audit.
 */

import * as React from "react";
import { Factory } from "lucide-react";
import type { CostReport, ValidationResult } from "@/lib/api";
import { blockersByProcess } from "@/lib/cost-views";
import { procLabel } from "@/lib/status";
import { marginalRate } from "@/lib/verify/verification";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { RoutingCard, DfmMatrix } from "@/components/glass-box";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import type { IndexedIssue } from "@/components/IssueList";

export function RoutingDfmView({
  report,
  validation,
  selectedIssueKey,
  onSelectIssue,
  onHighlightProcess,
}: {
  report: CostReport | null;
  validation: ValidationResult | null;
  selectedIssueKey: string | null;
  onSelectIssue: (it: IndexedIssue) => void;
  /** highlight the offending faces for a process's DFM blocker in the 3D rail */
  onHighlightProcess: (process: string) => void;
}) {
  const blockers = React.useMemo(
    () => (report ? blockersByProcess(report) : {}),
    [report]
  );
  const makeNowProcess = report?.decision?.make_now_process ?? null;
  const machineGrounding = React.useMemo(
    () => marginalRate(report?.verification, makeNowProcess),
    [report?.verification, makeNowProcess]
  );
  const machineFit =
    makeNowProcess && report?.verification?.per_route
      ? report.verification.per_route[makeNowProcess]
      : null;

  if (!report && !validation) {
    return (
      <EmptyState
        icon={Factory}
        title="No routing yet"
        description="Drop a part to see the geometry-recommended process, the reasoning behind it, and the per-process DFM verdicts."
      />
    );
  }

  return (
    <div className="space-y-4">
      {report?.routing ? (
        <RoutingCard routing={report.routing} />
      ) : report ? (
        <Card className="p-4 text-sm text-muted-foreground">
          Geometric routing not present on this report — surfacing{" "}
          <span className="num">routing</span> through the API is a build gap; the
          archetype, recommended process and reasoning live in the engine.
        </Card>
      ) : null}

      {machineGrounding && makeNowProcess && (
        <Card data-testid="machine-grounding" className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <span className="cv-eyebrow">Owned-machine grounding</span>
              <p className="mt-1 text-sm leading-relaxed text-foreground">
                <span className="font-semibold">
                  {machineGrounding.machine ?? "An owned machine"}
                </span>{" "}
                clears the declared floor gates for {procLabel(makeNowProcess)}.
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {machineFit?.machines_evaluated ?? 0} declared machine
                {(machineFit?.machines_evaluated ?? 0) === 1 ? "" : "s"} evaluated ·
                USER-declared capability and marginal rate
              </p>
            </div>
            <div className="rounded-sm border border-border bg-muted px-3 py-2 text-right">
              <p className="num text-sm font-semibold text-foreground">
                {machineGrounding.rateUsd == null
                  ? "Rate withheld"
                  : `$${machineGrounding.rateUsd.toFixed(2)}/hr`}
              </p>
              <p className="text-micro uppercase tracking-wide text-muted-foreground">
                decision rate
              </p>
            </div>
          </div>
        </Card>
      )}

      {report && report.engine_feasibility.length > 0 && (
        <DfmMatrix
          feasibility={report.engine_feasibility}
          blockers={blockers}
          costPick={report.decision?.make_now_process}
          onHighlight={validation ? onHighlightProcess : undefined}
        />
      )}

      {validation && (
        <div className="space-y-2 border-t border-border pt-4">
          <span className="cv-eyebrow">Per-process DFM audit</span>
          <AnalysisDashboard
            result={validation}
            selectedIssueKey={selectedIssueKey}
            onSelectIssue={onSelectIssue}
          />
        </div>
      )}
    </div>
  );
}
