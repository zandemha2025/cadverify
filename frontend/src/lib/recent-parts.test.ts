/**
 * Unit tests for the recent-parts mapper (frontend/src/lib/recent-parts.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest.
 *
 * Proves the FE-3 honesty fix: the "my recent parts" chip binds ONLY to fields
 * the REAL `GET /api/v1/analyses` list endpoint returns — `id` (the ULID that
 * `/analyses/{id}` resolves), `filename`, `verdict`, `created_at` — and NEVER to
 * the fabricated `ulid` / `overall_verdict` fields the old `AnalysisSummary`
 * type advertised (which produced `/analyses/undefined` dead links and empty
 * verdict badges).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { toRecentPartChip, type AnalysisListRow } from "./recent-parts.ts";

/** A row exactly as `backend/src/api/history.py::list_analyses` serialises it. */
function realRow(overrides: Partial<AnalysisListRow> = {}): AnalysisListRow {
  return {
    id: "01HQZ8ULID0000000000000001",
    filename: "bracket.step",
    file_type: "step",
    verdict: "issues",
    face_count: 128,
    duration_ms: 1234,
    created_at: "2026-07-02T10:00:00Z",
    process_count: 3,
    best_process: "cnc_milling",
    ...overrides,
  };
}

test("toRecentPartChip maps only the real fields the endpoint returns", () => {
  const chip = toRecentPartChip(realRow());
  assert.deepEqual(chip, {
    id: "01HQZ8ULID0000000000000001",
    filename: "bracket.step",
    verdict: "issues",
    createdAt: "2026-07-02T10:00:00Z",
    href: "/analyses/01HQZ8ULID0000000000000001",
  });
});

test("href routes to a real detail page via the list's `id` (the ULID)", () => {
  const chip = toRecentPartChip(realRow({ id: "01ABCDEF00000000000000000X" }));
  // The detail route /analyses/[id] → fetchAnalysis(id) → GET /analyses/{ulid}.
  assert.equal(chip.href, "/analyses/01ABCDEF00000000000000000X");
  // Never the fabricated dead link.
  assert.notEqual(chip.href, "/analyses/undefined");
});

test("verdict is taken verbatim from the real `verdict` field", () => {
  for (const v of ["pass", "issues", "fail", "unknown"] as const) {
    assert.equal(toRecentPartChip(realRow({ verdict: v })).verdict, v);
  }
});

test("does not read fabricated ulid / overall_verdict fields", () => {
  // A row that has ONLY the real fields (no `ulid`, no `overall_verdict`) — the
  // way the endpoint actually responds — must still map to a working chip.
  const row = realRow();
  const asRecord = row as unknown as Record<string, unknown>;
  assert.equal(asRecord.ulid, undefined, "endpoint has no `ulid`");
  assert.equal(asRecord.overall_verdict, undefined, "endpoint has no `overall_verdict`");

  const chip = toRecentPartChip(row);
  assert.ok(chip.id.length > 0);
  assert.ok(!chip.href.includes("undefined"));
  assert.equal(chip.verdict, "issues");
});
