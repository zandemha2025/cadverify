"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { fetchAnalysis } from "@/lib/api";
import type { AnalysisDetail, RepairResult } from "@/lib/api";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import PdfDownloadButton from "@/components/PdfDownloadButton";
import ShareButton from "@/components/ShareButton";
import RepairButton from "@/components/RepairButton";
import RepairComparison from "@/components/RepairComparison";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Spinner } from "@/components/ui/spinner";

function BackLink({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="ghost" size="sm" className="-ml-3" onClick={onClick}>
      <ArrowLeft /> Back to history
    </Button>
  );
}

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
  const [repairResult, setRepairResult] = useState<RepairResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchAnalysis(id)
      .then((data) => {
        if (!cancelled) setAnalysis(data);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Failed to load");
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
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (error || !analysis) {
    return (
      <div className="space-y-4">
        <BackLink onClick={() => router.push("/history")} />
        <ErrorState
          title="Analysis not found"
          message={error ?? "This analysis could not be loaded."}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <BackLink onClick={() => router.push("/history")} />

      <PageHeader
        title={analysis.filename}
        subtitle={`${analysis.file_type.toUpperCase()} · ${new Date(
          analysis.created_at,
        ).toLocaleString()}`}
        actions={
          <>
            <ShareButton
              analysisId={id}
              initialShared={analysis.is_public}
              initialShareUrl={analysis.share_url}
            />
            <PdfDownloadButton analysisId={id} filename={analysis.filename} />
            <RepairButton
              universalIssues={analysis.result_json.universal_issues}
              file={null}
              onRepairComplete={setRepairResult}
            />
          </>
        }
      />

      {analysis.decision_links.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Linked cost decisions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {analysis.decision_links.map((decision) => (
              <div
                key={decision.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3"
              >
                <div>
                  <p className="font-medium text-foreground">{decision.filename}</p>
                  <p className="text-xs text-muted-foreground">
                    {decision.make_now_process ?? "No make-now route"} · {decision.approval_status}
                  </p>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => router.push(decision.url)}
                >
                  Open decision
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Show repair comparison when available, otherwise original dashboard */}
      {repairResult ? (
        <RepairComparison
          result={repairResult}
          originalFilename={analysis.filename}
        />
      ) : (
        <AnalysisDashboard result={analysis.result_json} />
      )}
    </div>
  );
}
