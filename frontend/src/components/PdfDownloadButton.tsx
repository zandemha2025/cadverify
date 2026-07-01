"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { downloadPdf } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface PdfDownloadButtonProps {
  analysisId: string;
  filename: string;
}

export default function PdfDownloadButton({
  analysisId,
  filename,
}: PdfDownloadButtonProps) {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    try {
      await downloadPdf(analysisId, filename);
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
