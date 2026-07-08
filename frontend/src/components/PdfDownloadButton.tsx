"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { downloadPdf, downloadCostPdf } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface PdfDownloadButtonProps {
  /** analysis ulid (DFM) or cost-decision ulid (cost). */
  analysisId: string;
  filename: string;
  /** which report to fetch. "dfm" (default) → analysis PDF; "cost" → cost report. */
  kind?: "dfm" | "cost";
}

export default function PdfDownloadButton({
  analysisId,
  filename,
  kind = "dfm",
}: PdfDownloadButtonProps) {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    try {
      if (kind === "cost") await downloadCostPdf(analysisId, filename);
      else await downloadPdf(analysisId, filename);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to download PDF");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      variant="secondary"
      size="sm"
      loading={loading}
      onClick={handleClick}
    >
      {!loading && <Download />}
      {loading ? "Generating PDF…" : "Download PDF"}
    </Button>
  );
}
