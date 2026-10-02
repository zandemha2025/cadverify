"use client";

import { useEffect, useRef, useState } from "react";
import { Wrench } from "lucide-react";
import { repairAnalysis } from "@/lib/api";
import { CAD_ACCEPT } from "@/lib/cad-file";
import type { RepairResult, Issue, ValidationResult } from "@/lib/api";
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
  originalAnalysis?: ValidationResult | null;
  onRepairComplete: (result: RepairResult) => void;
}

export default function RepairButton({
  universalIssues,
  file,
  originalAnalysis,
  onRepairComplete,
}: RepairButtonProps) {
  const [loading, setLoading] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState("");
  const repairAbort = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);
  useEffect(() => {
    const sequence = requestSeq;
    const controller = repairAbort;
    ++sequence.current;
    setPendingFile(null);
    setLoading(false);
    setError(null);
    return () => { ++sequence.current; controller.current?.abort(); };
  }, [file]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const hasRepairableIssues = universalIssues.some((issue) =>
    REPAIRABLE_CODES.has(issue.code)
  );

  if (!hasRepairableIssues) return null;

  const runRepair = async (repairFile: File) => {
    const seq = ++requestSeq.current;
    setPendingFile(null);
    setLoading(true);
    setError(null);
    setProgress("Preparing local repair…");
    const controller=new AbortController(); repairAbort.current=controller;
    try {
      const result = await repairAnalysis(repairFile, file ? originalAnalysis ?? null : null, {signal:controller.signal,onProgress:setProgress});
      if (requestSeq.current === seq) onRepairComplete(result);
    } catch (err) {
      if (requestSeq.current === seq) setError(err instanceof Error ? err.message : "Repair failed");
    } finally {
      if (requestSeq.current === seq) setLoading(false);
      window.dispatchEvent(new Event("proofshape:usage-changed"));
    }
  };

  const handleClick = () => {
    if (file) {
      setPendingFile(file);
    } else {
      // No file prop — open file picker so user can re-select
      fileInputRef.current?.click();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setPendingFile(selected);
    }
  };

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        loading={loading}
        onClick={handleClick}
        title={file ? "Repair this file" : "Choose the original CAD file to attempt mesh repair"}
        aria-label={file ? "Attempt mesh repair" : "Attempt mesh repair - opens a file picker"}
      >
        {!loading && <Wrench />}
        {loading ? "Repair in progress…" : file ? "Try repair on my device" : "Choose file to repair"}
      </Button>
      {loading && <div role="status" className="my-2 text-sm"><p>{progress}</p>{!progress.startsWith("Verifying") && <Button size="sm" variant="ghost" onClick={()=>repairAbort.current?.abort()}>Cancel local repair</Button>}</div>}
      {error && <p role="alert" className="my-2 text-sm text-destructive">{error}</p>}
      {pendingFile && <div role="group" aria-label="Confirm automatic repair" className="my-3 space-y-2 rounded-lg border p-3 text-sm">
        <p className="font-semibold">Repair and verify {pendingFile.name}?</p>
        <p>1 check only if the repaired file passes the geometry checks. Failed attempts cost no checks. Approved paid access is included.</p>
        <p>Repair runs on your computer, with no triangle-count cutoff. Large files use your device’s memory and may take longer. You can cancel local repair at any time. We correct face directions, remove duplicate or collapsed triangles and close planar holes. Complex non-manifold or ambiguous shapes may need your CAD editor.</p>
        <p>Your original stays unchanged. Review the repaired STL before using it. STEP/IGES needs server conversion to a full mesh first; editable CAD features are not preserved in STL. Only the final verification is charged, if it passes.</p>
        <div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => void runRepair(pendingFile)}>Repair and verify · 1 check on success</Button><Button size="sm" variant="ghost" onClick={() => setPendingFile(null)}>Cancel</Button></div>
      </div>}
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
