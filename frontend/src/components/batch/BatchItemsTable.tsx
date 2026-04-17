"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getBatchItems, type BatchItem } from "@/lib/api/batch";

const STATUS_BADGES: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  queued: "bg-gray-100 text-gray-700",
  processing: "bg-yellow-100 text-yellow-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  skipped: "bg-gray-200 text-gray-500",
};

const STATUS_FILTERS = ["all", "pending", "processing", "completed", "failed", "skipped"];

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
        if (cursor) {
          setItems((prev) => [...prev, ...resp.items]);
        } else {
          setItems(resp.items);
        }
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

  const toggleError = (itemId: string) => {
    setExpandedErrors((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) {
        next.delete(itemId);
      } else {
        next.add(itemId);
      }
      return next;
    });
  };

  return (
    <div className="space-y-3">
      {/* Status filter */}
      <div className="flex gap-1">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setStatusFilter(f)}
            className={`rounded px-3 py-1 text-xs font-medium capitalize transition-colors ${
              statusFilter === f
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="animate-pulse py-8 text-center text-sm text-gray-400">
          Loading items...
        </div>
      ) : items.length === 0 ? (
        <div className="py-8 text-center text-sm text-gray-500">
          No items found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-left text-sm">
            <thead className="border-b bg-gray-50 text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-2">Filename</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Priority</th>
                <th className="px-4 py-2">Duration</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((item) => (
                <tr key={item.item_ulid} className="hover:bg-gray-50">
                  <td className="max-w-[200px] truncate px-4 py-2 font-medium">
                    {item.filename}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGES[item.status] || "bg-gray-100 text-gray-700"}`}
                    >
                      {item.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {item.priority}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {item.duration_ms != null
                      ? `${(item.duration_ms / 1000).toFixed(1)}s`
                      : "-"}
                  </td>
                  <td className="px-4 py-2">
                    {item.analysis_id != null && (
                      <Link
                        href={`/analyses/${item.analysis_id}`}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        View Analysis
                      </Link>
                    )}
                    {item.error_message && (
                      <button
                        type="button"
                        onClick={() => toggleError(item.item_ulid)}
                        className="ml-2 text-xs text-red-600 hover:underline"
                      >
                        {expandedErrors.has(item.item_ulid) ? "Hide Error" : "Show Error"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {/* Expanded error rows */}
              {items
                .filter(
                  (item) =>
                    item.error_message && expandedErrors.has(item.item_ulid),
                )
                .map((item) => (
                  <tr key={`${item.item_ulid}-error`} className="bg-red-50">
                    <td colSpan={5} className="px-4 py-2 text-xs text-red-700">
                      {item.error_message}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Load more */}
      {hasMore && (
        <div className="text-center">
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className="rounded-md bg-gray-100 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200 disabled:opacity-50"
          >
            {loadingMore ? "Loading..." : "Load More"}
          </button>
        </div>
      )}
    </div>
  );
}
