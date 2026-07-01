"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";
import Link from "next/link";
import ConfidenceBadge from "./ConfidenceBadge";
import { Button } from "@/components/ui/button";

// Single shared CAD viewer primitive (STL-from-URL via `src`).
const CadViewer = dynamic(() => import("@/components/ui/cad-viewer"), {
  ssr: false,
});

interface MeshPreviewProps {
  meshUrl: string;
  confidenceScore: number;
  confidenceLevel: "high" | "medium" | "low";
  analysisUrl: string;
  faceCount?: number;
}

export default function MeshPreview({
  meshUrl,
  confidenceScore,
  confidenceLevel,
  analysisUrl,
  faceCount,
}: MeshPreviewProps) {
  return (
    <div className="flex flex-col gap-6 md:flex-row">
      {/* 3D Viewer -- 70% on desktop */}
      <div className="h-80 w-full overflow-hidden md:h-96 md:w-[70%]">
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center rounded-[var(--radius)] border border-border bg-muted text-sm text-muted-foreground">
              Loading 3D viewer…
            </div>
          }
        >
          <CadViewer src={meshUrl} />
        </Suspense>
      </div>

      {/* Details panel -- 30% on desktop */}
      <div className="flex w-full flex-col justify-between gap-4 md:w-[30%]">
        <div className="space-y-4">
          <h3 className="text-base font-semibold text-foreground">
            Reconstruction result
          </h3>

          <ConfidenceBadge score={confidenceScore} level={confidenceLevel} />

          {faceCount != null && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Face count
              </p>
              <p className="num mt-0.5 text-sm text-foreground">
                {faceCount.toLocaleString()}
              </p>
            </div>
          )}
        </div>

        <Button asChild className="w-full">
          <Link href={analysisUrl}>View full analysis</Link>
        </Button>
      </div>
    </div>
  );
}
