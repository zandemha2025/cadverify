"use client";

/**
 * CatalogDoor — Door B's landing (D5 FE-4): the cost / sourcing engineer's grid
 * over their org's REAL parts×decisions, served by the org-scoped `/catalog`
 * endpoint (backend `src/api/catalog.py`). Not an invented table and not a client
 * join — ONE call paints every cell, each read verbatim off the engine's own
 * serialization:
 *
 *   Part · Route · Unit $ · Findings · Posture · State · When
 *
 * Findings is the REAL route-scoped DFM count (severity-bucketed); posture is the
 * server-derived provenance mix; unit $ is WITHHELD honestly on a DFM-blocked
 * route; state is the real Drafted/Costed lifecycle. A part with no DFM analysis
 * shows an honest "—" for findings (unknown, never faked zero). A row opens that
 * part's hero — the saved decision when costed, the analysis when drafted.
 *
 * The facet filters (state · route · has-findings) map to the endpoint's real
 * query params and are applied SERVER-SIDE before pagination, so the row count
 * and the page are always consistent. Compact density is the default for this
 * lens (a cost engineer scans many rows). This surface only ever mounts under
 * `NEXT_PUBLIC_STAGE_UI` (via LandingRouter), so flag-off never ships it.
 */

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { Calculator, Info } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import { procLabel, type Tone } from "@/lib/status";
import { formatUnitUsd } from "@/lib/catalog";
import {
  routeFacets,
  stateFacetCount,
  hasActiveFilters,
  type CatalogItem,
} from "@/lib/catalog-api";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Button } from "@/components/ui/button";
import { Rise } from "@/components/ui/motion";
import { cn } from "@/lib/utils";
import { DoorCrossNav, DOOR_ICONS, type DoorNav } from "../DoorCrossNav";
import { useCatalog } from "./useCatalogRows";
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

/** lifecycle_state → the shared status vocabulary. Drafted = analysis only, no
 *  price yet; Costed = a saved should-cost decision exists. */
const STATE_BADGE: Record<CatalogItem["lifecycleState"], { tone: Tone; label: string }> = {
  Costed: { tone: "info", label: "Costed" },
  Drafted: { tone: "neutral", label: "Drafted" },
};

/** A generic facet chip (label + count + active state). */
function FacetChip({
  label,
  count,
  active,
  onClick,
  title,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[var(--radius)] border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-accent-text/40 bg-accent-subtle text-foreground"
          : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {label}
      {count != null && (
        <span className="num text-[10px] text-subtle-foreground">{count}</span>
      )}
    </button>
  );
}

/** The route-scoped DFM findings cell — real, severity-bucketed, from /catalog. */
function FindingsCell({ item }: { item: CatalogItem }) {
  const f = item.findings;
  if (!f) {
    return (
      <span
        className="text-subtle-foreground"
        title="No DFM analysis for this part yet — findings are unknown, not zero."
      >
        —
      </span>
    );
  }
  if (f.total === 0) {
    return (
      <span
        className="num inline-flex items-center justify-end gap-1.5 text-pass"
        title={`No DFM findings on the recommended route (${procLabel(f.scopedProcess)})`}
      >
        <span className="size-1.5 rounded-full bg-pass" aria-hidden />0
      </span>
    );
  }
  const tone: Tone = f.critical > 0 ? "fail" : "warn";
  const dot = tone === "fail" ? "bg-fail" : "bg-warn";
  const bits: string[] = [];
  if (f.critical) bits.push(`${f.critical} critical`);
  if (f.advisory) bits.push(`${f.advisory} advisory`);
  if (f.info) bits.push(`${f.info} info`);
  return (
    <span
      className="num inline-flex items-center justify-end gap-1.5"
      title={`${f.total} route-scoped DFM finding${f.total === 1 ? "" : "s"} (${procLabel(
        f.scopedProcess
      )}) — ${bits.join(", ")}`}
    >
      <span className={cn("size-1.5 rounded-full", dot)} aria-hidden />
      {f.total}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Door                                                              */
/* ------------------------------------------------------------------ */

export function CatalogDoor({ nav }: { nav: DoorNav }) {
  const router = useRouter();
  const {
    status,
    error,
    rows,
    facets,
    pagination,
    truncated,
    filters,
    page,
    setStateFacet,
    setRouteFacet,
    setHasFindingsFacet,
    clearFilters,
    setPage,
    retry,
  } = useCatalog();

  const open = (item: CatalogItem) => {
    if (item.href) router.push(item.href);
  };

  const routes = useMemo(() => (facets ? routeFacets(facets) : []), [facets]);

  const columns = useMemo<ColumnDef<CatalogItem>[]>(
    () => [
      {
        id: "part",
        accessorFn: (r) => r.filename,
        header: "Part",
        cell: ({ row }) => {
          const s = row.original;
          return (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                open(s);
              }}
              disabled={!s.href}
              title={s.href ? `Open ${s.filename}` : s.filename}
              className="group/part flex min-w-0 max-w-[13rem] flex-col items-start rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default"
            >
              <span className="num truncate font-medium text-foreground group-hover/part:underline group-disabled/part:no-underline">
                {s.filename}
              </span>
              <span className="num text-[10px] uppercase tracking-wide text-subtle-foreground">
                {s.fileType}
              </span>
            </button>
          );
        },
      },
      {
        id: "route",
        accessorFn: (r) => r.routeProcess ?? "",
        header: "Route",
        cell: ({ row }) => {
          const r = row.original;
          if (!r.routeProcess) return <span className="text-subtle-foreground">—</span>;
          return (
            <div className="min-w-0">
              <span className="flex items-center gap-1.5">
                <span className="truncate text-foreground">{procLabel(r.routeProcess)}</span>
                {r.routeSource === "dfm" && (
                  <span
                    className="num shrink-0 rounded-sm bg-muted px-1 text-[9px] uppercase tracking-wide text-subtle-foreground"
                    title="DFM-recommended route — this part has not been costed yet."
                  >
                    DFM
                  </span>
                )}
              </span>
              {r.routeMaterial && (
                <span className="num block truncate text-[10px] text-subtle-foreground">
                  {r.routeMaterial}
                </span>
              )}
            </div>
          );
        },
      },
      {
        id: "unit",
        accessorFn: (r) => r.unitCost?.usd ?? null,
        header: "Unit $",
        meta: { numeric: true },
        cell: ({ row }) => {
          const uc = row.original.unitCost;
          if (!uc) return <span className="text-subtle-foreground" title="Not costed yet.">—</span>;
          if (uc.withheld) {
            return (
              <StatusBadge
                tone="fail"
                label="Withheld"
                size="sm"
                title={uc.withheldReason ?? "DFM-blocked route — price withheld"}
              />
            );
          }
          if (uc.usd != null) {
            return (
              <span
                className="font-medium text-foreground"
                title={uc.qty != null ? `Unit price at qty ${uc.qty}` : undefined}
              >
                {formatUnitUsd(uc.usd)}
              </span>
            );
          }
          return <span className="text-subtle-foreground">—</span>;
        },
      },
      {
        id: "findings",
        accessorFn: (r) => r.findings?.total ?? -1,
        header: "Findings",
        meta: { numeric: true },
        cell: ({ row }) => <FindingsCell item={row.original} />,
      },
      {
        id: "posture",
        accessorFn: (r) => r.posture?.groundedPct ?? -1,
        header: "Posture",
        cell: ({ row }) => {
          const p = row.original.posture;
          if (!p) return <span className="text-subtle-foreground">—</span>;
          return <PostureCell posture={p} />;
        },
      },
      {
        id: "state",
        accessorFn: (r) => r.lifecycleState,
        header: "State",
        cell: ({ row }) => {
          const b = STATE_BADGE[row.original.lifecycleState];
          return <StatusBadge tone={b.tone} label={b.label} size="sm" />;
        },
      },
      {
        id: "when",
        accessorFn: (r) => r.updatedAt,
        header: "When",
        meta: { numeric: true },
        cell: ({ row }) => (
          <span className="num text-muted-foreground">
            {relativeTime(row.original.updatedAt)}
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const Icon = DOOR_ICONS.cost;
  const filtered = hasActiveFilters(filters);
  const total = pagination?.total ?? 0;
  const totalPages = pagination?.total_pages ?? 0;

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
                Every part in your organization in one governed table — route, unit price,
                route-scoped DFM findings and the provenance posture behind each number, served
                org-scoped. A row opens that part&apos;s hero.
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

        {status === "ready" && total === 0 && !filtered && (
          <Rise delay={80}>
            <EmptyState
              icon={Calculator}
              title="No parts in your catalog yet"
              description="Analyze or cost a part — it lands here as a catalog row you can filter, page through and re-open."
              action={<Button onClick={() => nav.onGoDoor("part")}>Drop a part</Button>}
            />
          </Rise>
        )}

        {status === "ready" && (total > 0 || filtered) && facets && (
          <Rise delay={80}>
            <div className="space-y-3">
              {/* facet filters — mapped to the endpoint's REAL query params */}
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="cv-eyebrow mr-1">State</span>
                  <FacetChip
                    label="All"
                    active={filters.state === null}
                    onClick={() => setStateFacet(null)}
                  />
                  <FacetChip
                    label="Costed"
                    count={stateFacetCount(facets, "Costed")}
                    active={filters.state === "Costed"}
                    onClick={() =>
                      setStateFacet(filters.state === "Costed" ? null : "Costed")
                    }
                  />
                  <FacetChip
                    label="Drafted"
                    count={stateFacetCount(facets, "Drafted")}
                    active={filters.state === "Drafted"}
                    onClick={() =>
                      setStateFacet(filters.state === "Drafted" ? null : "Drafted")
                    }
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <span className="cv-eyebrow mr-1">Findings</span>
                  <FacetChip
                    label="Any"
                    active={filters.hasFindings === null}
                    onClick={() => setHasFindingsFacet(null)}
                  />
                  <FacetChip
                    label="Has findings"
                    count={facets.findings.with_findings}
                    active={filters.hasFindings === true}
                    onClick={() =>
                      setHasFindingsFacet(filters.hasFindings === true ? null : true)
                    }
                  />
                  <FacetChip
                    label="Clean"
                    count={facets.findings.without_findings}
                    active={filters.hasFindings === false}
                    onClick={() =>
                      setHasFindingsFacet(filters.hasFindings === false ? null : false)
                    }
                  />
                  {facets.findings.unknown > 0 && (
                    <span
                      className="num text-[11px] text-subtle-foreground"
                      title="Parts with no DFM analysis — findings unknown, so they match neither filter."
                    >
                      · {facets.findings.unknown} unknown
                    </span>
                  )}
                </div>

                {routes.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="cv-eyebrow mr-1">Route</span>
                    <FacetChip
                      label="All"
                      active={filters.route === null}
                      onClick={() => setRouteFacet(null)}
                    />
                    {routes.map((rf) => (
                      <FacetChip
                        key={rf.process}
                        label={procLabel(rf.process)}
                        count={rf.count}
                        active={filters.route === rf.process}
                        onClick={() =>
                          setRouteFacet(filters.route === rf.process ? null : rf.process)
                        }
                      />
                    ))}
                  </div>
                )}
              </div>

              {rows.length > 0 ? (
                <DataTable
                  columns={columns}
                  data={rows}
                  density="compact"
                  onRowClick={open}
                />
              ) : (
                <div className="rounded-[var(--radius)] border border-dashed border-border px-3 py-8 text-center">
                  <p className="text-sm text-subtle-foreground">No parts match these filters.</p>
                  <Button variant="secondary" size="sm" className="mt-3" onClick={clearFilters}>
                    Clear filters
                  </Button>
                </div>
              )}

              {/* pagination — real total, offset pages, honest has_more */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between gap-3 pt-1">
                  <span className="num text-xs text-subtle-foreground">
                    Page {page} of {totalPages} · {total} part{total === 1 ? "" : "s"}
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage(page - 1)}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={!pagination?.has_more}
                      onClick={() => setPage(page + 1)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}

              {truncated && (
                <div className="flex items-start gap-2 rounded-[var(--radius)] border border-dashed border-border bg-card/50 px-3 py-2.5 text-xs leading-relaxed text-subtle-foreground">
                  <Info className="mt-0.5 size-3.5 shrink-0" />
                  <p>
                    Your catalog exceeded the scan window, so the oldest parts aren&apos;t shown
                    here. Narrow the filters or page through the saved decisions to inspect the
                    rows outside this bounded view.
                  </p>
                </div>
              )}
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
