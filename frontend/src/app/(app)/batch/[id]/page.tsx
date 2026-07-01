"use client";

import { use, useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import BatchProgressBar from "@/components/batch/BatchProgressBar";
import BatchItemsTable from "@/components/batch/BatchItemsTable";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { AlertDialog } from "@/components/ui/alert-dialog";
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
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const isTerminal = progress ? TERMINAL_STATUSES.has(progress.status) : false;
  const isCompleted =
    progress?.status === "completed" || progress?.status === "failed";

  const doCancel = async () => {
    setCancelling(true);
    try {
      await cancelBatch(batchId);
      toast.success("Batch cancelled");
      setRefreshKey((k) => k + 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel");
    } finally {
      setCancelling(false);
      setConfirmOpen(false);
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
    <div className="space-y-6">
      <Button
        variant="ghost"
        size="sm"
        className="-ml-3"
        onClick={() => router.push("/batch")}
      >
        <ArrowLeft /> Back to batches
      </Button>

      <PageHeader
        title={
          <span className="flex items-baseline gap-2">
            Batch
            <span className="num text-base font-normal text-muted-foreground">
              {batchId.slice(0, 12)}
            </span>
          </span>
        }
        actions={
          <>
            {!isTerminal && (
              <Button
                variant="destructive"
                size="sm"
                loading={cancelling}
                onClick={() => setConfirmOpen(true)}
              >
                Cancel batch
              </Button>
            )}
            {isCompleted && (
              <Button variant="secondary" size="sm" onClick={handleCsvDownload}>
                Download CSV
              </Button>
            )}
          </>
        }
      />

      <BatchProgressBar batchId={batchId} onProgressUpdate={handleProgressUpdate} />

      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Items
        </h2>
        <BatchItemsTable batchId={batchId} refreshKey={refreshKey} />
      </section>

      <AlertDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Cancel this batch?"
        description="Pending items will be skipped. This cannot be undone."
        confirmLabel="Cancel batch"
        cancelLabel="Keep running"
        loading={cancelling}
        onConfirm={doCancel}
      />
    </div>
  );
}
