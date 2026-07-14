import type { ReconstructionJobResult } from "@/lib/api";

export interface ReconstructionViewModel {
  confidencePercent: number;
  confidenceLevel: "high" | "medium" | "low";
  analysisId: string;
  faceCount: number;
}

/** Convert the explicit unit-interval API score exactly once for percent UI. */
export function reconstructionViewModel(
  result: ReconstructionJobResult | null,
): ReconstructionViewModel {
  const confidence = result?.reconstruction.confidence;
  return {
    confidencePercent: Math.max(0, Math.min(100, (confidence?.score ?? 0) * 100)),
    confidenceLevel: confidence?.level ?? "low",
    analysisId: result?.analysis?.id ?? "",
    faceCount: result?.reconstruction.mesh.face_count ?? 0,
  };
}
