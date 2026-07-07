"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FileCheck2,
  FileJson,
  RotateCcw,
  Sheet,
  ShieldCheck,
} from "lucide-react";
import {
  approveCostDecision,
  createRfqPackage,
  downloadRfqPackage,
  fetchCostDecision,
  exportCostJson,
  exportCostCsv,
  reopenCostDecisionApproval,
} from "@/lib/api";
import type { CostDecisionDetail } from "@/lib/api";
import { SavedCostDecisionView } from "@/components/cost/SavedCostDecisionView";
import PdfDownloadButton from "@/components/PdfDownloadButton";
import ShareButton from "@/components/ShareButton";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Spinner } from "@/components/ui/spinner";
import { StatusBadge } from "@/components/ui/status-badge";
import { Textarea } from "@/components/ui/textarea";

function BackLink({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="ghost" size="sm" className="-ml-3" onClick={onClick}>
      <ArrowLeft /> Back to cost history
    </Button>
  );
}

function formatDate(iso?: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

function GovernancePanel({
  decision,
  onUpdate,
}: {
  decision: CostDecisionDetail;
  onUpdate: (patch: Partial<CostDecisionDetail>) => void;
}) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState<"approve" | "reopen" | null>(null);
  const approved = decision.approval_status === "approved";

  async function approve() {
    setSaving("approve");
    try {
      const patch = await approveCostDecision(decision.id, note);
      onUpdate(patch);
      setNote("");
      toast.success("Decision approved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setSaving(null);
    }
  }

  async function reopen() {
    setSaving("reopen");
    try {
      const patch = await reopenCostDecisionApproval(decision.id);
      onUpdate(patch);
      toast.success("Approval reopened");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reopen failed");
    } finally {
      setSaving(null);
    }
  }

  return (
    <Card tone={decision.is_stale ? "warn" : approved ? "pass" : "neutral"}>
      <CardContent compact className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">
                Decision governance
              </h2>
              {decision.is_stale ? (
                <StatusBadge tone="warn" label="Stale" size="sm" />
              ) : approved ? (
                <StatusBadge tone="pass" label="Approved" size="sm" />
              ) : (
                <StatusBadge tone="neutral" label="Unreviewed" size="sm" />
              )}
            </div>
            {approved ? (
              <p className="text-sm text-muted-foreground">
                Signed off by user {decision.approved_by_user_id ?? "—"} on{" "}
                {formatDate(decision.approved_at)}.
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                Awaiting analyst signoff before this decision is used as an RFQ
                or sourcing record.
              </p>
            )}
          </div>

          {approved ? (
            <Button
              variant="secondary"
              size="sm"
              loading={saving === "reopen"}
              onClick={reopen}
            >
              {saving !== "reopen" && <RotateCcw />} Reopen
            </Button>
          ) : (
            <Button size="sm" loading={saving === "approve"} onClick={approve}>
              {saving !== "approve" && <ShieldCheck />} Approve
            </Button>
          )}
        </div>

        {decision.is_stale && (
          <div className="flex gap-2 rounded-[var(--radius-sm)] border border-warn-border bg-warn-bg p-3 text-sm text-warn">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <div>
              <p className="font-medium">Re-cost before relying on this record.</p>
              <p className="mt-1 text-xs">
                {decision.stale_reason ?? "Governed assumptions changed"} ·{" "}
                {formatDate(decision.stale_at)}
              </p>
            </div>
          </div>
        )}

        {approved && decision.approval_note && (
          <div className="rounded-[var(--radius-sm)] border border-border bg-muted p-3">
            <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <CheckCircle2 className="size-3.5" aria-hidden /> Approval note
            </div>
            <p className="text-sm text-foreground">{decision.approval_note}</p>
          </div>
        )}

        {!approved && (
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={1000}
            placeholder="Optional approval note"
            className="min-h-20"
          />
        )}
      </CardContent>
    </Card>
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
  const [exporting, setExporting] = useState<"json" | "csv" | "rfq" | null>(null);

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

  async function runRfqPackage() {
    if (!decision) return;
    setExporting("rfq");
    try {
      const pkg = await createRfqPackage({
        decisionIds: [id],
        title: `RFQ package - ${decision.filename}`,
      });
      await downloadRfqPackage(pkg.id, pkg.title);
      toast.success("RFQ package generated");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "RFQ package failed");
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
            <Button
              variant="secondary"
              size="sm"
              loading={exporting === "rfq"}
              onClick={() => void runRfqPackage()}
            >
              {exporting !== "rfq" && <FileCheck2 />} RFQ ZIP
            </Button>
          </>
        }
      />

      <GovernancePanel
        decision={decision}
        onUpdate={(patch) =>
          setDecision((current) => (current ? { ...current, ...patch } : current))
        }
      />

      <SavedCostDecisionView report={decision.result} />
    </div>
  );
}
