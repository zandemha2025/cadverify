/**
 * THE single source of truth for status / severity / process vocabulary.
 *
 * This module replaces every per-file color/label map in the app
 * (AnalysisDashboard VERDICT_STYLES/PROCESS_LABELS/CITATION_COLORS/SEVERITY,
 *  CostDecisionCard PROCESS_LABELS/PROVENANCE_STYLES, AnalysisHistoryTable
 *  VERDICT_BADGE, s/[shortId] VERDICT_STYLES/SEVERITY_STYLES, batch STATUS maps,
 *  ProcessScoreCard VERDICT_COLORS, IssueList SEVERITY/CITATION, FeaturesList
 *  KIND_CONFIG, QuotaDisplay usageColor,
 *  reconstruct ConfidenceBadge/ReconstructionProgress level maps).
 *
 * No component may declare a new color/label map — import from here.
 */
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Info,
  XCircle,
  type LucideIcon,
} from "lucide-react";

export type Tone = "pass" | "warn" | "fail" | "info" | "neutral";

/**
 * tone -> the token-driven class bundles. Primitives (StatusBadge, Card tone,
 * dots, banners) consume these; they reference only @theme tokens (no raw hex).
 */
export const TONE: Record<
  Tone,
  { solid: string; bg: string; border: string; fg: string; dot: string }
> = {
  pass: {
    solid: "bg-pass text-white",
    bg: "bg-pass-bg",
    border: "border-pass-border",
    fg: "text-pass",
    dot: "bg-pass",
  },
  warn: {
    solid: "bg-warn text-white",
    bg: "bg-warn-bg",
    border: "border-warn-border",
    fg: "text-warn",
    dot: "bg-warn",
  },
  fail: {
    solid: "bg-fail text-white",
    bg: "bg-fail-bg",
    border: "border-fail-border",
    fg: "text-fail",
    dot: "bg-fail",
  },
  info: {
    solid: "bg-info text-white",
    bg: "bg-info-bg",
    border: "border-info-border",
    fg: "text-info",
    dot: "bg-info",
  },
  neutral: {
    solid: "bg-neutral-500 text-white",
    bg: "bg-muted",
    border: "border-border",
    fg: "text-muted-foreground",
    dot: "bg-neutral-400",
  },
};

/** lucide icon per tone — status is NEVER color-only. */
export const TONE_ICON: Record<Tone, LucideIcon> = {
  pass: CheckCircle2,
  warn: AlertTriangle,
  fail: XCircle,
  info: Info,
  neutral: Circle,
};

/* ------------------------------------------------------------------ */
/* Canonical vocabulary (ONE label set)                               */
/* ------------------------------------------------------------------ */

/** verdict (manufacturability) -> tone. issues/warning -> warn, fail/error -> fail */
export function verdictTone(v: string): Tone {
  switch (v) {
    case "pass":
      return "pass";
    case "issues":
    case "warning":
    case "warn":
      return "warn";
    case "fail":
    case "error":
      return "fail";
    case "info":
      return "info";
    default:
      return "neutral";
  }
}

/** verdict -> label. Short by default ("Pass/Advisory/Required"); long banner copy when long=true. */
export function verdictLabel(v: string, long = false): string {
  switch (v) {
    case "pass":
      return long ? "Manufacturable" : "Pass";
    case "issues":
    case "warning":
    case "warn":
      return long ? "Issues found" : "Advisory";
    case "fail":
    case "error":
      return long ? "Not manufacturable" : "Required";
    case "info":
      return "Info";
    default:
      return "Unknown";
  }
}

/** severity (issue) -> tone. error -> fail, warning -> warn, info -> info */
export function severityTone(s: string): Tone {
  switch (s) {
    case "error":
    case "critical":
    case "fail":
      return "fail";
    case "warning":
    case "warn":
      return "warn";
    case "info":
      return "info";
    default:
      return "neutral";
  }
}

/** severity -> label. Two-tier DFM: error -> Required, warning -> Advisory. */
export function severityLabel(s: string): string {
  switch (s) {
    case "error":
    case "critical":
    case "fail":
      return "Required";
    case "warning":
    case "warn":
      return "Advisory";
    case "info":
      return "Info";
    default:
      return "Note";
  }
}

/** batch item status -> tone */
export function batchStatusTone(s: string): Tone {
  switch (s) {
    case "completed":
    case "complete":
    case "done":
      return "pass";
    case "processing":
    case "running":
    case "queued":
      return "info";
    case "extracting":
      return "warn";
    case "failed":
    case "error":
      return "fail";
    case "pending":
    case "cancelled":
    case "canceled":
    default:
      return "neutral";
  }
}

/** reconstruction / matcher confidence -> tone */
export function confidenceTone(level: string): Tone {
  switch (level) {
    case "high":
      return "pass";
    case "medium":
      return "warn";
    case "low":
      return "fail";
    default:
      return "neutral";
  }
}

/** quota usage -> tone. <0.7 pass, <0.9 warn, else fail */
export function usageTone(used: number, limit: number): Tone {
  if (!limit || limit <= 0) return "neutral";
  const r = used / limit;
  if (r < 0.7) return "pass";
  if (r < 0.9) return "warn";
  return "fail";
}

/** rule-pack / citation domain tint */
export function domainTone(name: string): Tone {
  const n = (name || "").toLowerCase();
  if (n.includes("aero")) return "info";
  if (n.includes("auto")) return "pass";
  if (n.includes("oil") || n.includes("gas")) return "warn";
  return "neutral";
}

/* ------------------------------------------------------------------ */
/* Process display-name map (the ONE copy — 21 entries)               */
/* ------------------------------------------------------------------ */

export const PROCESS_LABELS: Record<string, string> = {
  fdm: "FDM / FFF",
  sla: "SLA Resin",
  dlp: "DLP Resin",
  sls: "SLS (Powder)",
  mjf: "MJF (HP)",
  dmls: "DMLS (Metal)",
  slm: "SLM (Metal)",
  ebm: "EBM (Metal)",
  binder_jetting: "Binder Jetting",
  ded: "DED",
  waam: "WAAM",
  cnc_3axis: "CNC 3-Axis",
  cnc_5axis: "CNC 5-Axis",
  cnc_turning: "CNC Turning",
  wire_edm: "Wire EDM",
  injection_molding: "Injection Molding",
  die_casting: "Die Casting",
  investment_casting: "Investment Casting",
  sand_casting: "Sand Casting",
  sheet_metal: "Sheet Metal",
  forging: "Forging",
};

export function procLabel(p: string): string {
  return PROCESS_LABELS[p] ?? p;
}

/* ------------------------------------------------------------------ */
/* Provenance (glass-box tags) — THE ATOM OF THE PRODUCT.             */
/*                                                                    */
/* Every driver / assumption / line-item the engine emits carries one */
/* of four sources. The visual system encodes TWO true dimensions:    */
/*   • FILL  = groundedness — filled marker = grounded in your reality */
/*     (MEASURED off geometry, SHOP rate, USER override); a HOLLOW     */
/*     ring = DEFAULT (a generic guess — "we don't know your number"). */
/*     The gaps are visible, not hidden.                              */
/*   • HUE   = source — measured-blue, calibration-teal (SHOP),        */
/*     override-green (USER), slate (DEFAULT).                         */
/* Status is never colour-only: each tag also carries fill + label.   */
/* ------------------------------------------------------------------ */

export type Provenance = "MEASURED" | "SHOP" | "USER" | "CAD" | "DEFAULT";

export interface ProvenanceMeta {
  /** uppercase tag rendered on the number */
  label: Provenance;
  /** one-line plain-language meaning (tooltip / legend) */
  description: string;
  /** grounded in the user's reality (filled) vs a generic guess (hollow ring) */
  filled: boolean;
  /** chip surface bundle (theme-aware tokens, no raw hex) */
  chip: string;
  /** the marker dot/ring class bundle */
  dot: string;
  /** bare text colour token */
  fg: string;
}

export const PROVENANCE_META: Record<Provenance, ProvenanceMeta> = {
  MEASURED: {
    label: "MEASURED",
    description: "Measured directly from your CAD geometry.",
    filled: true,
    chip: "bg-prov-measured-bg text-prov-measured border-prov-measured-border",
    dot: "bg-prov-measured border-prov-measured",
    fg: "text-prov-measured",
  },
  SHOP: {
    label: "SHOP",
    description: "Your shop's calibrated rate — bound to your real numbers.",
    filled: true,
    chip: "bg-prov-shop-bg text-prov-shop border-prov-shop-border",
    dot: "bg-prov-shop border-prov-shop",
    fg: "text-prov-shop",
  },
  USER: {
    label: "USER",
    description: "You overrode this value.",
    filled: true,
    chip: "bg-prov-user-bg text-prov-user border-prov-user-border",
    dot: "bg-prov-user border-prov-user",
    fg: "text-prov-user",
  },
  CAD: {
    label: "CAD",
    description:
      "Read from the CAD file's own material annotation — the file's stated claim, not measured from geometry and not confirmed by your team.",
    filled: true,
    chip: "bg-prov-cad-bg text-prov-cad border-prov-cad-border",
    dot: "bg-prov-cad border-prov-cad",
    fg: "text-prov-cad",
  },
  DEFAULT: {
    label: "DEFAULT",
    description: "Generic fallback — no calibrated value yet. We're guessing here.",
    filled: false,
    chip: "bg-prov-default-bg text-prov-default border-prov-default-border",
    dot: "bg-transparent border-prov-default",
    fg: "text-prov-default",
  },
};

/** Back-compat: chip class bundle by provenance (use PROVENANCE_META for fill/label). */
export const PROVENANCE: Record<Provenance, string> = {
  MEASURED: PROVENANCE_META.MEASURED.chip,
  SHOP: PROVENANCE_META.SHOP.chip,
  USER: PROVENANCE_META.USER.chip,
  CAD: PROVENANCE_META.CAD.chip,
  DEFAULT: PROVENANCE_META.DEFAULT.chip,
};

export function provMeta(p: string): ProvenanceMeta {
  return PROVENANCE_META[(p as Provenance)] ?? PROVENANCE_META.DEFAULT;
}
