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
  /** All processes that emitted this finding, including deduplicated rows. */
  processes?: readonly string[];
}

export function issueProcesses(row: IndexedIssue): readonly string[] {
  return row.processes ?? (row.issue.process ? [row.issue.process] : []);
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

/** Highest-action issue for summaries. Stable within a severity bucket so the
 * engine's own ordering is preserved after critical > advisory > info. */
export function highestPriorityIssue(
  issues: readonly IndexedIssue[]
): IndexedIssue | null {
  const rank: Record<DfmSeverityBucket, number> = {
    critical: 0,
    advisory: 1,
    info: 2,
  };
  let best: IndexedIssue | null = null;
  let bestRank = Number.POSITIVE_INFINITY;
  for (const candidate of issues) {
    const candidateRank = rank[issueSeverityBucket(candidate.issue.severity)];
    if (candidateRank < bestRank) {
      best = candidate;
      bestRank = candidateRank;
    }
  }
  return best;
}

/* ------------------------------------------------------------------ */
/*  Flatten helpers                                                    */
/* ------------------------------------------------------------------ */

type Push = (issue: Issue, keyBase: string, process?: string) => void;

export function issueIdentity(issue: Issue): string {
  // Equal text alone must not collapse distinct severities, locations or
  // measurement evidence into whichever process happened to arrive first.
  return JSON.stringify([issue.code, issue.message, issue.severity, issue.region_center,
    issue.measured_value, issue.required_value, issue.measurement_unit, issue.scope,
    issue.fix_suggestion, issue.citation,
    // A capped sample cannot establish the size of a union. Keep different
    // incomplete face sets separate instead of inventing a total count.
    issue.affected_faces_truncated || (issue.affected_face_count ?? 0) > (issue.affected_faces_sample?.length ?? 0)
      ? [issue.affected_face_count, issue.affected_faces_sample] : null]);
}

export function issueWithFaces(issue: Issue, faces: number[]): Issue {
  return { ...issue, affected_faces_sample: faces,
    affected_face_count: issue.affected_face_count == null || issue.affected_faces_truncated
      || issue.affected_face_count > (issue.affected_faces_sample?.length ?? 0)
      ? issue.affected_face_count : faces.length };
}

/** Dedup matching evidence, retaining canonical keys, faces and process membership. */
export function collectIssues(build: (push: Push) => void): IndexedIssue[] {
  const seen = new Map<string, IndexedIssue>();
  const keys = new Set<string>();
  const push: Push = (issue, keyBase, process) => {
    const id = issueIdentity(issue);
    const owner = process || issue.process;
    const processes = owner ? [owner] : [];
    const faces = issue.affected_faces_sample ?? [];
    const existing = seen.get(id);
    if (existing) {
      existing.faces = Array.from(new Set([...existing.faces, ...faces]));
      existing.issue = issueWithFaces(existing.issue, existing.faces);
      existing.processes = Array.from(new Set([...issueProcesses(existing), ...processes]));
    } else {
      // Several cost estimates can reuse a process/index while carrying
      // different evidence. Keep the first key and disambiguate later rows.
      let key = keyBase;
      for (let suffix = 1; keys.has(key); suffix++) key = `${keyBase}:${suffix}`;
      keys.add(key);
      seen.set(id, { key, issue, faces: [...faces], processes });
    }
  };
  build(push);
  return Array.from(seen.values());
}

/** Merge universal + EVERY per-process issue (the full candidate matrix). */
export function flattenIssues(result: ValidationResult): IndexedIssue[] {
  return collectIssues((push) => {
    result.universal_issues.forEach((iss, i) => push(iss, `u${i}`));
    result.process_scores.forEach((ps) =>
      ps.issues.forEach((iss, i) => push(iss, `${ps.process}#${i}`, ps.process))
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
  return collectIssues((push) => {
    result.universal_issues.forEach((iss, i) => push(iss, `u${i}`));
    result.process_scores.forEach((ps) => {
      if (!inScope.has(ps.process)) return;
      ps.issues.forEach((iss, i) => push(iss, `${ps.process}#${i}`, ps.process));
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

export type RouteScopedVerdict = "pass" | "issues" | "fail" | "unknown";

/**
 * Partition the full candidate matrix into { route, extra } by issue identity
 * (matching evidence), keeping the CANONICAL keys from `flattenIssues` on every row.
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
    summary.scoped.map((i) => issueIdentity(i.issue))
  );
  const onRoute = (i: IndexedIssue) =>
    routeIds.has(issueIdentity(i.issue));
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

/** Verdict for the route the user is actually being told to use. The backend's
 * `overall_verdict` can summarize every candidate process; it must not turn an
 * FDM recommendation amber because CNC turning rejected the same geometry. */
export function routeScopedDfmVerdict(
  result: ValidationResult | null | undefined,
  recommendedProcess?: string | null
): RouteScopedVerdict {
  if (!result) return "unknown";
  const process = recommendedProcess?.trim() ?? "";
  if (!process) return result.overall_verdict;
  const partition = partitionDfmByRoute(result, process);
  if (partition.counts.critical > 0) return "fail";
  if (partition.counts.advisory > 0) return "issues";
  const routeScore = result.process_scores.find((score) => score.process === process);
  return routeScore?.verdict ?? result.overall_verdict;
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
