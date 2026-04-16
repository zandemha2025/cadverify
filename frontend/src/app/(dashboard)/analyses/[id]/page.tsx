"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchAnalysis } from "@/lib/api";
import type { AnalysisDetail } from "@/lib/api";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import ShareButton from "@/components/ShareButton";

export default function AnalysisDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchAnalysis(id)
      .then((data) => {
        if (!cancelled) setAnalysis(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <main className="py-8 text-center text-gray-400">Loading analysis...</main>
    );
  }

  if (error || !analysis) {
    return (
      <main className="space-y-4 py-8">
        <button
          onClick={() => router.push("/dashboard")}
          className="text-sm text-blue-600 hover:underline"
        >
          &larr; Back to dashboard
        </button>
        <p className="text-center text-red-600">
          {error ?? "Analysis not found"}
        </p>
      </main>
    );
  }

  return (
    <main className="space-y-4">
      <button
        onClick={() => router.push("/dashboard")}
        className="text-sm text-blue-600 hover:underline"
      >
        &larr; Back to dashboard
      </button>

      {/* Metadata header */}
      <div className="rounded-md border p-3">
        <h1 className="text-lg font-semibold">{analysis.filename}</h1>
        <p className="text-sm text-gray-500">
          {analysis.file_type.toUpperCase()} &middot;{" "}
          {new Date(analysis.created_at).toLocaleString()}
        </p>
        <div className="mt-2 flex items-center gap-2">
          <ShareButton
            analysisId={id}
            initialShared={analysis.is_public}
            initialShareUrl={analysis.share_url}
          />
        </div>
      </div>

      {/* Reuse existing AnalysisDashboard for the full result */}
      <AnalysisDashboard result={analysis.result_json} />
    </main>
  );
}
