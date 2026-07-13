"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Layers } from "lucide-react";
import { toast } from "sonner";
import type { ColumnDef } from "@tanstack/react-table";
import BatchUploadForm from "@/components/batch/BatchUploadForm";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import {
  downloadBatchCsv,
  listBatches,
  type BatchSummaryRow,
} from "@/lib/api/batch";

export default function BatchListPage() {
  const router = useRouter();
  const [batches, setBatches] = useState<BatchSummaryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBatches = useCallback(async (cursor?: string) => {
    try {
      const resp = await listBatches({ cursor, limit: 20 });
      setBatches((prev) => (cursor ? [...prev, ...resp.batches] : resp.batches));
      setNextCursor(resp.next_cursor);
      setHasMore(resp.has_more);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load batches.");
    }
  }, []);

  useEffect(() => {
    fetchBatches().finally(() => setLoading(false));
  }, [fetchBatches]);

  const handleCsvDownload = useCallback(async (batchId: string) => {
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
  }, []);

  const columns = useMemo<ColumnDef<BatchSummaryRow>[]>(
    () => [
      {
        accessorKey: "batch_ulid",
        header: "Batch ID",
        cell: ({ row }) => (
          <span className="num text-xs text-primary">
            {row.original.batch_ulid.slice(0, 12)}…
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} size="sm" />,
      },
      {
        id: "items",
        header: "Items",
        meta: { numeric: true },
        cell: ({ row }) => {
          const b = row.original;
          return (
            <span>
              {b.completed_items}/{b.total_items}
              {b.failed_items > 0 && (
                <span className="ml-1 text-fail">
                  ({b.failed_items} failed)
                </span>
              )}
            </span>
          );
        },
      },
      {
        accessorKey: "created_at",
        header: "Created",
        meta: { numeric: true },
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.created_at
              ? new Date(row.original.created_at).toLocaleString()
              : "—"}
          </span>
        ),
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => {
          const b = row.original;
          if (b.status !== "completed" && b.status !== "failed") return null;
          return (
            <div className="flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCsvDownload(b.batch_ulid);
                }}
              >
                Download CSV
              </Button>
            </div>
          );
        },
      },
    ],
    [handleCsvDownload],
  );

  return (
    <div className="space-y-8">
      <PageHeader
        title="Batch"
        subtitle="Run DFM analysis across many parts at once."
      />

      <Card>
        <CardHeader>
          <CardTitle>New batch</CardTitle>
        </CardHeader>
        <CardContent>
          <BatchUploadForm />
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Recent batches
        </h2>
        {error && (
          <ErrorState
            title="Could not load recent batches"
            message={error}
            onRetry={() => {
              setError(null);
              setLoading(true);
              fetchBatches().finally(() => setLoading(false));
            }}
          />
        )}
        {(!error || batches.length > 0) && (
          <DataTable
            columns={columns}
            data={batches}
            loading={loading}
            onRowClick={(row) => router.push(`/batch/${row.batch_ulid}`)}
            emptyState={
              <EmptyState
                icon={Layers}
                title="No batches yet"
                description="Upload a ZIP file above to analyze many parts at once."
              />
            }
          />
        )}
        {hasMore && (
          <div className="text-center">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => nextCursor && fetchBatches(nextCursor)}
            >
              Load more
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}
