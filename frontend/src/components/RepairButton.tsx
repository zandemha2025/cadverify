"use client";

import { useRef, useState } from "react";
import { repairAnalysis } from "@/lib/api";
import type { RepairResult, Issue } from "@/lib/api";

const REPAIRABLE_CODES = new Set([
  "NON_WATERTIGHT",
  "INCONSISTENT_NORMALS",
  "NOT_SOLID_VOLUME",
  "DEGENERATE_FACES",
  "MULTIPLE_BODIES",
]);

interface RepairButtonProps {
  universalIssues: Issue[];
  file: File | null;
  onRepairComplete: (result: RepairResult) => void;
}

export default function RepairButton({
  universalIssues,
  file,
  onRepairComplete,
}: RepairButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const hasRepairableIssues = universalIssues.some((issue) =>
    REPAIRABLE_CODES.has(issue.code)
  );

  if (!hasRepairableIssues) return null;

  const runRepair = async (repairFile: File) => {
    setLoading(true);
    setError(null);
    try {
      const result = await repairAnalysis(repairFile);
      onRepairComplete(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Repair failed");
    } finally {
      setLoading(false);
    }
  };

  const handleClick = () => {
    if (file) {
      runRepair(file);
    } else {
      // No file prop — open file picker so user can re-select
      fileInputRef.current?.click();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      runRepair(selected);
    }
  };

  return (
    <div className="inline-flex items-center gap-2">
      <button
        onClick={handleClick}
        disabled={loading}
        className="rounded border border-blue-600 px-3 py-1.5 text-sm text-blue-600 hover:bg-blue-50 disabled:opacity-50"
      >
        {loading ? "Repairing..." : "Attempt Mesh Repair"}
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".stl,.step,.stp"
        className="hidden"
        onChange={handleFileChange}
      />
      {error && (
        <span className="text-xs text-red-600">{error}</span>
      )}
    </div>
  );
}
