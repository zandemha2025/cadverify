"use client";

import { AlertTriangle, Download } from "lucide-react";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { RepairResult } from "@/lib/api";
import { formatVolumeChange, repairFailureReason } from "@/lib/repair-details";

interface RepairComparisonProps {
  result: RepairResult;
  originalFilename: string;
}

export default function RepairComparison({
  result,
  originalFilename,
}: RepairComparisonProps) {
  const handleDownload = () => {
    if (!result.repaired_file_b64) return;

    // Decode base64 to binary
    const binaryString = atob(result.repaired_file_b64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    const blob = new Blob([bytes], { type: result.repair_verification?.download_media_type ?? "model/stl" });

    const stem = originalFilename.replace(/\.[^.]+$/, "");
    const downloadName = result.repair_verification?.download_filename ?? `${stem}-repaired.stl`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = downloadName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (!result.repair_applied) {
    const reason = repairFailureReason(result.repair_details);
    return (
      <Card tone="warn" className="bg-warn-bg">
        <CardContent compact className="space-y-1">
          <div className="flex items-center gap-2">
            <StatusBadge tone="warn" label="Repair not possible" size="sm" />
          </div>
          {reason && (
            <p className="num text-xs text-muted-foreground">
              Reason: {reason}
            </p>
          )}
        </CardContent>
      </Card>
    );
  }

  const volumeChange = formatVolumeChange(result.repair_details.volume_change_pct);
  // The API warns when the repaired solid's volume moved past its threshold:
  // the shell closed, but holes or bores of the design may have been filled.
  const volumeWarning = result.repair_details.volume_warning;

  return (
    <div className="space-y-4">
      {/* Repair summary banner */}
      <Card tone={volumeWarning ? "warn" : "pass"} className={volumeWarning ? "bg-warn-bg" : "bg-pass-bg"}>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <StatusBadge
                tone={volumeWarning ? "warn" : "pass"}
                label={volumeWarning ? "Repaired — check features" : "Mesh repaired"}
                size="sm"
              />
              <p className="num text-xs text-muted-foreground">
                Tier {result.repair_details.tier} ·{" "}
                {result.repair_details.original_faces?.toLocaleString()} →{" "}
                {result.repair_details.repaired_faces?.toLocaleString()} faces ·{" "}
                {result.repair_details.duration_ms?.toFixed(0)}ms
                {volumeChange && <> · volume {volumeChange}</>}
              </p>
            </div>
            {result.repaired_file_b64 && (
              <Button variant="secondary" size="sm" onClick={handleDownload}>
                <Download /> Download repaired file
              </Button>
            )}
          </div>
          {volumeWarning && (
            <div
              role="alert"
              data-testid="repair-volume-warning"
              className="flex items-start gap-2 rounded-[var(--radius)] border border-warn-border bg-background px-3 py-2"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
              <p className="text-xs text-foreground">{volumeWarning}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {result.repair_verification && (
        <Card>
          <CardContent compact className="space-y-1 text-xs">
            <p className="font-semibold">Re-verified through the same validation path</p>
            <p className="text-muted-foreground">
              Original verdict: <b className="text-foreground">{result.repair_verification.original_verdict}</b>
              {" · "}Repaired verdict: <b className="text-foreground">{result.repair_verification.repaired_verdict}</b>
            </p>
            <p className="break-all font-mono text-[10px] text-muted-foreground">
              Repaired file SHA-256 {result.repair_verification.repaired_sha256}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Before / After comparison */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Original analysis
          </h3>
          <AnalysisDashboard result={result.original_analysis} />
        </div>
        {result.repaired_analysis && (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-pass">
              Repaired analysis
            </h3>
            <AnalysisDashboard result={result.repaired_analysis} />
          </div>
        )}
      </div>
    </div>
  );
}
