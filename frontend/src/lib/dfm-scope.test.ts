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
  routeScopedDfmVerdict,
  severityCounts,
  flattenIssues,
  flattenScopedIssues,
  highestPriorityIssue,
  collectIssues,
  dfmScopedFlagsEnabled,
} from "./dfm-scope.ts";
import { groupPinpointIssues } from "./pinpoint-groups.ts";
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

test("route verdict ignores failures that belong only to other candidate processes", () => {
  const result = bracketResult();
  result.overall_verdict = "fail";
  assert.equal(routeScopedDfmVerdict(result, "mjf"), "issues");
  assert.notEqual(routeScopedDfmVerdict(result, "mjf"), result.overall_verdict);
});

test("a missing route cannot inherit another process's passing verdict", () => {
  const result = bracketResult();
  result.universal_issues = [];
  result.overall_verdict = "pass";
  assert.equal(routeScopedDfmVerdict(result, "cnc_5axis"), "unknown");
  assert.equal(routeScopedDfmVerdict(result, null), "unknown");
  result.universal_issues = [issue("INVALID", "error")];
  assert.equal(routeScopedDfmVerdict(result, "cnc_5axis"), "fail");
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

// Regression: QA ISSUE-006 — “first issue” means the most actionable route issue,
// not whichever universal/process analyzer happened to serialize first.
test("highestPriorityIssue prefers critical while preserving stable ties", () => {
  const ordered = flattenIssues(bracketResult());
  assert.equal(highestPriorityIssue(ordered)?.issue.severity, "error");
  assert.equal(highestPriorityIssue([]), null);
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

test("identical warnings retain every process through flatten, scope and grouping", () => {
  const result = bracketResult();
  result.universal_issues = [];
  const processes = ["dlp", "mjf", "injection_molding"];
  result.process_scores = processes.map((p) => ps(p, [
    issue("WALL_THICKNESS_PRECISION", "warning", "Check source precision", p, [1, 2]),
  ]));
  const original = structuredClone(result);
  const all = flattenIssues(result);
  assert.equal(all.length, 1);
  assert.equal(all[0].key, "dlp#0");
  assert.deepEqual(groupPinpointIssues(all)[0].processes, processes);
  const scoped = flattenScopedIssues(result, ["mjf"]);
  assert.deepEqual(groupPinpointIssues(scoped)[0].processes, ["mjf"]);
  const partition = partitionDfmByRoute(result, "mjf");
  assert.equal(partition.route[0].key, all[0].key);
  assert.equal(partition.counts.advisory, 1);
  assert.equal(partition.extra.length, 0);
  assert.deepEqual(result, original, "UI projection must not mutate the stored report");
});

test("process score supplies membership when legacy issues omit process", () => {
  const result = bracketResult();
  result.universal_issues = [];
  result.process_scores = ["fdm", "mjf"].map((p) => ps(p, [issue("A", "warning")]));
  assert.deepEqual(groupPinpointIssues(flattenIssues(result))[0].processes, ["fdm", "mjf"]);
});

test("duplicate text cannot hide another route's severity or a distinct location", () => {
  const result = bracketResult();
  result.universal_issues = [];
  result.process_scores = [ps("mjf", [issue("A", "warning", "same", "mjf")]),
    ps("fdm", [issue("A", "error", "same", "fdm")])];
  assert.equal(routeScopedDfmVerdict(result, "fdm"), "fail");
  assert.equal(routeScopedDfmVerdict(result, "mjf"), "issues");
  result.process_scores[1].issues[0].severity = "warning";
  result.process_scores[0].issues[0].region_center = [1, 2, 3];
  result.process_scores[1].issues[0].region_center = [4, 5, 6];
  assert.equal(groupPinpointIssues(flattenIssues(result)).length, 2);
});

test("merged face counts describe the union; incomplete samples keep their own totals", () => {
  const a = { ...issue("A", "warning", "same", "mjf", [1, 2]), affected_face_count: 2 };
  const b = { ...issue("A", "warning", "same", "fdm", [2, 3]), affected_face_count: 2 };
  const rows = () => collectIssues((push) => { push(a, "a"); push(b, "b"); });
  const merged = rows();
  assert.equal(merged[0].issue.affected_face_count, 3);
  assert.deepEqual(merged[0].issue.affected_faces_sample, [1, 2, 3]);
  assert.equal(a.affected_face_count, 2);
  a.affected_face_count = b.affected_face_count = 100;
  assert.equal(rows().length, 2, "unknown overlap cannot produce a truthful merged total");
});
