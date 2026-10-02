"use client";

import { Download } from "lucide-react";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { repairedFile, type RepairResult } from "@/lib/api";

interface RepairComparisonProps {
  result: RepairResult;
  originalFilename: string;
  onPreview?: (repaired: boolean) => void;
}

export default function RepairComparison({
  result,
  originalFilename,
  onPreview,
}: RepairComparisonProps) {
  const handleDownload = () => {
    const file = repairedFile(result);
    if (!file) return;
    const url = URL.createObjectURL(file);
    const a = document.createElement("a");
    a.href = url;
    a.download = file.name;
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
            <StatusBadge tone="warn" label="Automatic repair did not succeed · no check charged" size="sm" />
          </div>
          {(result.repair_details.error || result.repair_details.reason) && (
            <p className="num text-xs text-muted-foreground">
              Reason: {result.repair_details.error || result.repair_details.reason}
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
              <StatusBadge tone="pass" label="Repaired file passes geometry checks" size="sm" />
              <p className="num text-xs text-muted-foreground">
                {result.repair_details.tier === "browser" ? "Repaired on your device" : `Tier ${result.repair_details.tier}`} ·{" "}
                {result.repair_details.original_faces?.toLocaleString()} →{" "}
                {result.repair_details.repaired_faces?.toLocaleString()} faces ·{" "}
                {result.repair_details.duration_ms?.toFixed(0)}ms
              </p>
            </div>
            {(result.local_file || result.repaired_file_b64) && (
              <Button variant="secondary" size="sm" onClick={handleDownload}>
                <Download /> Download repaired file
              </Button>
            )}
          </div>
          <p className="text-xs">Original: {result.original_filename ?? originalFilename}. Review the changed shape before manufacturing; passing geometry checks does not establish design intent or process suitability.</p>
          {result.repair_details.actions?.map((action) => <p key={action} className="text-xs">{action}</p>)}
          {onPreview && <div className="flex flex-wrap gap-2"><Button variant="secondary" size="sm" onClick={() => onPreview(false)}>View original model</Button><Button variant="secondary" size="sm" onClick={() => onPreview(true)}>Preview repaired model</Button></div>}
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

      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer text-sm font-medium">Full before and after analysis</summary>
      <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Original analysis
          </h3>
            {result.original_analysis ? <AnalysisDashboard result={result.original_analysis} /> : <p className="text-sm">The selected file was repaired locally. No original server analysis was matched to these bytes.</p>}
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
      </details>
    </div>
  );
}
