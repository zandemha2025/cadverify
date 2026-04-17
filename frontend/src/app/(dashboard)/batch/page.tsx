"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import BatchUploadForm from "@/components/batch/BatchUploadForm";
import {
  downloadBatchCsv,
  listBatches,
  type BatchSummaryRow,
} from "@/lib/api/batch";

const STATUS_BADGES: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  extracting: "bg-yellow-100 text-yellow-800",
  processing: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-200 text-gray-600",
};

export default function BatchListPage() {
  const [batches, setBatches] = useState<BatchSummaryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const fetchBatches = useCallback(async (cursor?: string) => {
    try {
      const resp = await listBatches({ cursor, limit: 20 });
      if (cursor) {
        setBatches((prev) => [...prev, ...resp.batches]);
      } else {
        setBatches(resp.batches);
      }
      setNextCursor(resp.next_cursor);
      setHasMore(resp.has_more);
    } catch {
      // silent -- table will be empty
    }
  }, []);

  useEffect(() => {
    fetchBatches().finally(() => setLoading(false));
  }, [fetchBatches]);

  const handleCsvDownload = async (batchId: string) => {
    try {
      const blob = await downloadBatchCsv(batchId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `batch_${batchId}_results.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "CSV download failed");
    }
  };

  return (
    <main className="space-y-8">
      <h1 className="text-2xl font-semibold">Batch Processing</h1>

      {/* Upload form */}
      <section className="rounded-md border p-6">
        <h2 className="mb-4 text-lg font-medium text-gray-700">
          New Batch
        </h2>
        <BatchUploadForm />
      </section>

      {/* Recent batches */}
      <section>
        <h2 className="mb-2 text-lg font-medium text-gray-700">
          Recent Batches
        </h2>

        {loading ? (
          <div className="animate-pulse py-6 text-center text-sm text-gray-400">
            Loading...
          </div>
        ) : batches.length === 0 ? (
          <div className="rounded-md border py-6 text-center text-sm text-gray-500">
            No batches yet. Upload a ZIP file above to get started.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left text-sm">
              <thead className="border-b bg-gray-50 text-xs font-medium uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-2">Batch ID</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Items</th>
                  <th className="px-4 py-2">Created</th>
                  <th className="px-4 py-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {batches.map((b) => (
                  <tr key={b.batch_ulid} className="hover:bg-gray-50">
                    <td className="px-4 py-2">
                      <Link
                        href={`/batch/${b.batch_ulid}`}
                        className="font-mono text-xs text-blue-600 hover:underline"
                      >
                        {b.batch_ulid.slice(0, 12)}...
                      </Link>
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGES[b.status] || "bg-gray-100 text-gray-700"}`}
                      >
                        {b.status}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-600">
                      {b.completed_items}/{b.total_items}
                      {b.failed_items > 0 && (
                        <span className="ml-1 text-red-500">
                          ({b.failed_items} failed)
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500">
                      {b.created_at
                        ? new Date(b.created_at).toLocaleString()
                        : "-"}
                    </td>
                    <td className="px-4 py-2">
                      {(b.status === "completed" || b.status === "failed") && (
                        <button
                          type="button"
                          onClick={() => handleCsvDownload(b.batch_ulid)}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Download CSV
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {hasMore && (
          <div className="mt-3 text-center">
            <button
              type="button"
              onClick={() => {
                if (nextCursor) fetchBatches(nextCursor);
              }}
              className="rounded-md bg-gray-100 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200"
            >
              Load More
            </button>
          </div>
        )}
      </section>
    </main>
  );
}
