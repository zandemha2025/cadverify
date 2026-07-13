"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import {
  analysisPageHref,
  getBatchItems,
  type BatchItem,
} from "@/lib/api/batch";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";

const STATUS_FILTERS = [
  "all",
  "pending",
  "processing",
  "completed",
  "failed",
  "skipped",
];

interface Props {
  batchId: string;
  /** Trigger a refresh by changing this key. */
  refreshKey?: number;
}

export default function BatchItemsTable({ batchId, refreshKey }: Props) {
  const [items, setItems] = useState<BatchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());

  const fetchItems = useCallback(
    async (cursor?: string) => {
      try {
        const resp = await getBatchItems(batchId, {
          status: statusFilter === "all" ? undefined : statusFilter,
          cursor,
          limit: 50,
        });
        setItems((prev) => (cursor ? [...prev, ...resp.items] : resp.items));
        setNextCursor(resp.next_cursor);
        setHasMore(resp.has_more);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load items");
      }
    },
    [batchId, statusFilter],
  );

  // Initial load + filter change
  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchItems().finally(() => setLoading(false));
  }, [fetchItems, refreshKey]);

  const loadMore = async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    await fetchItems(nextCursor);
    setLoadingMore(false);
  };

  const toggleError = useCallback((itemId: string) => {
    setExpandedErrors((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }, []);

  const columns = useMemo<ColumnDef<BatchItem>[]>(
    () => [
      {
        accessorKey: "filename",
        header: "Filename",
        cell: ({ row }) => {
          const item = row.original;
          const expanded = expandedErrors.has(item.item_ulid);
          return (
            <div className="max-w-[280px]">
              <p className="truncate font-medium text-foreground">
                {item.filename}
              </p>
              {item.error_message && expanded && (
                <p className="mt-1 whitespace-pre-wrap text-xs text-fail">
                  {item.error_message}
                </p>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} size="sm" />,
      },
      {
        accessorKey: "priority",
        header: "Priority",
        meta: { numeric: true },
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.priority}</span>
        ),
      },
      {
        accessorKey: "duration_ms",
        header: "Duration",
        meta: { numeric: true },
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.duration_ms != null
              ? `${(row.original.duration_ms / 1000).toFixed(1)} s`
              : "—"}
          </span>
        ),
      },
      {
        id: "result",
        header: "Result",
        cell: ({ row }) => {
          const item = row.original;
          if (!item.analysis_url) return <span className="text-muted-foreground">—</span>;
          return (
            <div className="text-xs leading-5">
              <p className="font-medium text-foreground">{item.verdict ?? "—"}</p>
              <p className="text-muted-foreground">
                {item.best_process ?? "No best process"} · {item.issue_count ?? "—"} issues
              </p>
            </div>
          );
        },
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => {
          const item = row.original;
          const analysisHref = analysisPageHref(item.analysis_url);
          return (
            <div className="flex items-center justify-end gap-1">
              {analysisHref && (
                <Button asChild variant="ghost" size="sm">
                  <Link href={analysisHref}>View</Link>
                </Button>
              )}
              {item.error_message && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-fail hover:text-fail"
                  onClick={() => toggleError(item.item_ulid)}
                >
                  {expandedErrors.has(item.item_ulid)
                    ? "Hide error"
                    : "Show error"}
                </Button>
              )}
            </div>
          );
        },
      },
    ],
    [expandedErrors, toggleError],
  );

  return (
    <div className="space-y-3">
      {/* Status filter */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">Filter</span>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTERS.map((f) => (
              <SelectItem key={f} value={f} className="capitalize">
                {f === "all" ? "All statuses" : f}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {error && (
        <ErrorState
          message={error}
          onRetry={() => {
            setError(null);
            setLoading(true);
            fetchItems().finally(() => setLoading(false));
          }}
        />
      )}

      <DataTable
        columns={columns}
        data={items}
        loading={loading}
        emptyState={
          <EmptyState
            title="No items found"
            description="No items match this filter."
          />
        }
      />

      {hasMore && (
        <div className="text-center">
          <Button
            variant="secondary"
            size="sm"
            loading={loadingMore}
            onClick={loadMore}
          >
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
