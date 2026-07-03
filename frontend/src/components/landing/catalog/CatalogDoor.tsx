"use client";

/**
 * CatalogDoor — Door B's landing (D5 FE-4): the cost / sourcing engineer's grid
 * over their REAL saved should-cost decisions. Not an invented table — every row
 * is one saved decision, and every cell binds to a real engine field:
 *
 *   Part · Route · Unit $ · DFM (route blockers) · Posture · State · When
 *
 * The list columns paint immediately off `/cost-decisions`; unit $, posture, the
 * route-blocker count and the lifecycle state hydrate per row from each decision's
 * verbatim report (see `useCatalogRows`). Blocked routes withhold the price
 * honestly. Saved views ("my override queue", "DEFAULT-heavy", "price withheld")
 * are REAL client-side filters over the derived metrics. A row opens that part's
 * saved decision — the durable re-render of its FE-2 hero.
 *
 * Compact density is the default for this lens (a cost engineer scans many rows).
 * This surface only ever mounts under `NEXT_PUBLIC_STAGE_UI` (via LandingRouter),
 * so flag-off never ships it.
 */

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Calculator, Info } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import { procLabel, type Tone } from "@/lib/status";
import {
  SAVED_VIEWS,
  matchesSavedView,
  lifecycleRank,
  formatUnitUsd,
  type SavedViewId,
  type CatalogLifecycle,
} from "@/lib/catalog";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Button } from "@/components/ui/button";
import { Rise } from "@/components/ui/motion";
import { cn } from "@/lib/utils";
import { DoorCrossNav, DOOR_ICONS, type DoorNav } from "../DoorCrossNav";
import { useCatalogRows, type CatalogRow } from "./useCatalogRows";
import { PostureCell } from "./PostureCell";

/* ------------------------------------------------------------------ */
/*  Small presentation helpers                                        */
/* ------------------------------------------------------------------ */

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/** lifecycle → the shared status vocabulary (tone + label). */
const LIFECYCLE_BADGE: Record<CatalogLifecycle, { tone: Tone; label: string }> = {
  blocked: { tone: "fail", label: "Blocked" },
  assumption: { tone: "warn", label: "Assumption" },
  calibrated: { tone: "pass", label: "Calibrated" },
  overridden: { tone: "info", label: "Overridden" },
  validated: { tone: "pass", label: "Validated" },
  unknown: { tone: "neutral", label: "No cost" },
};

const CELL_SKELETON = <Skeleton className="h-4 w-16" />;

/** the DFM route-blocker count cell — real, route-scoped, never the full matrix. */
function RouteBlockersCell({ row }: { row: CatalogRow }) {
  if (row.hydration === "pending") return CELL_SKELETON;
  const m = row.metrics;
  if (!m || m.lifecycle === "unknown") {
    return <span className="text-subtle-foreground">—</span>;
  }
  const n = m.routeBlockerCount;
  const tone: Tone = m.blocked ? "fail" : n > 0 ? "warn" : "pass";
  const dot =
    tone === "fail" ? "bg-fail" : tone === "warn" ? "bg-warn" : "bg-pass";
  return (
    <span
      className="num inline-flex items-center justify-end gap-1.5"
      title={
        n > 0
          ? `${n} DFM blocker${n === 1 ? "" : "s"} on the recommended route (${procLabel(
              m.routeProcess ?? ""
            )})`
          : "No DFM blockers on the recommended route"
      }
    >
      <span className={cn("size-1.5 rounded-full", dot)} aria-hidden />
      {n}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Door                                                              */
/* ------------------------------------------------------------------ */

export function CatalogDoor({ nav }: { nav: DoorNav }) {
  const router = useRouter();
  const { status, error, rows, hydratingCount, hasMore, loadingMore, loadMore, retry } =
    useCatalogRows();
  const [view, setView] = useState<SavedViewId>("all");

  const open = (row: CatalogRow) => router.push(`/cost-decisions/${row.summary.id}`);

  // Per-view counts over HYDRATED rows only (an un-hydrated row isn't classified).
  const viewCounts = useMemo(() => {
    const counts: Record<SavedViewId, number> = {
      all: rows.length,
      override: 0,
      assumption: 0,
      blocked: 0,
    };
    for (const r of rows) {
      if (r.hydration !== "ready" || !r.metrics) continue;
      for (const v of SAVED_VIEWS) {
        if (v.id !== "all" && matchesSavedView(r.metrics, v.id)) counts[v.id]++;
      }
    }
    return counts;
  }, [rows]);

  const visible = useMemo(() => {
    if (view === "all") return rows;
    return rows.filter(
      (r) => r.hydration === "ready" && r.metrics && matchesSavedView(r.metrics, view)
    );
  }, [rows, view]);

  const columns = useMemo<ColumnDef<CatalogRow>[]>(
    () => [
      {
        id: "part",
        accessorFn: (r) => r.summary.label || r.summary.filename,
        header: "Part",
        cell: ({ row }) => {
          const s = row.original.summary;
          return (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                open(row.original);
              }}
              title={`Open ${s.label || s.filename}`}
              className="group/part flex min-w-0 max-w-[13rem] flex-col items-start rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="num truncate font-medium text-foreground group-hover/part:underline">
                {s.label || s.filename}
              </span>
              <span className="num text-[10px] uppercase tracking-wide text-subtle-foreground">
                {s.file_type}
              </span>
            </button>
          );
        },
      },
      {
        id: "route",
        accessorFn: (r) => r.metrics?.routeProcess ?? "",
        header: "Route",
        cell: ({ row }) => {
          const r = row.original;
          if (r.hydration === "pending") return CELL_SKELETON;
          const m = r.metrics;
          if (!m || !m.routeProcess) return <span className="text-subtle-foreground">—</span>;
          return (
            <div className="min-w-0">
              <span className="block truncate text-foreground">{procLabel(m.routeProcess)}</span>
              {m.routeMaterial && (
                <span className="num block truncate text-[10px] text-subtle-foreground">
                  {m.routeMaterial}
                </span>
              )}
            </div>
          );
        },
      },
      {
        id: "unit",
        accessorFn: (r) => r.metrics?.unitUsd ?? null,
        header: "Unit $",
        meta: { numeric: true },
        cell: ({ row }) => {
          const r = row.original;
          if (r.hydration === "pending") return CELL_SKELETON;
          const m = r.metrics;
          if (m?.blocked) {
            return (
              <StatusBadge
                tone="fail"
                label="Withheld"
                size="sm"
                title={m.withheldReason ?? "DFM-blocked route — price withheld"}
              />
            );
          }
          if (m?.unitUsd != null) {
            return <span className="font-medium text-foreground">{formatUnitUsd(m.unitUsd)}</span>;
          }
          return <span className="text-subtle-foreground">—</span>;
        },
      },
      {
        id: "dfm",
        accessorFn: (r) => r.metrics?.routeBlockerCount ?? -1,
        header: "DFM",
        meta: { numeric: true },
        cell: ({ row }) => <RouteBlockersCell row={row.original} />,
      },
      {
        id: "posture",
        accessorFn: (r) => r.metrics?.posture.groundedPct ?? -1,
        header: "Posture",
        cell: ({ row }) => {
          const r = row.original;
          if (r.hydration === "pending") return CELL_SKELETON;
          if (!r.metrics) return <span className="text-subtle-foreground">—</span>;
          return <PostureCell posture={r.metrics.posture} />;
        },
      },
      {
        id: "state",
        accessorFn: (r) => (r.metrics ? lifecycleRank(r.metrics.lifecycle) : -1),
        header: "State",
        cell: ({ row }) => {
          const r = row.original;
          if (r.hydration === "pending") return CELL_SKELETON;
          if (r.hydration === "error") {
            return (
              <span
                className="text-subtle-foreground"
                title="Couldn't load this decision's detail."
              >
                —
              </span>
            );
          }
          if (!r.metrics) return <span className="text-subtle-foreground">—</span>;
          const b = LIFECYCLE_BADGE[r.metrics.lifecycle];
          return <StatusBadge tone={b.tone} label={b.label} size="sm" />;
        },
      },
      {
        id: "when",
        accessorFn: (r) => r.summary.created_at,
        header: "When",
        meta: { numeric: true },
        cell: ({ row }) => (
          <span className="num text-muted-foreground">
            {relativeTime(row.original.summary.created_at)}
          </span>
        ),
      },
    ],
    // `open` is stable enough (router identity); columns don't depend on state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const Icon = DOOR_ICONS.cost;

  return (
    <div className="flex h-full min-h-full flex-col p-6">
      <DoorCrossNav nav={nav} />

      <div className="mx-auto w-full max-w-6xl space-y-5 py-6">
        <Rise>
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-lg)] bg-muted text-muted-foreground">
              <Icon className="size-4" />
            </span>
            <div>
              <span className="num cv-eyebrow text-accent-text">I own the numbers · OVERRIDE</span>
              <h1 className="mt-1 text-display font-semibold tracking-tight text-foreground">
                Your cost catalog
              </h1>
              <p className="mt-1 max-w-prose text-sm text-muted-foreground">
                Every saved should-cost decision in one governed table — route, unit price,
                DFM and the provenance posture behind each number. A row opens that part&apos;s
                saved decision.
              </p>
            </div>
          </div>
        </Rise>

        {status === "loading" && (
          <Rise delay={80}>
            <GridSkeleton />
          </Rise>
        )}

        {status === "error" && (
          <Rise delay={80}>
            <ErrorState
              title="Couldn't load your cost catalog"
              message={error ?? undefined}
              onRetry={retry}
            />
          </Rise>
        )}

        {status === "ready" && rows.length === 0 && (
          <Rise delay={80}>
            <EmptyState
              icon={Calculator}
              title="No saved cost decisions yet"
              description="Cost a part and save the decision — it lands here as a catalog row you can sort, filter and re-open."
              action={<Button onClick={() => nav.onGoDoor("part")}>Drop a part to cost</Button>}
            />
          </Rise>
        )}

        {status === "ready" && rows.length > 0 && (
          <Rise delay={80}>
            <div className="space-y-3">
              {/* saved-view filters (real client-side filters over the fetched rows) */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="cv-eyebrow mr-1">Saved views</span>
                {SAVED_VIEWS.map((v) => {
                  const activeView = v.id === view;
                  return (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => setView(v.id)}
                      title={v.description}
                      aria-pressed={activeView}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-[var(--radius)] border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        activeView
                          ? "border-accent-text/40 bg-accent-subtle text-foreground"
                          : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      {v.label}
                      <span className="num text-[10px] text-subtle-foreground">
                        {viewCounts[v.id]}
                      </span>
                    </button>
                  );
                })}
                {hydratingCount > 0 && (
                  <span className="num inline-flex items-center gap-1.5 text-[11px] text-subtle-foreground">
                    <span className="size-1.5 animate-pulse rounded-full bg-accent-text" aria-hidden />
                    hydrating {hydratingCount}…
                  </span>
                )}
              </div>

              {visible.length > 0 ? (
                <DataTable
                  columns={columns}
                  data={visible}
                  density="compact"
                  onRowClick={open}
                />
              ) : (
                <p className="rounded-[var(--radius)] border border-dashed border-border px-3 py-6 text-center text-sm text-subtle-foreground">
                  {hydratingCount > 0
                    ? `No parts classified into this view yet — ${hydratingCount} still loading.`
                    : "No parts match this view."}
                </p>
              )}

              {hasMore && (
                <div className="text-center">
                  <Button variant="secondary" size="sm" loading={loadingMore} onClick={loadMore}>
                    Load more
                  </Button>
                </div>
              )}

              {/* Honest gap note — the findings column and the per-row hydration. */}
              <div className="flex items-start gap-2 rounded-[var(--radius)] border border-dashed border-border bg-card/50 px-3 py-2.5 text-xs leading-relaxed text-subtle-foreground">
                <Info className="mt-0.5 size-3.5 shrink-0" />
                <p>
                  Unit $, posture and state are read from each saved decision on open; the
                  one-call governed-catalog aggregate lands in{" "}
                  <span className="text-muted-foreground">Phase 1</span>. DFM counts the blockers
                  on the recommended route (real, route-scoped) — a full findings count across the
                  DFM analysis needs that analysis joined to the decision, a backend item shown
                  blank here rather than faked.
                </p>
              </div>
            </div>
          </Rise>
        )}
      </div>
    </div>
  );
}

function GridSkeleton() {
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-24" />
        ))}
      </div>
      <div className="overflow-hidden rounded-[var(--radius)] border border-border">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-0">
            {Array.from({ length: 7 }).map((_, c) => (
              <Skeleton key={c} className="h-4 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
