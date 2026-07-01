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
