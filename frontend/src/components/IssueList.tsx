"use client";

import { useEffect, useRef } from "react";
import { Crosshair } from "lucide-react";
import type { Issue, ValidationResult } from "@/lib/api";
import { severityTone, type Tone } from "@/lib/status";
import { StatusBadge } from "@/components/ui/status-badge";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Flattened issue index — shared by AnalysisDashboard (render) and   */
/*  PartWorkspace (geometry → issue mapping for two-way linking).      */
/* ------------------------------------------------------------------ */

export interface IndexedIssue {
  key: string;
  issue: Issue;
  /** sampled face indices for 3D highlight (unioned across duplicates) */
  faces: number[];
}

/** Merge universal + per-process issues, dedup by code|message, union faces. */
export function flattenIssues(result: ValidationResult): IndexedIssue[] {
  const seen = new Map<string, IndexedIssue>();
  const push = (issue: Issue, keyBase: string) => {
    const id = `${issue.code}|${issue.message}`;
    const faces = issue.affected_faces_sample ?? [];
    const existing = seen.get(id);
    if (existing) {
      existing.faces = Array.from(new Set([...existing.faces, ...faces]));
    } else {
      seen.set(id, { key: keyBase, issue, faces: [...faces] });
    }
  };
  result.universal_issues.forEach((iss, i) => push(iss, `u${i}`));
  result.process_scores.forEach((ps) =>
    ps.issues.forEach((iss, i) => push(iss, `${ps.process}#${i}`))
  );
  return Array.from(seen.values());
}

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
