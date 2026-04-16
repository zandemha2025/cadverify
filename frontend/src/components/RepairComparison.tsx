"use client";

import AnalysisDashboard from "@/components/AnalysisDashboard";
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
      <div className="rounded-md border border-yellow-300 bg-yellow-50 p-4">
        <p className="text-sm text-yellow-800">
          Repair was not possible for this mesh.
          {result.repair_details.error && (
            <span className="mt-1 block text-xs text-yellow-600">
              Reason: {result.repair_details.error}
            </span>
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Repair summary banner */}
      <div className="rounded-md border border-green-300 bg-green-50 p-4">
        <p className="text-sm font-medium text-green-800">
          Mesh repaired successfully
        </p>
        <p className="mt-1 text-xs text-green-600">
          Tier: {result.repair_details.tier} &middot;{" "}
          {result.repair_details.original_faces?.toLocaleString()} &rarr;{" "}
          {result.repair_details.repaired_faces?.toLocaleString()} faces &middot;{" "}
          {result.repair_details.duration_ms?.toFixed(0)}ms
        </p>
        {result.repaired_file_b64 && (
          <button
            onClick={handleDownload}
            className="mt-2 rounded bg-green-600 px-3 py-1 text-sm text-white hover:bg-green-700"
          >
            Download Repaired File
          </button>
        )}
      </div>

      {/* Before / After comparison */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-gray-500">
            Original Analysis
          </h3>
          <AnalysisDashboard result={result.original_analysis} />
        </div>
        {result.repaired_analysis && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-green-600">
              Repaired Analysis
            </h3>
            <AnalysisDashboard result={result.repaired_analysis} />
          </div>
        )}
      </div>
    </div>
  );
}
