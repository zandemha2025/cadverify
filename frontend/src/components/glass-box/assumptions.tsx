"use client";

/**
 * Assumptions — every one editable. The cost engineer's surface: each assumption
 * shows value + provenance + source; "Override" turns it into an inline field
 * that, on commit, re-tags the value USER and fires `onOverride` (the report
 * re-runs upstream). SHOP/MEASURED rows read grounded; DEFAULT rows are flagged
 * hollow so the gaps — "where the model is guessing" — are visible, not hidden.
 */

import * as React from "react";
import { PencilLine, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CostAssumption } from "@/lib/api";
import { provMeta } from "@/lib/status";
import { ProvenanceChip } from "./provenance";

function fmtValue(a: Pick<CostAssumption, "value" | "unit">): string {
  if (a.unit === "$/hr") return `$${a.value}/hr`;
  if (a.unit === "$") return `$${a.value}`;
  if (a.unit === "×") return `${a.value}×`;
  if (!a.unit || a.unit === "frac") return String(a.value);
  return `${a.value} ${a.unit}`;
}

function AssumptionItem({
  assumption,
  onOverride,
  canOverride,
}: {
  assumption: CostAssumption;
  onOverride?: (name: string, value: number) => void;
  canOverride?: (a: CostAssumption) => boolean;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(String(assumption.value));
  const m = provMeta(assumption.provenance);
  const editable = !!onOverride && (canOverride ? canOverride(assumption) : true);

  const commit = () => {
    const v = parseFloat(draft);
    if (!Number.isNaN(v)) onOverride?.(assumption.name, v);
    setEditing(false);
  };

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-[var(--radius)] border px-3 py-2",
        editing ? "border-prov-user-border bg-prov-user-bg/40" : "border-border bg-card"
      )}
    >
      <span className="min-w-0 flex-1 truncate text-sm text-foreground" title={assumption.source}>
        {assumption.name}
      </span>

      {editing ? (
        <>
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              if (e.key === "Escape") setEditing(false);
            }}
            inputMode="decimal"
            aria-label={`Override ${assumption.name}`}
            className="num h-7 w-20 rounded-sm border border-prov-user-border bg-card px-2 text-right text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
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
        </>
      ) : (
        <>
          <span className={cn("num text-sm font-semibold", m.filled ? "text-foreground" : "text-muted-foreground")}>
            {fmtValue(assumption)}
          </span>
          <ProvenanceChip provenance={assumption.provenance} withLabel={false} size="xs" />
          {editable && (
            <button
              type="button"
              onClick={() => {
                setDraft(String(assumption.value));
                setEditing(true);
              }}
              aria-label={`Override ${assumption.name}`}
              className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <PencilLine className="size-3.5" />
            </button>
          )}
        </>
      )}
    </div>
  );
}

export function AssumptionGrid({
  assumptions,
  onOverride,
  canOverride,
  className,
}: {
  assumptions: CostAssumption[];
  onOverride?: (name: string, value: number) => void;
  /** which assumptions are editable into a real re-cost (others read-only) */
  canOverride?: (a: CostAssumption) => boolean;
  className?: string;
}) {
  return (
    <div className={cn("grid gap-2 sm:grid-cols-2", className)}>
      {assumptions.map((a) => (
        <AssumptionItem
          key={a.name}
          assumption={a}
          onOverride={onOverride}
          canOverride={canOverride}
        />
      ))}
    </div>
  );
}
