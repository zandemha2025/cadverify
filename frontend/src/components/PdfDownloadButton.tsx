"use client";

import { useState } from "react";
import { downloadPdf } from "@/lib/api";

interface PdfDownloadButtonProps {
  analysisId: string;
  filename: string;
}

export default function PdfDownloadButton({
  analysisId,
  filename,
}: PdfDownloadButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setLoading(true);
    setError(null);
    try {
      await downloadPdf(analysisId, filename);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to download PDF";
      setError(msg);
      setTimeout(() => setError(null), 3000);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="inline-flex items-center gap-2">
      <button
        onClick={handleClick}
        disabled={loading}
        className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? "Generating PDF..." : "Download PDF"}
      </button>
      {error && (
        <span className="text-xs text-red-600">{error}</span>
      )}
    </div>
  );
}
