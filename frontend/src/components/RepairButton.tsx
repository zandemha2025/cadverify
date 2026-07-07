"use client";

import { useRef, useState } from "react";
import { Wrench } from "lucide-react";
import { toast } from "sonner";
import { repairAnalysis } from "@/lib/api";
import { CAD_ACCEPT } from "@/lib/cad-file";
import type { RepairResult, Issue } from "@/lib/api";
import { Button } from "@/components/ui/button";

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
  const fileInputRef = useRef<HTMLInputElement>(null);

  const hasRepairableIssues = universalIssues.some((issue) =>
    REPAIRABLE_CODES.has(issue.code)
  );

  if (!hasRepairableIssues) return null;

  const runRepair = async (repairFile: File) => {
    setLoading(true);
    try {
      const result = await repairAnalysis(repairFile);
      onRepairComplete(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Repair failed");
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
    <>
      <Button
        variant="secondary"
        size="sm"
        loading={loading}
        onClick={handleClick}
      >
        {!loading && <Wrench />}
        {loading ? "Repairing…" : "Attempt mesh repair"}
      </Button>
      <input
        ref={fileInputRef}
        type="file"
        accept={CAD_ACCEPT}
        className="hidden"
        onChange={handleFileChange}
      />
    </>
  );
}
