/**
 * DFM flag scoping — the pure, unit-testable core behind the DFM panel.
 *
 * FRAGILE-1 (the #1 demo trust-killer): the DFM headline used to be the UNION of
 * every issue across all 21 candidate process analyzers (including the 8
 * casting/molding/forging processes that ALWAYS fail on a printed part), deduped
 * only by code|message. That headline ("58 flags · 11 critical") directly
 * CONTRADICTS a recommended route that is often DFM-clean (0 flags), so a real
 * engineer reads it as noise.
 *
 * The fix: the headline count must reflect the route the part will ACTUALLY be
 * made by (the recommended process, optionally a costed shortlist) PLUS the
 * part-level `universal_issues` (geometry validity, non-watertight, …) which are
 * real regardless of process. Process-specific issues from processes that are
 * NOT on the recommended route must not inflate the headline — but the full
 * per-process matrix stays reachable via `all` (honestly labeled by the UI).
 *
 * This module has NO React / no runtime imports (only erased type imports), so
 * it is imported by both the render layer (`@/components/IssueList` re-exports
 * `flattenIssues`/`IndexedIssue`) and by the unit tests directly.
 */
import type { Issue, ValidationResult } from "@/lib/api";

export interface IndexedIssue {
  key: string;
  issue: Issue;
  /** sampled face indices for 3D highlight (unioned across duplicates) */
  faces: number[];
}

/* ------------------------------------------------------------------ */
/*  Severity buckets — mirrors lib/status.severityTone, inlined so     */
/*  this module stays free of runtime imports (node --test friendly).  */
/* ------------------------------------------------------------------ */

export type DfmSeverityBucket = "critical" | "advisory" | "info";

/** issue severity -> headline bucket. error/critical/fail -> critical,
 *  warning/warn -> advisory, everything else (info + unknown) -> info. */
export function issueSeverityBucket(severity: string): DfmSeverityBucket {
  switch (severity) {
    case "error":
    case "critical":
    case "fail":
      return "critical";
    case "warning":
    case "warn":
      return "advisory";
    default:
      return "info";
  }
}

export interface SeverityCounts {
  total: number;
  critical: number;
  advisory: number;
  info: number;
}

export function severityCounts(issues: readonly IndexedIssue[]): SeverityCounts {
  const c: SeverityCounts = { total: issues.length, critical: 0, advisory: 0, info: 0 };
  for (const it of issues) {
    const bucket = issueSeverityBucket(it.issue.severity);
    if (bucket === "critical") c.critical++;
    else if (bucket === "advisory") c.advisory++;
    else c.info++;
  }
  return c;
}

/* ------------------------------------------------------------------ */
/*  Flatten helpers                                                    */
/* ------------------------------------------------------------------ */

type Push = (issue: Issue, keyBase: string) => void;

/** Dedup by code|message, unioning the affected-face samples. */
function collect(build: (push: Push) => void): IndexedIssue[] {
  const seen = new Map<string, IndexedIssue>();
  const push: Push = (issue, keyBase) => {
    const id = `${issue.code}|${issue.message}`;
    const faces = issue.affected_faces_sample ?? [];
    const existing = seen.get(id);
    if (existing) {
      existing.faces = Array.from(new Set([...existing.faces, ...faces]));
    } else {
      seen.set(id, { key: keyBase, issue, faces: [...faces] });
    }
  };
  build(push);
  return Array.from(seen.values());
}

/** Merge universal + EVERY per-process issue (the full candidate matrix). */
export function flattenIssues(result: ValidationResult): IndexedIssue[] {
  return collect((push) => {
    result.universal_issues.forEach((iss, i) => push(iss, `u${i}`));
    result.process_scores.forEach((ps) =>
      ps.issues.forEach((iss, i) => push(iss, `${ps.process}#${i}`))
    );
  });
}

/** Merge universal issues + ONLY the issues of the given processes (the route
 *  the part will actually be made by). Part-level universal issues always count. */
export function flattenScopedIssues(
  result: ValidationResult,
  processes: readonly string[]
): IndexedIssue[] {
  const inScope = new Set(processes.filter(Boolean));
  return collect((push) => {
    result.universal_issues.forEach((iss, i) => push(iss, `u${i}`));
    result.process_scores.forEach((ps) => {
      if (!inScope.has(ps.process)) return;
      ps.issues.forEach((iss, i) => push(iss, `${ps.process}#${i}`));
    });
  });
}

/* ------------------------------------------------------------------ */
/*  The scoped summary + route partition                              */
/* ------------------------------------------------------------------ */

export interface ScopedDfmSummary {
  /** the process the headline is scoped to (recommended route); "" if unknown */
  recommendedProcess: string;
  /** processes whose issues are counted in the headline (recommended + shortlist) */
  scopedProcesses: string[];
  /** issues on the recommended route: universal + scoped-process issues */
  scoped: IndexedIssue[];
  /** headline severity counts (recommended route) */
  counts: SeverityCounts;
  /** every issue across all candidate processes (the full matrix) */
  all: IndexedIssue[];
  /** full-matrix severity counts */
  allCounts: SeverityCounts;
  /** number of candidate processes evaluated (== process_scores.length) */
  candidateProcessCount: number;
}

/**
 * Scope the DFM issue set to the recommended route (and an optional costed
 * shortlist). This is the pure heart of the FRAGILE-1 fix.
 */
export function scopedDfmSummary(
  result: ValidationResult,
  recommendedProcess?: string | null,
  shortlist?: readonly string[]
): ScopedDfmSummary {
  const rec = (recommendedProcess ?? "").trim();
  const scopedProcesses = Array.from(
    new Set([rec, ...(shortlist ?? [])].filter(Boolean))
  );
  const scoped = flattenScopedIssues(result, scopedProcesses);
  const all = flattenIssues(result);
  return {
    recommendedProcess: rec,
    scopedProcesses,
    scoped,
    counts: severityCounts(scoped),
    all,
    allCounts: severityCounts(all),
    candidateProcessCount: result.process_scores.length,
  };
}

export interface DfmPartition {
  /** issues on the recommended route — CANONICAL keys (from the full flatten),
   *  so the 3D two-way highlight linking stays coherent across surfaces. */
  route: IndexedIssue[];
  /** issues that appear ONLY on other (non-recommended) candidate processes */
  extra: IndexedIssue[];
  /** the full candidate matrix (canonical keys) */
  all: IndexedIssue[];
  /** headline counts for the recommended route */
  counts: SeverityCounts;
  /** counts for the full matrix */
  allCounts: SeverityCounts;
  /** the recommended route ("" if unknown) */
  recommendedProcess: string;
  /** number of candidate processes evaluated */
  candidateProcessCount: number;
}

/**
 * Partition the full candidate matrix into { route, extra } by issue identity
 * (code|message), keeping the CANONICAL keys from `flattenIssues` on every row.
 *
 * Why canonical keys: an issue shared by several processes (e.g. present on both
 * the recommended route and a casting process) is deduped to a single row whose
 * key comes from the first process that emitted it. Callers that render the
 * route rows and later feed the selected key back to a component that looks the
 * key up in the FULL `flattenIssues` result (the 3D highlight linking) must use
 * those same keys — so we partition `all` rather than re-flatten with new keys.
 */
export function partitionDfmByRoute(
  result: ValidationResult,
  recommendedProcess?: string | null,
  shortlist?: readonly string[]
): DfmPartition {
  const summary = scopedDfmSummary(result, recommendedProcess, shortlist);
  const routeIds = new Set(
    summary.scoped.map((i) => `${i.issue.code}|${i.issue.message}`)
  );
  const onRoute = (i: IndexedIssue) =>
    routeIds.has(`${i.issue.code}|${i.issue.message}`);
  const route = summary.all.filter(onRoute);
  const extra = summary.all.filter((i) => !onRoute(i));
  return {
    route,
    extra,
    all: summary.all,
    counts: severityCounts(route),
    allCounts: summary.allCounts,
    recommendedProcess: summary.recommendedProcess,
    candidateProcessCount: summary.candidateProcessCount,
  };
}

/* ------------------------------------------------------------------ */
/*  Feature flag                                                       */
/* ------------------------------------------------------------------ */

/**
 * FRAGILE-1: the corrected, route-scoped DFM headline is ON by default. Set
 * `NEXT_PUBLIC_DFM_SCOPED_FLAGS` to "0" / "false" / "off" / "no" to fall back to
 * the legacy union-across-all-21-processes headline. Anything else (including
 * unset) keeps the scoped behavior — no half-done toggle.
 */
export function dfmScopedFlagsEnabled(): boolean {
  const v = process.env.NEXT_PUBLIC_DFM_SCOPED_FLAGS;
  if (v == null) return true;
  const s = v.toLowerCase().trim();
  return !(s === "0" || s === "false" || s === "off" || s === "no");
}
