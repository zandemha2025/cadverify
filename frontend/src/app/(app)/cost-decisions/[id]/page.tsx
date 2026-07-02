"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowLeft, FileJson, Sheet } from "lucide-react";
import { fetchCostDecision, exportCostJson, exportCostCsv } from "@/lib/api";
import type { CostDecisionDetail } from "@/lib/api";
import { SavedCostDecisionView } from "@/components/cost/SavedCostDecisionView";
import PdfDownloadButton from "@/components/PdfDownloadButton";
import ShareButton from "@/components/ShareButton";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Spinner } from "@/components/ui/spinner";

function BackLink({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="ghost" size="sm" className="-ml-3" onClick={onClick}>
      <ArrowLeft /> Back to cost history
    </Button>
  );
}

export default function CostDecisionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [decision, setDecision] = useState<CostDecisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState<"json" | "csv" | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchCostDecision(id)
      .then((data) => {
        if (!cancelled) setDecision(data);
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

  async function runExport(kind: "json" | "csv") {
    if (!decision) return;
    setExporting(kind);
    try {
      if (kind === "json") await exportCostJson(id, decision.filename);
      else await exportCostCsv(id, decision.filename);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(null);
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (error || !decision) {
    return (
      <div className="space-y-4">
        <BackLink onClick={() => router.push("/cost-decisions")} />
        <ErrorState
          title="Cost decision not found"
          message={error ?? "This cost decision could not be loaded."}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <BackLink onClick={() => router.push("/cost-decisions")} />

      <PageHeader
        title={decision.label || decision.filename}
        subtitle={`${decision.file_type.toUpperCase()} · ${new Date(
          decision.created_at
        ).toLocaleString()}`}
        actions={
          <>
            <ShareButton
              analysisId={id}
              kind="cost"
              initialShared={decision.is_public}
              initialShareUrl={decision.share_url}
            />
            <PdfDownloadButton
              analysisId={id}
              filename={decision.filename}
              kind="cost"
            />
            <Button
              variant="secondary"
              size="sm"
              loading={exporting === "json"}
              onClick={() => runExport("json")}
            >
              {exporting !== "json" && <FileJson />} JSON
            </Button>
            <Button
              variant="secondary"
              size="sm"
              loading={exporting === "csv"}
              onClick={() => runExport("csv")}
            >
              {exporting !== "csv" && <Sheet />} CSV
            </Button>
          </>
        }
      />

      <SavedCostDecisionView report={decision.result} />
    </div>
  );
}
