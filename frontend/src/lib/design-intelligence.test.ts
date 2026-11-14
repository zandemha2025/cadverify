import { test } from "node:test";
import assert from "node:assert/strict";
import {
  canRecordAnalysisMemory,
  designIntelligenceEnabled,
  designIntelligenceEmptyMessage,
  evidenceTimeRange,
  findingRefForPriorityFix,
  isSafeDesignIntelligenceResponse,
  isSafeOrgPrecedentResponse,
  safeEvidenceUrl,
} from "./design-intelligence.ts";
import {
  fetchAnalysisDesignIntelligence,
  fetchAnalysisFeedback,
  fetchAnalysisPrecedents,
  recordAnalysisFeedback,
} from "./api.ts";

test("analysis memory writes require analyst-or-higher role", () => {
  assert.equal(canRecordAnalysisMemory("viewer"), false);
  assert.equal(canRecordAnalysisMemory(null), false);
  assert.equal(canRecordAnalysisMemory("analyst"), true);
  assert.equal(canRecordAnalysisMemory("admin"), true);
  assert.equal(canRecordAnalysisMemory("superadmin"), true);
});

test("design intelligence is off unless explicitly enabled", () => {
  assert.equal(designIntelligenceEnabled(undefined), false);
  assert.equal(designIntelligenceEnabled("0"), false);
  assert.equal(designIntelligenceEnabled("true"), true);
  assert.equal(designIntelligenceEnabled(" 1 "), true);
});

test("advisory empty states preserve the deterministic finding", () => {
  assert.match(designIntelligenceEmptyMessage("no_match"), /finding above is unchanged/);
  assert.match(
    designIntelligenceEmptyMessage(
      "no_match",
      "no_relevant_precedent_in_bounded_index",
      true
    ),
    /unindexed eligible records may contain additional context/
  );
  assert.match(
    designIntelligenceEmptyMessage("unavailable", "no_eligible_knowledge_records"),
    /No production-eligible design context/
  );
  assert.equal(designIntelligenceEmptyMessage("available"), null);
  assert.equal(designIntelligenceEmptyMessage("research_only"), null);
});

test("evidence timestamps are compact and reject unusable ranges", () => {
  assert.equal(evidenceTimeRange(12.5, 18), "0:12–0:18");
  assert.equal(evidenceTimeRange(65, null), "1:05");
  assert.equal(evidenceTimeRange(20, 19), "0:20");
  assert.equal(evidenceTimeRange(null, 18), null);
});

test("only http sources become clickable", () => {
  assert.equal(
    safeEvidenceUrl("https://huggingface.co/datasets/example"),
    "https://huggingface.co/datasets/example"
  );
  assert.equal(safeEvidenceUrl("javascript:alert(1)"), null);
  assert.equal(safeEvidenceUrl("not a url"), null);
});

test("ID-scoped intelligence rejects another analysis or finding", async () => {
  const locator = {
    scope: "process" as const,
    code: "THIN_WALL",
    occurrence: 0,
    process: "injection_molding",
  };
  const advisory = {
    status: "unavailable",
    reason: "no_eligible_knowledge_records",
    finding_code: "THIN_WALL",
    authority: "ADVISORY_ONLY",
    engineering_authority: "NONE",
    provenance: "THIRD_PARTY_UNVERIFIED",
    may_affect_deterministic_verdict: false,
    is_manufacturing_ground_truth: false,
    eligible_records_scanned: 0,
    indexed_records: 0,
    index_truncated: false,
    possible_intents: [],
    relevant_requirements: [],
    workflow_evidence: [],
    analysis_id: "ANALYSIS-B",
    finding_ref: locator,
  };
  const precedent = {
    status: "unavailable",
    reason: "target_geometry_unusable",
    analysis_id: "ANALYSIS-B",
    authority: "ADVISORY_ONLY",
    may_affect_deterministic_verdict: false,
    corpus_version: "org-analyses/v1",
    algorithm_version: "geometry-precedent/v3",
    analysis_version: "1",
    current_analysis_version: "1",
    max_distance: 1,
    candidate_limit: 100,
    candidates_examined: 0,
    search_truncated: false,
    cases: [],
    provenance: {
      corpus: "ACTIVE_ORGANIZATION_SAVED_ANALYSES",
      similarity: "DETERMINISTIC_DERIVED_FROM_MEASURED_GEOMETRY",
    },
  };
  const feedback = {
    analysis_id: "ANALYSIS-B",
    saved: true,
    decision: null,
    advisory: null,
    finding_ref: null,
    source: "authenticated_user",
    provenance: "user",
  };
  const responses: unknown[] = [
    advisory,
    { ...advisory, analysis_id: "ANALYSIS-A", finding_ref: { ...locator, code: "OTHER" } },
    precedent,
    feedback,
    feedback,
    {
      ...feedback,
      analysis_id: "ANALYSIS-A",
      decision: "redesign",
      advisory: "helpful",
      finding_ref: locator,
    },
  ];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(responses.shift()), { status: 200 })) as typeof fetch;
  try {
    await assert.rejects(
      fetchAnalysisDesignIntelligence("ANALYSIS-A", locator),
      /Unsafe design intelligence response/
    );
    await assert.rejects(
      fetchAnalysisDesignIntelligence("ANALYSIS-A", locator),
      /Unsafe design intelligence response/
    );
    await assert.rejects(
      fetchAnalysisPrecedents("ANALYSIS-A"),
      /Unsafe organization precedent response/
    );
    await assert.rejects(
      recordAnalysisFeedback("ANALYSIS-A", { decision: "redesign" }),
      /Unsafe analysis feedback response/
    );
    await assert.rejects(
      fetchAnalysisFeedback("ANALYSIS-A"),
      /Unsafe analysis feedback response/
    );
    const restored = await fetchAnalysisFeedback("ANALYSIS-A");
    assert.equal(restored.decision, "redesign");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("missing feedback is an ordinary empty read", async () => {
  const findingRef = {
    scope: "universal" as const,
    code: "THIN_WALL",
    occurrence: 0,
  };
  const empty = {
    analysis_id: "ANALYSIS-A",
    saved: true,
    decision: null,
    advisory: null,
    finding_ref: null,
    source: "authenticated_user",
    provenance: "user",
  };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(empty), { status: 200 })) as typeof fetch;
  try {
    assert.deepEqual(await fetchAnalysisFeedback("ANALYSIS-A"), empty);
    assert.deepEqual(
      await fetchAnalysisFeedback("ANALYSIS-A", findingRef),
      empty
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("unsafe advisory responses are rejected before any evidence can render", () => {
  const safe = {
    status: "available",
    reason: null,
    finding_code: "THIN_WALL",
    authority: "ADVISORY_ONLY",
    engineering_authority: "NONE",
    provenance: "THIRD_PARTY_UNVERIFIED",
    may_affect_deterministic_verdict: false,
    is_manufacturing_ground_truth: false,
    eligible_records_scanned: 3,
    indexed_records: 3,
    index_truncated: false,
    possible_intents: [{
      candidate: "Housing",
      provenance: "THIRD_PARTY_UNVERIFIED",
      license_status: "CC-BY-4.0",
      production_eligible: true,
    }],
    relevant_requirements: [
      {
        excerpt: "Retain the mounting face",
        provenance: "THIRD_PARTY_UNVERIFIED",
        license_status: "CC-BY-4.0",
        production_eligible: true,
      },
    ],
    workflow_evidence: [
      {
        excerpt: "Added a fillet",
        provenance: "THIRD_PARTY_UNVERIFIED",
        license_status: "CC-BY-4.0",
        production_eligible: true,
      },
    ],
  };
  assert.equal(isSafeDesignIntelligenceResponse(safe), true);
  assert.equal(
    isSafeDesignIntelligenceResponse({
      ...safe,
      status: "no_match",
      reason: "no_relevant_precedent_in_bounded_index",
      eligible_records_scanned: 6,
      indexed_records: 3,
      index_truncated: true,
      possible_intents: [],
      relevant_requirements: [],
      workflow_evidence: [],
    }),
    true
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({
      ...safe,
      status: "no_match",
      reason: "no_relevant_precedent",
      eligible_records_scanned: 6,
      indexed_records: 3,
      index_truncated: true,
      possible_intents: [],
      relevant_requirements: [],
      workflow_evidence: [],
    }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({ ...safe, indexed_records: 4 }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({ ...safe, authority: "ENGINEERING" }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({ ...safe, engineering_authority: "FULL" }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({ ...safe, provenance: "ENGINE_VERIFIED" }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({
      ...safe,
      may_affect_deterministic_verdict: true,
    }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({ ...safe, is_manufacturing_ground_truth: true }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({ ...safe, workflow_evidence: [null] }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({
      ...safe,
      workflow_evidence: [
        {
          excerpt: "Unlicensed evidence",
          provenance: "THIRD_PARTY_UNVERIFIED",
          license_status: "UNDECLARED",
          production_eligible: false,
        },
      ],
    }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({
      ...safe,
      status: "research_only",
      research_mode: true,
      possible_intents: safe.possible_intents.map((row) => ({
        ...row,
        license_status: "UNDECLARED",
        production_eligible: false,
      })),
      relevant_requirements: [],
      workflow_evidence: [],
    }),
    true
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({
      ...safe,
      status: "research_only",
      research_mode: false,
    }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({
      ...safe,
      workflow_evidence: [
        {
          excerpt: "Added a fillet",
          provenance: "THIRD_PARTY_UNVERIFIED",
          license_status: "CC-BY-4.0",
          production_eligible: true,
          application: {},
        },
      ],
    }),
    false
  );
  assert.equal(
    isSafeDesignIntelligenceResponse({
      ...safe,
      workflow_evidence: [
        {
          excerpt: "Added a fillet",
          provenance: "THIRD_PARTY_UNVERIFIED",
          license_status: "CC-BY-4.0",
          production_eligible: true,
          start_s: Number.NaN,
        },
      ],
    }),
    false
  );
});

test("priority fixes map back to stable server-owned finding locators", () => {
  const validation = {
    universal_issues: [
      { code: "OPEN_MESH", message: "Mesh is open" },
    ],
    process_scores: [
      {
        process: "cnc_3axis",
        issues: [
          { code: "DEEP_POCKET", message: "First pocket" },
          { code: "DEEP_POCKET", message: "Second pocket" },
        ],
      },
    ],
  } as never;
  assert.deepEqual(
    findingRefForPriorityFix(validation, {
      code: "OPEN_MESH",
      severity: "error",
      message: "Mesh is open",
      process: "all",
      fix: null,
      measured_value: null,
      required_value: null,
    }),
    { scope: "universal", code: "OPEN_MESH", occurrence: 0 }
  );
  assert.deepEqual(
    findingRefForPriorityFix(validation, {
      code: "DEEP_POCKET",
      severity: "warning",
      message: "Second pocket",
      process: "cnc_3axis",
      fix: null,
      measured_value: null,
      required_value: null,
    }),
    {
      scope: "process",
      process: "cnc_3axis",
      code: "DEEP_POCKET",
      occurrence: 1,
    }
  );
  assert.equal(
    findingRefForPriorityFix(validation, {
      code: "MISSING",
      severity: "info",
      message: "Not persisted",
      process: "cnc_3axis",
      fix: null,
      measured_value: null,
      required_value: null,
    }),
    null
  );
});

test("organization precedents accept measured advisory cases and reject unsafe authority", () => {
  const safe = {
    status: "available",
    reason: null,
    analysis_id: "current",
    authority: "ADVISORY_ONLY",
    may_affect_deterministic_verdict: false,
    corpus_version: "org-saved-analyses/v1",
    algorithm_version: "geometry-precedent/v2",
    analysis_version: "v1",
    current_analysis_version: "v2",
    max_distance: 0.35,
    candidate_limit: 500,
    candidates_examined: 12,
    search_truncated: false,
    provenance: {
      corpus: "ACTIVE_ORGANIZATION_SAVED_ANALYSES",
      similarity: "DETERMINISTIC_DERIVED_FROM_MEASURED_GEOMETRY",
    },
    cases: [{
      analysis_id: "prior",
      analysis_url: "/analyses/prior",
      analysis_api_url: "/api/v1/analyses/prior",
      filename: "prior.step",
      created_at: "2026-09-02T12:00:00Z",
      distance: 0.125,
      shared_geometry: [{
        name: "bbox_shape_ratios",
        target: [0.5, 0.8],
        candidate: [0.51, 0.79],
        provenance: "MEASURED_DERIVED",
      }],
      verdict: "conditional",
      best_process: "cnc_3axis",
      recommended_material: "aluminum",
      recommended_machine: null,
      analysis_version: "v1",
      stale: false,
      provenance: { similarity: "DETERMINISTIC" },
    }],
  };
  assert.equal(isSafeOrgPrecedentResponse(safe), true);
  assert.equal(
    isSafeOrgPrecedentResponse({ ...safe, may_affect_deterministic_verdict: true }),
    false
  );
  assert.equal(
    isSafeOrgPrecedentResponse({ ...safe, cases: [{ ...safe.cases[0], distance: Number.NaN }] }),
    false
  );
  assert.equal(
    isSafeOrgPrecedentResponse({ ...safe, cases: [{ ...safe.cases[0], distance: 0.5 }] }),
    false
  );
  assert.equal(
    isSafeOrgPrecedentResponse({ ...safe, cases: [{ ...safe.cases[0], analysis_url: "https://evil.example" }] }),
    false
  );
  assert.equal(
    isSafeOrgPrecedentResponse({ ...safe, status: "no_match", cases: [] }),
    true
  );
});
