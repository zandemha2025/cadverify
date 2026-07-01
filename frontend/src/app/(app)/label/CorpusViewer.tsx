"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";
import { API_BASE } from "@/lib/api-base";

// Use the single shared CAD viewer primitive (STL-from-URL via `src`).
const CadViewer = dynamic(() => import("@/components/ui/cad-viewer"), {
  ssr: false,
});

export default function CorpusViewer({ partId }: { partId: string }) {
  const url = `${API_BASE}/corpus/parts/${partId}/mesh.stl`;
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          Loading 3D viewer...
        </div>
      }
    >
      {/* key forces a fresh loader when the part changes */}
      <CadViewer key={partId} src={url} />
    </Suspense>
  );
}
