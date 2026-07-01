"use client";

import { useEffect, useRef } from "react";
import { Crosshair } from "lucide-react";
import { severityTone, type Tone } from "@/lib/status";
import { StatusBadge } from "@/components/ui/status-badge";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { flattenIssues, type IndexedIssue } from "@/lib/dfm-scope";

/* ------------------------------------------------------------------ */
/*  Flattened issue index — the pure flatten/scoping logic now lives   */
/*  in `@/lib/dfm-scope` (unit-tested, no React). Re-exported here for  */
/*  the existing importers (AnalysisDashboard, LivingInstrument,       */
/*  PartWorkspace) and used by this renderer.                          */
/* ------------------------------------------------------------------ */

export { flattenIssues };
export type { IndexedIssue };

/** Inline renderer for `[tag]` citation markers — neutral, on-token badges. */
function CitationText({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[([^\]]+)\]$/);
        if (match) {
          return (
            <Badge
              key={i}
              variant="outline"
              size="sm"
              className="num mx-0.5 align-baseline"
            >
              {match[1]}
            </Badge>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

const GROUP_ORDER: { tone: Tone; label: string }[] = [
  { tone: "fail", label: "Required fixes" },
  { tone: "warn", label: "Advisory" },
  { tone: "info", label: "Notes" },
];

export default function IssueList({
  items,
  selectedKey,
  onSelect,
}: {
  items: IndexedIssue[];
  selectedKey?: string | null;
  onSelect?: (item: IndexedIssue) => void;
}) {
  if (items.length === 0) return null;

  const groups = GROUP_ORDER.map((g) => ({
    ...g,
    rows: items.filter((it) => severityTone(it.issue.severity) === g.tone),
  })).filter((g) => g.rows.length > 0);

  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <div key={g.label}>
          <div className="mb-2 flex items-center gap-2">
            <StatusBadge tone={g.tone} label={g.label} size="sm" />
            <span className="num text-xs text-muted-foreground">
              {g.rows.length}
            </span>
          </div>
          <div className="space-y-2">
            {g.rows.map((it) => (
              <IssueRow
                key={it.key}
                item={it}
                selected={selectedKey === it.key}
                onSelect={onSelect}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function IssueRow({
  item,
  selected,
  onSelect,
}: {
  item: IndexedIssue;
  selected: boolean;
  onSelect?: (item: IndexedIssue) => void;
}) {
  const { issue, faces } = item;
  const ref = useRef<HTMLDivElement>(null);
  const interactive = !!onSelect;
  const locatable = interactive && faces.length > 0;

  useEffect(() => {
    if (selected && ref.current) {
      ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selected]);

  return (
    <div
      ref={ref}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? () => onSelect?.(item) : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect?.(item);
              }
            }
          : undefined
      }
      className={cn(
        "rounded-[var(--radius)] border bg-card p-3 transition-colors",
        interactive && "cursor-pointer hover:bg-muted/60",
        selected
          ? "border-primary ring-2 ring-primary/40"
          : "border-border"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge severity={issue.severity} size="sm" />
          <span className="num text-xs text-muted-foreground">{issue.code}</span>
          {issue.measured_value !== undefined &&
            issue.required_value !== undefined && (
              <span className="num text-xs text-muted-foreground">
                {issue.measured_value.toFixed(2)} / {issue.required_value}{" "}
                required
              </span>
            )}
        </div>
        {locatable && (
          <span
            className="flex shrink-0 items-center gap-1 text-[11px] text-primary"
            title="Highlighted on the 3D model"
          >
            <Crosshair className="size-3.5" />
            {selected ? "shown in 3D" : "locate"}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-foreground">{issue.message}</p>
      {issue.fix_suggestion && (
        <p className="mt-1 whitespace-pre-line text-sm text-muted-foreground">
          <CitationText text={issue.fix_suggestion} />
        </p>
      )}
    </div>
  );
}
