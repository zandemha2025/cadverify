"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import type { AnalysisSummary, AnalysesPage, RateLimits } from "@/lib/api";
import { fetchAnalyses } from "@/lib/api";

const MAX_LOADED_ITEMS = 500;

const VERDICT_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  pass: { bg: "bg-green-100", text: "text-green-800", label: "Pass" },
  issues: { bg: "bg-yellow-100", text: "text-yellow-800", label: "Issues" },
  fail: { bg: "bg-red-100", text: "text-red-800", label: "Fail" },
  unknown: { bg: "bg-gray-100", text: "text-gray-800", label: "Unknown" },
};

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
  const [verdictFilter, setVerdictFilter] = useState<string>("");

  const loadPage = useCallback(
    async (nextCursor?: string, reset?: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const page: AnalysesPage = await fetchAnalyses({
          cursor: nextCursor,
          limit: 20,
          verdict: verdictFilter || undefined,
        });
        setAnalyses((prev) => {
          const next = reset ? page.analyses : [...prev, ...page.analyses];
          return next;
        });
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

  // Initial load
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

  const atCapacity = analyses.length >= MAX_LOADED_ITEMS;

  return (
    <div className="space-y-3">
      {/* Filter */}
      <div className="flex items-center gap-2">
        <label htmlFor="verdict-filter" className="text-sm text-gray-500">
          Filter:
        </label>
        <select
          id="verdict-filter"
          value={verdictFilter}
          onChange={(e) => handleFilterChange(e.target.value)}
          className="rounded border px-2 py-1 text-sm"
        >
          <option value="">All verdicts</option>
          <option value="pass">Pass</option>
          <option value="issues">Issues</option>
          <option value="fail">Fail</option>
        </select>
      </div>

      {error && (
        <p className="text-sm text-red-600">{error}</p>
      )}

      {initialized && analyses.length === 0 && !loading ? (
        <p className="py-8 text-center text-gray-400">
          No analyses yet. Upload a file to get started.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">File</th>
                <th className="px-3 py-2">Verdict</th>
                <th className="px-3 py-2 text-right">Faces</th>
                <th className="px-3 py-2 text-right">Duration</th>
                <th className="px-3 py-2 text-right">When</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {analyses.map((a) => {
                const badge = VERDICT_BADGE[a.overall_verdict] ?? VERDICT_BADGE.unknown;
                return (
                  <tr
                    key={a.ulid}
                    onClick={() => router.push(`/dashboard/analyses/${a.ulid}`)}
                    className="cursor-pointer hover:bg-gray-50"
                  >
                    <td className="px-3 py-2 font-medium">{a.filename}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${badge.bg} ${badge.text}`}
                      >
                        {badge.label}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {a.face_count.toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {a.analysis_time_ms}ms
                    </td>
                    <td className="px-3 py-2 text-right text-gray-500">
                      {relativeTime(a.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Load more */}
      {hasMore && initialized && analyses.length > 0 && (
        <div className="text-center">
          {atCapacity ? (
            <p className="text-sm text-gray-500">
              {analyses.length} analyses loaded.{" "}
              <button
                onClick={() => router.push("/dashboard/analyses")}
                className="text-blue-600 underline"
              >
                Load more in new view
              </button>
            </p>
          ) : (
            <button
              onClick={() => loadPage(cursor ?? undefined)}
              disabled={loading}
              className="rounded-md border px-4 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {loading ? "Loading..." : "Load more"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
