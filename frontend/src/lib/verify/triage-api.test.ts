import assert from "node:assert/strict";
import test from "node:test";

import {
  fetchRecurringBlockers,
  isRecurringBlockerRollup,
  mergeMakeabilityRows,
  type MakeabilityRow,
} from "./triage-api.ts";

const shell = {
  clusters: [],
  summary: {
    latest_part_count: 0,
    parts_with_blockers: 0,
    recurring_cluster_count: 0,
    recurring_affected_part_count: 0,
    stale_affected_part_count: 0,
    part_summary_count: 0,
    malformed_analysis_count: 0,
    malformed_part_summary_count: 0,
    truncated: false,
  },
  provenance: {
    source: "ACTIVE_ORGANIZATION_LATEST_SAVED_ANALYSES",
    algorithm_version: "blocker-clusters/v1",
    minimum_distinct_parts: 2,
    candidate_limit: 1000,
    scope: "WHOLE_ORGANIZATION",
    llm_inference: false,
  },
} as const;

test("recurring blocker guard rejects malformed affected parts", async () => {
  const unsafe = {
    ...shell,
    clusters: [
      {
        id: "cluster",
        code: "THIN_WALL",
        scope: "process",
        process: "injection_molding",
        severity: "error",
        message: "Wall too thin",
        fix_suggestion: null,
        affected_part_count: 1,
        count_basis: "distinct_latest_parts",
        severity_basis: "engine finding",
        stale: false,
        stale_part_count: 0,
        affected_parts: [{}],
        provenance: {},
      },
    ],
  };
  assert.equal(isRecurringBlockerRollup(unsafe), false);

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(unsafe), { status: 200 })) as typeof fetch;
  try {
    await assert.rejects(fetchRecurringBlockers(), /Unsafe recurring blocker response/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("capability pages append in order without duplicate parts", () => {
  const row = (part_key: string): MakeabilityRow => ({
    part_key,
    filename: `${part_key}.step`,
    makeability: { verdict: "makeable_not_on_owned", stale: false, gap: null },
  });

  const merged = mergeMakeabilityRows(
    [row("part-a"), row("part-b")],
    [row("part-b"), row("part-c")]
  );

  assert.deepEqual(
    merged.map((item) => item.part_key),
    ["part-a", "part-b", "part-c"]
  );
});
