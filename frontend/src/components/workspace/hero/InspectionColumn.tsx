"use client";

/**
 * InspectionColumn — the co-primary FINDINGS column of the part hero (D5 FE-2).
 *
 * "The engine answers without being asked" (D1 truth #3): on drop, this column
 * surfaces what you missed — every finding pinned to its locus and its source.
 * Two real classes of evidence, one severity vocabulary, staggered in on the
 * showcase tempo:
 *
 *   • DFM issues — the engine's real `Issue`s, SCOPED to the recommended route
 *     via lib/dfm-scope (not the scary union across all 21 candidate processes).
 *     Each card: severity chip · code · measured→required · message · fix, and a
 *     LOCATE affordance when the issue carries affected faces — clicking it drives
 *     the existing highlightFaces/onFaceClick wiring on the shared CadViewer stage.
 *   • Derived findings — provenance-caveat · confidence-caveat · fragility, from
 *     the pure lib/findings on the real report. Each names the exact engine field
 *     it binds to (no fake affordances, no geometry it doesn't have).
 *
 * The full per-process DFM matrix + routing reasoning live one click deeper, in
 * the Inspection depth panel (onOpenDepth) — reachable, never the only path.
 */

import * as React from "react";
import { Crosshair, Factory, ChevronRight, ShieldCheck } from "lucide-react";
import type { IndexedIssue } from "@/lib/dfm-scope";
import type { DerivedFinding } from "@/lib/findings";
import { severityTone, type Tone } from "@/lib/status";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/ui/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ErrorState } from "@/components/ui/error-state";
import { Rise, staggerDelay } from "@/components/ui/motion";

const TONE_RANK: Record<Tone, number> = { fail: 0, warn: 1, info: 2, neutral: 3, pass: 4 };

type Row =
  | { kind: "dfm"; key: string; tone: Tone; issue: IndexedIssue }
  | { kind: "derived"; key: string; tone: Tone; finding: DerivedFinding };

/** Inline renderer for `[tag]` citation markers — mirrors IssueList. */
function CitationText({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const m = part.match(/^\[([^\]]+)\]$/);
        return m ? (
          <Badge key={i} variant="outline" size="sm" className="num mx-0.5 align-baseline">
            {m[1]}
          </Badge>
        ) : (
          <span key={i}>{part}</span>
        );
      })}
    </>
  );
}

export function InspectionColumn({
  issues,
  findings,
  selectedKey,
  onSelect,
  analyzing,
  error,
  onRetry,
  onOpenDepth,
  candidateProcessCount,
  revealBase = 360,
  step = 70,
}: {
  /** DFM issues scoped to the recommended route (canonical keys) */
  issues: IndexedIssue[];
  /** derived trust findings (provenance / confidence / fragility) */
  findings: DerivedFinding[];
  selectedKey: string | null;
  /** select a DFM issue → highlight its faces on the stage (null clears) */
  onSelect: (key: string | null) => void;
  analyzing?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** open the per-process DFM audit + routing (the Inspection depth panel) */
  onOpenDepth?: () => void;
  /** number of candidate processes evaluated (honest "N of M" scope note) */
  candidateProcessCount?: number;
  /** base (showcase) reveal delay in ms for the first card */
  revealBase?: number;
  step?: number;
}) {
  const rows = React.useMemo<Row[]>(() => {
    const dfm: Row[] = issues.map((it) => ({
      kind: "dfm" as const,
      key: it.key,
      tone: severityTone(it.issue.severity),
      issue: it,
    }));
    const der: Row[] = findings.map((f) => ({
      kind: "derived" as const,
      key: f.key,
      tone: severityTone(f.severity),
      finding: f,
    }));
    // dfm-before-derived within a tone (geometry-pinned evidence leads); stable.
    return [...dfm, ...der].sort((a, b) => TONE_RANK[a.tone] - TONE_RANK[b.tone]);
  }, [issues, findings]);

  const counts = React.useMemo(() => {
    const c = { fail: 0, warn: 0, info: 0 };
    for (const r of rows) {
      if (r.tone === "fail") c.fail++;
      else if (r.tone === "warn") c.warn++;
      else c.info++;
    }
    return c;
  }, [rows]);

  return (
    <section aria-label="Inspection" className="flex min-w-0 flex-col gap-3">
      <Rise delay={revealBase - 40}>
        <header className="flex items-baseline justify-between gap-2">
          <span className="cv-eyebrow">Inspection · findings</span>
          {rows.length > 0 && (
            <span className="num text-[11px] text-muted-foreground">
              {counts.fail > 0 && <span className="text-fail">{counts.fail} required</span>}
              {counts.fail > 0 && (counts.warn > 0 || counts.info > 0) && " · "}
              {counts.warn > 0 && <span className="text-warn">{counts.warn} advisory</span>}
              {counts.warn > 0 && counts.info > 0 && " · "}
              {counts.info > 0 && <span className="text-muted-foreground">{counts.info} note{counts.info === 1 ? "" : "s"}</span>}
            </span>
          )}
        </header>
      </Rise>

      {error && !analyzing ? (
        <Rise delay={revealBase}>
          <ErrorState title="Analysis unavailable" message={error} onRetry={onRetry} />
        </Rise>
      ) : analyzing && rows.length === 0 ? (
        <Rise delay={revealBase}>
          <Card className="flex h-40 flex-col items-center justify-center gap-3">
            <Spinner />
            <p className="text-sm text-muted-foreground">Inspecting across processes…</p>
          </Card>
        </Rise>
      ) : rows.length === 0 ? (
        <Rise delay={revealBase}>
          <Card className="space-y-2 p-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-pass" aria-hidden />
              <span className="text-sm font-semibold text-foreground">
                Clean on the recommended route
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              No DFM blockers on the recommended process and no open cost caveats. The
              full per-process matrix is one click deeper.
            </p>
          </Card>
        </Rise>
      ) : (
        <div className="flex flex-col gap-2.5">
          {rows.map((row, i) => (
            <Rise key={row.key} delay={revealBase + staggerDelay(i, step)}>
              {row.kind === "dfm" ? (
                <DfmCard
                  item={row.issue}
                  selected={selectedKey === row.key}
                  onSelect={() => onSelect(selectedKey === row.key ? null : row.key)}
                />
              ) : (
                <DerivedCard finding={row.finding} />
              )}
            </Rise>
          ))}
        </div>
      )}

      {onOpenDepth && (rows.length > 0 || (!analyzing && !error)) && (
        <Rise delay={revealBase + staggerDelay(rows.length, step)}>
          <button
            type="button"
            onClick={onOpenDepth}
            className="group flex w-full items-center gap-2 rounded-[var(--radius)] border border-border bg-card px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Factory className="size-4 text-muted-foreground" aria-hidden />
            <span className="flex-1">
              <span className="font-medium text-foreground">Per-process DFM audit</span>
              {candidateProcessCount ? (
                <span className="num ml-1.5 text-xs text-muted-foreground">
                  {candidateProcessCount} processes · routing reasoning
                </span>
              ) : (
                <span className="ml-1.5 text-xs text-muted-foreground">routing reasoning</span>
              )}
            </span>
            <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
          </button>
        </Rise>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Cards                                                              */
/* ------------------------------------------------------------------ */

function DfmCard({
  item,
  selected,
  onSelect,
}: {
  item: IndexedIssue;
  selected: boolean;
  onSelect: () => void;
}) {
  const { issue, faces } = item;
  const ref = React.useRef<HTMLDivElement>(null);
  const locatable = faces.length > 0;

  React.useEffect(() => {
    if (selected && ref.current) {
      ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selected]);

  return (
    <div
      ref={ref}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "cursor-pointer rounded-[var(--radius)] border bg-card p-3 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "border-primary ring-2 ring-primary/40" : "border-border"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge severity={issue.severity} size="sm" />
          <span className="num text-xs text-muted-foreground">{issue.code}</span>
          {issue.measured_value !== undefined && issue.required_value !== undefined && (
            <span className="num text-xs text-muted-foreground">
              {issue.measured_value.toFixed(2)} / {issue.required_value} required
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

/** Plain-language label for a derived-finding class (the honesty audit trail). */
const CLASS_LABEL: Record<DerivedFinding["cls"], string> = {
  "provenance-caveat": "provenance",
  "confidence-caveat": "confidence",
  fragility: "fragility",
};

function DerivedCard({ finding }: { finding: DerivedFinding }) {
  return (
    <div className="rounded-[var(--radius)] border border-border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge severity={finding.severity} size="sm" />
        <span className="cv-eyebrow">{CLASS_LABEL[finding.cls]}</span>
      </div>
      <p className="mt-1 text-sm font-medium text-foreground">{finding.title}</p>
      <p className="mt-0.5 text-sm text-muted-foreground">{finding.detail}</p>
      <p className="num mt-1.5 text-micro text-subtle-foreground">{finding.source}</p>
    </div>
  );
}
