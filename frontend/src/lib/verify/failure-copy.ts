export type AnalysisFailureKind = "capacity" | "unsupported" | "geometry" | "unknown";

export interface AnalysisFailureCopy {
  kind: AnalysisFailureKind;
  title: string;
  explanation: string;
  action: string;
  toast: string;
}

/** Keep operational failures from being mislabeled as broken customer CAD. */
export function analysisFailureCopy(reason: string | null | undefined): AnalysisFailureCopy {
  const value = reason?.trim() ?? "";

  if (/capacity|concurrent-analysis|rate limit|rate-limit|too many requests|retry shortly/i.test(value)) {
    return {
      kind: "capacity",
      title: "Verification is temporarily busy.",
      explanation: "The service did not start routing, DFM, or should-cost for this attempt.",
      action: "Wait a moment and retry. The CAD file does not need to be re-exported.",
      toast: "Could not analyze — verification capacity is busy; retry shortly",
    };
  }

  if (/unsupported file type|use \.stl|not a (?:cad|supported)/i.test(value)) {
    return {
      kind: "unsupported",
      title: "We couldn’t read this file.",
      explanation: "The selected file type is not supported for verification.",
      action: "Upload an STL, STEP, STP, IGES, or IGS part to run the walk.",
      toast: "Could not analyze — unsupported CAD file type",
    };
  }

  if (/tessell|mesher|triangulat|unsupported surface|invalid geometry|clean solid/i.test(value)) {
    return {
      kind: "geometry",
      title: "This part couldn’t be tessellated.",
      explanation: "The geometry contains a surface the mesher could not triangulate.",
      action: "Re-export the part as a clean solid and upload it again.",
      toast: "Could not analyze — this part couldn’t be tessellated",
    };
  }

  return {
    kind: "unknown",
    title: "Verification could not finish.",
    explanation: "The service returned no routing, DFM, or should-cost result for this attempt.",
    action: "Retry once. If it repeats, keep the file and contact the platform operator.",
    toast: "Could not analyze — verification did not finish",
  };
}
