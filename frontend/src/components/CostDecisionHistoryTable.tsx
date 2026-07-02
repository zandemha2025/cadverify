"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Calculator } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import type {
  CostDecisionSummary,
  CostDecisionsPage,
  RateLimits,
} from "@/lib/api";
import { fetchCostDecisions } from "@/lib/api";
import { procLabel } from "@/lib/status";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";

const MAX_LOADED_ITEMS = 500;

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

interface Props {
  onRateLimitsUpdate?: (limits: RateLimits | undefined) => void;
}

export default function CostDecisionHistoryTable({ onRateLimitsUpdate }: Props) {
  const router = useRouter();
  const [items, setItems] = useState<CostDecisionSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPage = useCallback(
    async (nextCursor?: string, reset?: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const page: CostDecisionsPage = await fetchCostDecisions({
          cursor: nextCursor,
          limit: 20,
        });
        setItems((prev) =>
          reset ? page.cost_decisions : [...prev, ...page.cost_decisions]
        );
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
        onRateLimitsUpdate?.(page.rateLimits);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load cost decisions");
      } finally {
        setLoading(false);
        setInitialized(true);
      }
    },
    [onRateLimitsUpdate]
  );

  // Initial load.
  if (!initialized && !loading) {
    loadPage(undefined, true);
  }

  const columns = useMemo<ColumnDef<CostDecisionSummary>[]>(
    () => [
      {
        accessorKey: "filename",
        header: "File",
        cell: ({ row }) => (
          <span className="font-medium text-foreground">
            {row.original.label || row.original.filename}
          </span>
        ),
      },
      {
        accessorKey: "make_now_process",
        header: "Make now",
        cell: ({ row }) =>
          row.original.make_now_process
            ? procLabel(row.original.make_now_process)
            : "—",
      },
      {
        accessorKey: "crossover_qty",
        header: "Crossover",
        meta: { numeric: true },
        cell: ({ row }) =>
          row.original.crossover_qty != null
            ? Math.round(row.original.crossover_qty).toLocaleString()
            : "—",
      },
      {
        accessorKey: "quantities",
        header: "Quantities",
        cell: ({ row }) =>
          row.original.quantities?.length
            ? row.original.quantities.map((q) => q.toLocaleString()).join(", ")
            : "—",
      },
      {
        accessorKey: "is_public",
        header: "Shared",
        cell: ({ row }) =>
          row.original.is_public ? (
            <StatusBadge tone="pass" label="Shared" size="sm" />
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        accessorKey: "created_at",
        header: "When",
        meta: { numeric: true },
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {relativeTime(row.original.created_at)}
          </span>
        ),
      },
    ],
    []
  );

  const atCapacity = items.length >= MAX_LOADED_ITEMS;

  return (
    <div className="space-y-3">
      {error && (
        <ErrorState message={error} onRetry={() => loadPage(undefined, true)} />
      )}

      <DataTable
        columns={columns}
        data={items}
        loading={loading && items.length === 0}
        onRowClick={(row) => router.push(`/cost-decisions/${row.id}`)}
        emptyState={
          initialized && !error ? (
            <EmptyState
              icon={Calculator}
              title="No saved cost decisions yet"
              description="Cost a part in the instrument and it will be saved here."
              action={
                <Button onClick={() => router.push("/cost")}>
                  Cost a part
                </Button>
              }
            />
          ) : undefined
        }
      />

      {hasMore && initialized && items.length > 0 && (
        <div className="text-center">
          {atCapacity ? (
            <p className="text-sm text-muted-foreground">
              {items.length} decisions loaded.
            </p>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              loading={loading}
              onClick={() => loadPage(cursor ?? undefined)}
            >
              Load more
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
