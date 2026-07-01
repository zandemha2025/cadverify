"use client";

/**
 * DriverBreakdown — the open model. Every cost driver, provenance-tagged and
 * sourced, with the Σ line-items = unit-cost coherence check shown (no naked
 * numbers). Each row is a universal drill-target: it expands INLINE (never a
 * modal) to the engine's verbatim source string and an override affordance that
 * re-tags the value USER. DEFAULT rows are quieter-but-flagged so the cost
 * engineer instantly sees where the model is guessing.
 */

import * as React from "react";
import { ChevronRight, PencilLine, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CostDriver, CostEstimate } from "@/lib/api";
import { provMeta } from "@/lib/status";
import { ProvenanceChip } from "./provenance";

/** The rate a driver row edits — label/unit/prefill supplied by the parent. */
export interface DriverRateEditor {
  label: string; // e.g. "machine rate"
  unit: string; // e.g. "$/hr"
  prefill: number | null; // current rate, read from the engine's source string
}

const USD = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function fmtDriver(d: CostDriver): string {
  if (d.unit === "$") return USD(d.value);
  const v =
    Math.abs(d.value) >= 100
      ? d.value.toLocaleString(undefined, { maximumFractionDigits: 1 })
      : d.value.toLocaleString(undefined, { maximumFractionDigits: 3 });
  return d.unit && d.unit !== "frac" ? `${v} ${d.unit}` : v;
}

function DriverLine({
  driver,
  onOverride,
  rateEditor,
}: {
  driver: CostDriver;
  /** commit a new RATE for this driver → a real server re-cost. */
  onOverride?: (d: CostDriver, value: number) => void;
  /** the rate this row edits, or null when the driver has no rate lever. */
  rateEditor?: DriverRateEditor | null;
}) {
  const [open, setOpen] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const m = provMeta(driver.provenance);
  const editable = !!onOverride && !!rateEditor;

  const startEdit = () => {
    setDraft(rateEditor?.prefill != null ? String(rateEditor.prefill) : "");
    setEditing(true);
  };
  const commit = () => {
    const v = parseFloat(draft);
    if (!Number.isNaN(v)) onOverride?.(driver, v);
    setEditing(false);
  };
  return (
    <div
      className={cn(
        "rounded-[var(--radius)] border border-transparent transition-colors",
        open && "border-border bg-card-raised"
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-[var(--radius)] px-2 py-1.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90"
          )}
          aria-hidden
        />
        <span
          className={cn(
            "num min-w-0 flex-1 truncate text-sm",
            m.filled ? "text-foreground" : "text-muted-foreground"
          )}
        >
          {driver.name}
        </span>
        <span className="num text-sm font-semibold text-foreground">
          {fmtDriver(driver)}
        </span>
        <ProvenanceChip provenance={driver.provenance} withLabel size="xs" />
        {driver.error_band_pct != null && (
          <span className="num w-12 shrink-0 text-right text-micro text-muted-foreground">
            ±{driver.error_band_pct}%
          </span>
        )}
      </button>
      {open && (
        <div className="cv-reveal space-y-2 px-8 pb-2.5 pt-0.5">
          <p className="num text-micro leading-relaxed text-muted-foreground">
            <span className={cn("font-semibold", m.fg)}>{m.label}</span> · {driver.source}
          </p>
          {editable &&
            (editing ? (
              <div className="flex items-center gap-1.5">
                <span className="text-micro text-muted-foreground">
                  {rateEditor!.label}
                </span>
                <input
                  autoFocus
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commit();
                    if (e.key === "Escape") setEditing(false);
                  }}
                  inputMode="decimal"
                  aria-label={`Override ${rateEditor!.label}`}
                  className="num h-7 w-24 rounded-sm border border-prov-user-border bg-card px-2 text-right text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <span className="num text-micro text-muted-foreground">
                  {rateEditor!.unit}
                </span>
                <button
                  type="button"
                  onClick={commit}
                  aria-label="Apply override"
                  className="rounded-sm p-1 text-prov-user hover:bg-prov-user-bg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Check className="size-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  aria-label="Cancel override"
                  className="rounded-sm p-1 text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <X className="size-4" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={startEdit}
                className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <PencilLine className="size-3.5" />
                Override {rateEditor!.label} — re-tags USER, re-costs
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

export function DriverBreakdown({
  estimate,
  onOverride,
  rateEditorFor,
  className,
}: {
  estimate: CostEstimate;
  /** commit a new RATE for a driver → a real server re-cost. */
  onOverride?: (d: CostDriver, value: number) => void;
  /** the rate a given driver edits, or null when it has no rate lever. */
  rateEditorFor?: (d: CostDriver) => DriverRateEditor | null;
  className?: string;
}) {
  const drivers = estimate.drivers.filter((d) => d.name !== "cycle_time");
  const items = Object.entries(estimate.line_items);
  const sum = items.reduce((a, [, v]) => a + v, 0);
  const coherent = Math.abs(sum - estimate.unit_cost_usd) < 0.02;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="space-y-0.5">
        {drivers.map((d) => (
          <DriverLine
            key={d.name}
            driver={d}
            onOverride={onOverride}
            rateEditor={rateEditorFor ? rateEditorFor(d) : null}
          />
        ))}
      </div>

      {/* Σ = unit cost — the coherence check, always visible. Show the arithmetic. */}
      <div className="rounded-[var(--radius)] border border-border bg-card-raised px-3 py-2.5">
        <div className="space-y-1">
          {items.map(([k, v]) => (
            <div key={k} className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{k}</span>
              <span className="num text-foreground">{USD(v)}</span>
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-center justify-between border-t border-border pt-2">
          <span className="text-sm font-semibold text-foreground">
            Σ line items = unit cost
          </span>
          <span
            className={cn(
              "num text-sm font-semibold",
              coherent ? "text-foreground" : "text-fail"
            )}
          >
            {USD(sum)}
            {!coherent && (
              <span className="ml-1 text-xs">(≠ {USD(estimate.unit_cost_usd)})</span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
