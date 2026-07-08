/**
 * Unit tests for the pure DFM scoping core (FRAGILE-1).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (Node >= 22.6). No vitest/jest needed. See package.json "test".
 *
 * Proves:
 *   (a) a part whose recommended process is DFM-clean shows 0 critical in the
 *       headline even when OTHER processes have errors;
 *   (b) part-level (universal) issues still count in the headline;
 *   (c) the full candidate matrix count is still available;
 *   (d) the off-route partition is correct and issues shared with the route
 *       stay on the route (not double-counted as "extra");
 *   (e) the feature flag defaults ON (scoped).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  scopedDfmSummary,
  partitionDfmByRoute,
  severityCounts,
  flattenIssues,
  dfmScopedFlagsEnabled,
} from "./dfm-scope.ts";
import type { Issue, ProcessScore, ValidationResult } from "@/lib/api";

/* ---- fixture helpers -------------------------------------------- */

function issue(
  code: string,
  severity: Issue["severity"],
  message = code,
  process?: string,
  faces?: number[]
): Issue {
  return {
    code,
    severity,
    message,
    fix_suggestion: null,
    ...(process ? { process } : {}),
    ...(faces ? { affected_faces_sample: faces } : {}),
  };
}

function ps(process: string, issues: Issue[]): ProcessScore {
  return {
    process,
    score: 50,
    verdict: issues.some((i) => i.severity === "error") ? "fail" : "issues",
    recommended_material: null,
    recommended_machine: null,
    estimated_cost_factor: null,
    issues,
  };
}

/**
 * The miata top-bracket shape: MJF (the recommended route) is DFM-clean, but the
 * casting/molding processes each raise several errors, plus one real part-level
 * (universal) geometry issue. The legacy union headline reads scary; the scoped
 * headline must reflect MJF only + the universal issue.
 */
function bracketResult(): ValidationResult {
  return {
    filename: "miata-top-bracket.stl",
    file_type: "stl",
    overall_verdict: "issues",
    best_process: "mjf",
    analysis_time_ms: 1234,
    geometry: {} as ValidationResult["geometry"],
    segments: [],
    universal_issues: [
      // a real, process-independent part-level flag (must always count)
      issue("NON_WATERTIGHT", "warning", "Mesh is not watertight"),
    ],
    process_scores: [
      // recommended route — DFM-clean
      ps("mjf", []),
      // off-route processes that inflate the union with "critical" errors
      ps("die_casting", [
        issue("DRAFT_ANGLE", "error", "Insufficient draft angle", "die_casting"),
        issue("WALL_THIN", "error", "Wall too thin for casting", "die_casting"),
      ]),
      ps("injection_molding", [
        issue("UNDERCUT", "error", "Undercut requires side action", "injection_molding"),
        issue("SINK_MARK", "warning", "Sink mark risk", "injection_molding"),
      ]),
      ps("forging", [
        issue("PARTING_LINE", "error", "No feasible parting line", "forging"),
      ]),
    ],
    priority_fixes: [],
  };
}

/* ---- (a) + (b) recommended route clean => 0 critical, universal counts */

test("clean recommended route shows 0 critical even when other processes error", () => {
  const result = bracketResult();
  const summary = scopedDfmSummary(result, "mjf");

  // universal watertight warning still counts (part-level, always real)
  assert.equal(summary.counts.total, 1, "headline counts only universal + MJF");
  assert.equal(summary.counts.critical, 0, "MJF is clean => 0 critical in headline");
  assert.equal(summary.counts.advisory, 1, "the universal watertight warning counts");
  assert.equal(summary.recommendedProcess, "mjf");
});

/* ---- (c) full matrix count still available ---------------------- */

test("full candidate matrix count is still available", () => {
  const result = bracketResult();
  const summary = scopedDfmSummary(result, "mjf");

  // union = 1 universal + 2 die_casting + 2 injection + 1 forging = 6
  assert.equal(summary.allCounts.total, 6);
  assert.equal(summary.allCounts.critical, 4, "4 errors across off-route processes");
  assert.equal(summary.candidateProcessCount, 4);
  // sanity: flattenIssues (the legacy union) matches allCounts
  assert.equal(flattenIssues(result).length, 6);
});

/* ---- (d) route/extra partition, canonical keys ------------------ */

test("partition splits route vs off-route candidates without double counting", () => {
  const result = bracketResult();
  const part = partitionDfmByRoute(result, "mjf");

  assert.equal(part.route.length, 1, "only the universal issue is on the MJF route");
  assert.equal(part.route[0].issue.code, "NON_WATERTIGHT");
  assert.equal(part.extra.length, 5, "5 issues live only on off-route processes");
  assert.equal(part.route.length + part.extra.length, part.all.length);

  // every rendered row key is unique (route + extra render together)
  const keys = [...part.route, ...part.extra].map((i) => i.key);
  assert.equal(new Set(keys).size, keys.length, "no duplicate React keys");
});

test("an issue shared by the recommended route stays on the route, not extra", () => {
  const result = bracketResult();
  // give MJF a real critical flag that ALSO appears on an off-route process
  const shared = issue("OVERHANG", "error", "Steep overhang", "mjf", [7, 8]);
  result.process_scores[0] = ps("mjf", [shared]);
  result.process_scores[1].issues.unshift(
    issue("OVERHANG", "error", "Steep overhang", "die_casting", [9])
  );

  const part = partitionDfmByRoute(result, "mjf");
  // route = universal watertight + OVERHANG (deduped, on MJF) = 2
  assert.equal(part.counts.total, 2);
  assert.equal(part.counts.critical, 1, "the shared overhang counts on the route");
  // OVERHANG must NOT also appear in extra
  assert.ok(
    !part.extra.some((i) => i.issue.code === "OVERHANG"),
    "shared issue is not double-counted as off-route"
  );
});

/* ---- severity bucketing ----------------------------------------- */

test("severityCounts buckets error/warning/info and totals consistently", () => {
  const result = bracketResult();
  const counts = severityCounts(flattenIssues(result));
  assert.equal(counts.total, counts.critical + counts.advisory + counts.info);
});

/* ---- pre-cost fallback: no recommended process => universal only  */

test("with no recommended process the headline is part-level only", () => {
  const result = bracketResult();
  const summary = scopedDfmSummary(result, "");
  assert.equal(summary.counts.total, 1, "only universal part-level issues");
  assert.equal(summary.counts.critical, 0);
});

/* ---- (e) flag defaults ON (scoped) ------------------------------ */

test("dfmScopedFlagsEnabled defaults ON and honors explicit opt-out", () => {
  const prev = process.env.NEXT_PUBLIC_DFM_SCOPED_FLAGS;
  try {
    delete process.env.NEXT_PUBLIC_DFM_SCOPED_FLAGS;
    assert.equal(dfmScopedFlagsEnabled(), true, "unset => scoped ON");

    process.env.NEXT_PUBLIC_DFM_SCOPED_FLAGS = "0";
    assert.equal(dfmScopedFlagsEnabled(), false, "'0' => legacy union");

    process.env.NEXT_PUBLIC_DFM_SCOPED_FLAGS = "false";
    assert.equal(dfmScopedFlagsEnabled(), false, "'false' => legacy union");

    process.env.NEXT_PUBLIC_DFM_SCOPED_FLAGS = "1";
    assert.equal(dfmScopedFlagsEnabled(), true, "'1' => scoped ON");
  } finally {
    if (prev === undefined) delete process.env.NEXT_PUBLIC_DFM_SCOPED_FLAGS;
    else process.env.NEXT_PUBLIC_DFM_SCOPED_FLAGS = prev;
  }
});
