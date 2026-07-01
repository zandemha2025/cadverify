"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { History } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import type { AnalysisSummary, AnalysesPage, RateLimits } from "@/lib/api";
import { fetchAnalyses } from "@/lib/api";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";

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

export default function AnalysisHistoryTable({ onRateLimitsUpdate }: Props) {
  const router = useRouter();
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verdictFilter, setVerdictFilter] = useState<string>("all");

  const loadPage = useCallback(
    async (nextCursor?: string, reset?: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const page: AnalysesPage = await fetchAnalyses({
          cursor: nextCursor,
          limit: 20,
          verdict: verdictFilter === "all" ? undefined : verdictFilter,
        });
        setAnalyses((prev) =>
          reset ? page.analyses : [...prev, ...page.analyses],
        );
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
        onRateLimitsUpdate?.(page.rateLimits);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load analyses");
      } finally {
        setLoading(false);
        setInitialized(true);
      }
    },
    [verdictFilter, onRateLimitsUpdate],
  );

  // Initial load (and reload after a filter change resets `initialized`).
  if (!initialized && !loading) {
    loadPage(undefined, true);
  }

  const handleFilterChange = (v: string) => {
    setVerdictFilter(v);
    setAnalyses([]);
    setCursor(null);
    setHasMore(true);
    setInitialized(false);
  };

  const columns = useMemo<ColumnDef<AnalysisSummary>[]>(
    () => [
      {
        accessorKey: "filename",
        header: "File",
        cell: ({ row }) => (
          <span className="font-medium text-foreground">
            {row.original.filename}
          </span>
        ),
      },
      {
        accessorKey: "overall_verdict",
        header: "Verdict",
        cell: ({ row }) => (
          <StatusBadge verdict={row.original.overall_verdict} size="sm" />
        ),
      },
      {
        accessorKey: "face_count",
        header: "Faces",
        meta: { numeric: true },
        cell: ({ row }) => row.original.face_count.toLocaleString(),
      },
      {
        accessorKey: "analysis_time_ms",
        header: "Duration",
        meta: { numeric: true },
        cell: ({ row }) => `${row.original.analysis_time_ms} ms`,
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
    [],
  );

  const atCapacity = analyses.length >= MAX_LOADED_ITEMS;

  return (
    <div className="space-y-3">
      {/* Filter */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">Filter</span>
        <Select value={verdictFilter} onValueChange={handleFilterChange}>
          <SelectTrigger className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All verdicts</SelectItem>
            <SelectItem value="pass">Pass</SelectItem>
            <SelectItem value="issues">Advisory</SelectItem>
            <SelectItem value="fail">Required</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {error && (
        <ErrorState
          message={error}
          onRetry={() => loadPage(undefined, true)}
        />
      )}

      <DataTable
        columns={columns}
        data={analyses}
        loading={loading && analyses.length === 0}
        onRowClick={(row) => router.push(`/analyses/${row.ulid}`)}
        emptyState={
          initialized && !error ? (
            <EmptyState
              icon={History}
              title="No analyses yet"
              description="Upload a CAD file to get started."
              action={
                <Button onClick={() => router.push("/analyze")}>
                  Analyze a part
                </Button>
              }
            />
          ) : undefined
        }
      />

      {/* Load more */}
      {hasMore && initialized && analyses.length > 0 && (
        <div className="text-center">
          {atCapacity ? (
            <p className="text-sm text-muted-foreground">
              {analyses.length} analyses loaded.
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
