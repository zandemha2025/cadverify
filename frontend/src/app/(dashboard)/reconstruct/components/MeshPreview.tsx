"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";
import Link from "next/link";
import ConfidenceBadge from "./ConfidenceBadge";

// Dynamically import the Three.js viewer to avoid SSR issues
const MeshCanvas = dynamic(() => import("./MeshCanvas"), { ssr: false });

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
      <div className="h-80 w-full overflow-hidden rounded-xl bg-gradient-to-b from-gray-100 to-gray-200 md:h-96 md:w-[70%]">
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
              Loading 3D viewer...
            </div>
          }
        >
          <MeshCanvas url={meshUrl} />
        </Suspense>
      </div>

      {/* Details panel -- 30% on desktop */}
      <div className="flex w-full flex-col justify-between space-y-4 md:w-[30%]">
        <div className="space-y-4">
          <h3 className="text-lg font-semibold text-gray-800">
            Reconstruction Result
          </h3>

          <ConfidenceBadge score={confidenceScore} level={confidenceLevel} />

          {faceCount != null && (
            <div>
              <p className="text-xs font-medium uppercase text-gray-500">
                Face Count
              </p>
              <p className="text-sm text-gray-800">
                {faceCount.toLocaleString()}
              </p>
            </div>
          )}
        </div>

        <Link
          href={analysisUrl}
          className="block w-full rounded-md bg-blue-600 px-4 py-2.5 text-center text-sm font-medium text-white hover:bg-blue-700"
        >
          View Full Analysis
        </Link>
      </div>
    </div>
  );
}
