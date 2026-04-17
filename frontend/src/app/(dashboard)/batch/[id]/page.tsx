"use client";

import { use, useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import BatchProgressBar from "@/components/batch/BatchProgressBar";
import BatchItemsTable from "@/components/batch/BatchItemsTable";
import {
  cancelBatch,
  downloadBatchCsv,
  type BatchProgress,
} from "@/lib/api/batch";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

export default function BatchDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: batchId } = use(params);
  const router = useRouter();
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const isTerminal = progress ? TERMINAL_STATUSES.has(progress.status) : false;
  const isCompleted = progress?.status === "completed" || progress?.status === "failed";

  const handleCancel = async () => {
    if (!confirm("Cancel this batch? Pending items will be skipped.")) return;
    setCancelling(true);
    try {
      await cancelBatch(batchId);
      toast.success("Batch cancelled");
      setRefreshKey((k) => k + 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel");
    } finally {
      setCancelling(false);
    }
  };

  const handleCsvDownload = async () => {
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

  const handleProgressUpdate = useCallback((p: BatchProgress) => {
    setProgress(p);
  }, []);

  return (
    <main className="space-y-6">
      {/* Nav */}
      <button
        type="button"
        onClick={() => router.push("/batch")}
        className="text-sm text-blue-600 hover:underline"
      >
        &larr; Back to batches
      </button>

      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">
          Batch{" "}
          <span className="font-mono text-lg text-gray-500">
            {batchId.slice(0, 12)}
          </span>
        </h1>
        <div className="flex gap-2">
          {!isTerminal && (
            <button
              type="button"
              onClick={handleCancel}
              disabled={cancelling}
              className="rounded-md bg-red-50 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-50"
            >
              {cancelling ? "Cancelling..." : "Cancel Batch"}
            </button>
          )}
          {isCompleted && (
            <button
              type="button"
              onClick={handleCsvDownload}
              className="rounded-md bg-green-50 px-3 py-1.5 text-sm font-medium text-green-700 hover:bg-green-100"
            >
              Download CSV
            </button>
          )}
        </div>
      </div>

      {/* Progress */}
      <BatchProgressBar
        batchId={batchId}
        onProgressUpdate={handleProgressUpdate}
      />

      {/* Items table */}
      <section>
        <h2 className="mb-2 text-lg font-medium text-gray-700">Items</h2>
        <BatchItemsTable batchId={batchId} refreshKey={refreshKey} />
      </section>
    </main>
  );
}
