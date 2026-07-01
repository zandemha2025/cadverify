"use client";

import { Download } from "lucide-react";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { RepairResult } from "@/lib/api";

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
    const blob = new Blob([bytes], { type: "application/octet-stream" });

    // Trigger download with {original}-repaired.stl filename
    const stem = originalFilename.replace(/\.[^.]+$/, "");
    const downloadName = `${stem}-repaired.stl`;
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
    return (
      <Card tone="warn" className="bg-warn-bg">
        <CardContent compact className="space-y-1">
          <div className="flex items-center gap-2">
            <StatusBadge tone="warn" label="Repair not possible" size="sm" />
          </div>
          {result.repair_details.error && (
            <p className="num text-xs text-muted-foreground">
              Reason: {result.repair_details.error}
            </p>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Repair summary banner */}
      <Card tone="pass" className="bg-pass-bg">
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <StatusBadge tone="pass" label="Mesh repaired" size="sm" />
              <p className="num text-xs text-muted-foreground">
                Tier {result.repair_details.tier} ·{" "}
                {result.repair_details.original_faces?.toLocaleString()} →{" "}
                {result.repair_details.repaired_faces?.toLocaleString()} faces ·{" "}
                {result.repair_details.duration_ms?.toFixed(0)}ms
              </p>
            </div>
            {result.repaired_file_b64 && (
              <Button variant="secondary" size="sm" onClick={handleDownload}>
                <Download /> Download repaired file
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

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
