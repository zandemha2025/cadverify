/**
 * Recent-parts strip — the HONEST shape of the analyses-list row (FE-3).
 *
 * The landing "my recent parts" chips bind to `GET /api/v1/analyses` (the list
 * endpoint served by `backend/src/api/history.py::list_analyses`). That endpoint
 * returns, per row, EXACTLY these fields:
 *
 *   { id, filename, file_type, verdict, face_count, duration_ms,
 *     created_at, process_count, best_process }
 *
 * where `id` holds the ULID that the detail route `/analyses/{id}` resolves
 * (the backend detail handler matches on `Analysis.ulid`). It does NOT return
 * `ulid`, `overall_verdict`, or `analysis_time_ms` — the fields the legacy
 * `AnalysisSummary` type in `lib/api.ts` wrongly claims. Binding to those
 * produced `/analyses/undefined` dead links and empty (fabricated) verdict
 * badges, so this module owns the real shape and a pure mapper that reads ONLY
 * fields the endpoint actually returns. Kept free of React/DOM so it runs on the
 * repo's `node --test` runner.
 */

export type Verdict = "pass" | "issues" | "fail" | "unknown";

/** A single row of the REAL `GET /api/v1/analyses` list response. */
export interface AnalysisListRow {
  /** ULID — the identifier the detail route `/analyses/{id}` resolves. */
  id: string;
  filename: string;
  file_type: string;
  verdict: Verdict;
  face_count: number;
  duration_ms: number;
  created_at: string;
  process_count: number;
  best_process: string | null;
}

/** View model for one recent-part chip — only real, renderable fields. */
export interface RecentPartChip {
  /** ULID — used as the React key and to build the detail href. */
  id: string;
  filename: string;
  verdict: Verdict;
  createdAt: string;
  /** Resolves to a real page: `/analyses/{ulid}`. */
  href: string;
}

/**
 * Map a real analyses-list row to a recent-part chip. Reads ONLY the fields the
 * list endpoint actually returns — never the fabricated `ulid` /
 * `overall_verdict` the old type advertised.
 */
export function toRecentPartChip(row: AnalysisListRow): RecentPartChip {
  return {
    id: row.id,
    filename: row.filename,
    verdict: row.verdict,
    createdAt: row.created_at,
    href: `/analyses/${row.id}`,
  };
}
