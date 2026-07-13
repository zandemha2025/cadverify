export type AnalysisFailureKind = "capacity" | "unreadable" | "unsupported" | "geometry" | "unknown";

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

  if (
    /does not appear to be a valid (?:step|stl|iges)|missing iso-10303-21 header|too small to be a valid stl|could not read (?:step(?:\/iges)?|iges) geometry|not a valid\/supported (?:step|iges|file)/i.test(value)
  ) {
    return {
      kind: "unreadable",
      title: "We couldn’t read this file.",
      explanation: "The file name uses a supported CAD format, but its contents could not be parsed as a valid model.",
      action: "Re-export the original part as a clean STL, STEP, STP, IGES, or IGS file, then upload that export.",
      toast: "Could not analyze — the CAD export is unreadable",
    };
  }

  if (
    /unsupported file type|use \.stl|not a (?:cad|supported)|proprietary\/native cad|requires a licensed reader/i.test(value)
  ) {
    return {
      kind: "unsupported",
      title: "We couldn’t read this file.",
      explanation: "This file type cannot be read directly for verification.",
      action: "Export the original part as STL, STEP, STP, IGES, or IGS, then upload that exchange file.",
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
