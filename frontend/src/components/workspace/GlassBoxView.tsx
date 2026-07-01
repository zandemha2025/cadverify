"use client";

/**
 * Glass Box lens — where the Cost engineer lands. The inverse of the Decision
 * lens: depth is the default. Every driver provenance-tagged + sourced, summing
 * visibly to the unit cost; the confidence band with its basis spelled out; every
 * editable assumption/driver re-costs FOR REAL — the edit threads the engine's
 * override surface (the CLI --set keys) back through the cost API, so the number
 * actually moves and the touched line returns tagged USER. Bound to the engine's
 * REAL report_to_dict — no naked numbers, no fabricated accuracy figure.
 */

import * as React from "react";
import { Bookmark, Boxes, RotateCcw } from "lucide-react";
import type { CostReport, CostAssumption, CostDriver } from "@/lib/api";
import { procLabel } from "@/lib/status";
import {
  costedProcesses,
  costedQuantities,
  pickEstimate,
  assumptionOverrideKey,
  canOverrideAssumption,
  canOverrideDriver,
  driverOverrideKey,
  driverRateLabel,
  driverRateUnit,
  parseDriverRate,
} from "@/lib/cost-views";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import {
  DriverBreakdown,
  ConfidenceInterval,
  AssumptionGrid,
  ProvenanceLegend,
  ProvenanceChip,
  type DriverRateEditor,
} from "@/components/glass-box";

const USD = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** A session-local saved scenario (overrides + the headline it produced). */
export interface ScenarioSummary {
  id: string;
  label: string;
  unitCost: number | null;
  process: string | null;
}

function Segmented<T extends string | number>({
  label,
  options,
  value,
  format,
  onChange,
}: {
  label: string;
  options: T[];
  value: T;
  format: (v: T) => string;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="cv-eyebrow">{label}</span>
      <div className="inline-flex flex-wrap gap-1 rounded-[var(--radius)] border border-border bg-muted p-0.5">
        {options.map((o) => (
          <button
            key={String(o)}
            type="button"
            onClick={() => onChange(o)}
            aria-pressed={o === value}
            className={cn(
              "num rounded-sm px-2 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              o === value
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {format(o)}
          </button>
        ))}
      </div>
    </div>
  );
}

export function GlassBoxView({
  report,
  assumptions,
  overrideCount,
  recosting,
  scenarios,
  onApplyOverride,
  onSetCavities,
  onClearOverrides,
  onSaveScenario,
  onRecallScenario,
}: {
  report: CostReport;
  assumptions: CostAssumption[];
  /** how many ad-hoc USER overrides are currently applied */
  overrideCount: number;
  recosting?: boolean;
  scenarios: ScenarioSummary[];
  /** thread a dotted rate override (e.g. labor_rate, machine_rate.MJF) → re-cost */
  onApplyOverride: (key: string, value: number) => void;
  /** n_cavities edits route to the cavities option → re-cost */
  onSetCavities: (value: number) => void;
  /** drop all ad-hoc overrides, back to the shop/default rates */
  onClearOverrides: () => void;
  onSaveScenario: () => void;
  onRecallScenario: (id: string) => void;
}) {
  const processes = React.useMemo(() => costedProcesses(report), [report]);
  const quantities = React.useMemo(() => costedQuantities(report), [report]);

  const [process, setProcess] = React.useState(
    () => report.decision?.make_now_process ?? processes[0]
  );
  const [qty, setQty] = React.useState(
    () => quantities[0] ?? report.quantities[0]
  );

  // keep the selection valid if the report changes underneath us
  React.useEffect(() => {
    if (!processes.includes(process)) {
      setProcess(report.decision?.make_now_process ?? processes[0]);
    }
    if (!quantities.includes(qty)) setQty(quantities[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report]);

  const estimate = pickEstimate(report, process, qty);

  /* ---- override wiring (real re-cost) ----------------------------- */
  const onOverrideAssumption = React.useCallback(
    (name: string, value: number) => {
      const key = assumptionOverrideKey(name);
      if (key) onApplyOverride(key, value);
      else if (name === "n_cavities") onSetCavities(Math.max(1, Math.round(value)));
    },
    [onApplyOverride, onSetCavities]
  );

  const onOverrideDriver = React.useCallback(
    (d: CostDriver, value: number) => {
      const key = driverOverrideKey(d.name, process, report.material_class);
      if (key) onApplyOverride(key, value);
    },
    [onApplyOverride, process, report.material_class]
  );

  const rateEditorFor = React.useCallback(
    (d: CostDriver): DriverRateEditor | null =>
      canOverrideDriver(d.name)
        ? {
            label: driverRateLabel(d.name),
            unit: driverRateUnit(d.name),
            prefill: parseDriverRate(d),
          }
        : null,
    []
  );

  if (!estimate) {
    return (
      <EmptyState
        icon={Boxes}
        title="No cost breakdown yet"
        description="Drop a part to open the glass box — every driver, its provenance, and the arithmetic that sums to the unit cost."
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* selectors */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Segmented
          label="Process"
          options={processes}
          value={process}
          format={procLabel}
          onChange={setProcess}
        />
        <Segmented
          label="Qty"
          options={quantities}
          value={qty}
          format={(q) => q.toLocaleString()}
          onChange={setQty}
        />
        <span className="num ml-auto text-sm text-muted-foreground">
          {procLabel(estimate.process)} ·{" "}
          <span className="font-semibold text-foreground">
            {USD(estimate.unit_cost_usd)}
          </span>
          /unit
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* drivers + Σ check */}
        <Card className="space-y-3 p-4">
          <div className="flex items-baseline justify-between">
            <span className="cv-eyebrow">Cost drivers · the open model</span>
            <span className="text-micro text-muted-foreground">
              click a driver → edit its rate → re-costs
            </span>
          </div>
          <DriverBreakdown
            estimate={estimate}
            onOverride={onOverrideDriver}
            rateEditorFor={rateEditorFor}
          />
        </Card>

        {/* confidence + assumptions */}
        <div className="space-y-4">
          {estimate.confidence && (
            <Card className="p-4">
              <ConfidenceInterval confidence={estimate.confidence} />
            </Card>
          )}
          <Card className="space-y-3 p-4">
            <div className="flex items-baseline justify-between">
              <span className="cv-eyebrow">Assumptions · editable ones re-cost</span>
              <span className="text-micro text-muted-foreground">
                override → re-tags USER
              </span>
            </div>
            <AssumptionGrid
              assumptions={assumptions}
              onOverride={onOverrideAssumption}
              canOverride={(a) => canOverrideAssumption(a.name)}
            />
          </Card>
        </div>
      </div>

      {/* saved scenarios (this session) */}
      {scenarios.length > 0 && (
        <Card className="space-y-2 p-4">
          <span className="cv-eyebrow">Saved scenarios · this session</span>
          <div className="flex flex-wrap gap-2">
            {scenarios.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => onRecallScenario(s.id)}
                className="num inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="text-muted-foreground">{s.label}</span>
                {s.unitCost != null && (
                  <span className="font-semibold">{USD(s.unitCost)}</span>
                )}
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <ProvenanceLegend />
          {overrideCount > 0 && (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <ProvenanceChip provenance="USER" size="xs" />
              {overrideCount} override{overrideCount === 1 ? "" : "s"} applied
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {overrideCount > 0 && (
            <Button variant="ghost" onClick={onClearOverrides} disabled={recosting}>
              <RotateCcw className="size-4" />
              Reset overrides
            </Button>
          )}
          <Button variant="secondary" onClick={onSaveScenario} disabled={recosting}>
            <Bookmark className="size-4" />
            Save as scenario
          </Button>
        </div>
      </Card>

      {!estimate.confidence && (
        <p className="text-xs text-muted-foreground">
          Confidence band not present on this estimate — surfacing{" "}
          <span className="num">confidence</span> through the API is a build gap;
          the band lives in the engine&apos;s report.
        </p>
      )}
    </div>
  );
}
