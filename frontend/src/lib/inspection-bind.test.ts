/**
 * Unit tests for the pure Findings-API binding core (Inspection experience).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (Node >= 22.6). Type-only imports from `@/lib/*` are erased, so this
 * resolves without a path-alias loader, exactly like the other pure-lib suites.
 *
 * Proves the honesty contract of each binding:
 *   (a) citationRef → a chip ONLY when `standard` is present; a descriptor when
 *       only `text` survives; null when uncited — no empty/fake citation;
 *   (b) affectedFacesSummary reports the TRUE `affected_face_count` and flags the
 *       2000-cap truncation honestly (shown vs true), null when unlocalized;
 *   (c) costBlockerLocators flattens `dfm_blocker_details` into locatable
 *       IndexedIssue rows (dedup by code|message, face-union) — [] pre-relink.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  citationRef,
  citationChipLabel,
  affectedFacesSummary,
  isWholePart,
  costBlockerLocators,
  hasLocatableCostBlocker,
} from "./inspection-bind.ts";

/* ---- 1. citations -------------------------------------------------- */

test("citationRef: standard present → a citation chip (kind=standard)", () => {
  const ref = citationRef({ standard: "AMS 4928", clause: "§3.1", text: "min wall" });
  assert.equal(ref?.kind, "standard");
  assert.equal(ref?.kind === "standard" && ref.standard, "AMS 4928");
  assert.equal(ref?.kind === "standard" && ref.clause, "§3.1");
  assert.equal(citationChipLabel(ref!), "AMS 4928 · §3.1");
});

test("citationRef: standard present, no clause → chip label omits the middot", () => {
  const ref = citationRef({ standard: "ISO 2768" });
  assert.equal(citationChipLabel(ref!), "ISO 2768");
});

test("citationRef: no standard, only text → the honest descriptor case", () => {
  const ref = citationRef({ text: "3-axis: draft not required" });
  assert.equal(ref?.kind, "descriptor");
  assert.equal(ref?.kind === "descriptor" && ref.text, "3-axis: draft not required");
  assert.equal(citationChipLabel(ref!), "3-axis: draft not required");
});

test("citationRef: absent / empty citation → null (never a fake chip)", () => {
  assert.equal(citationRef(null), null);
  assert.equal(citationRef(undefined), null);
  assert.equal(citationRef({}), null);
  assert.equal(citationRef({ standard: "   ", text: "  " }), null);
});

/* ---- 2. affected faces -------------------------------------------- */

test("affectedFacesSummary: untruncated → TRUE count label", () => {
  const s = affectedFacesSummary({
    code: "THIN_WALL",
    severity: "error",
    message: "m",
    fix_suggestion: null,
    affected_face_count: 47,
    affected_faces_sample: new Array(47).fill(0).map((_, i) => i),
  });
  assert.equal(s?.count, 47);
  assert.equal(s?.truncated, false);
  assert.equal(s?.label, "47 faces");
});

test("affectedFacesSummary: singular face reads 'face' not 'faces'", () => {
  const s = affectedFacesSummary({
    code: "X", severity: "warning", message: "m", fix_suggestion: null,
    affected_face_count: 1, affected_faces_sample: [0],
  });
  assert.equal(s?.label, "1 face");
});

test("affectedFacesSummary: capped at 2000 → honest 'shown of true' label", () => {
  const s = affectedFacesSummary({
    code: "THIN_WALL", severity: "error", message: "m", fix_suggestion: null,
    affected_face_count: 5231,
    affected_faces_sample: new Array(2000).fill(0),
    affected_faces_truncated: true,
  });
  assert.equal(s?.count, 5231);
  assert.equal(s?.sampleCount, 2000);
  assert.equal(s?.truncated, true);
  assert.equal(s?.label, "2,000 of 5,231 faces shown");
});

test("affectedFacesSummary: no faces (whole-part finding) → null", () => {
  assert.equal(
    affectedFacesSummary({
      code: "EXCEEDS_BUILD_VOLUME", severity: "error", message: "m",
      fix_suggestion: null, scope: "whole_part",
    }),
    null
  );
});

test("isWholePart reads the honest scope marker", () => {
  assert.equal(isWholePart({ code: "A", severity: "error", message: "m", fix_suggestion: null, scope: "whole_part" }), true);
  assert.equal(isWholePart({ code: "A", severity: "error", message: "m", fix_suggestion: null, scope: "localized" }), false);
  assert.equal(isWholePart({ code: "A", severity: "error", message: "m", fix_suggestion: null }), false);
});

/* ---- 3. cost-blocker relink --------------------------------------- */

function est(overrides: Record<string, unknown>) {
  return {
    process: "cnc_milling", material: "AL6061", quantity: 100,
    unit_cost_usd: 1, fixed_cost_usd: 0, variable_cost_usd: 1,
    est_error_band_pct: 0, dfm_ready: false, dfm_verdict: "fail",
    dfm_score: 0, dfm_blockers: [], line_items: {}, drivers: [],
    lead_time: { low_days: 1, high_days: 2, mid_days: 1, components: {}, capacity: {} },
    ...overrides,
  };
}

test("costBlockerLocators: relinks blockers into locatable IndexedIssue rows", () => {
  const rows = costBlockerLocators(
    est({
      dfm_blocker_details: [
        { code: "THIN_WALL", severity: "error", message: "thin", fix_suggestion: null,
          affected_face_count: 12, affected_faces_sample: [3, 4, 5] },
      ],
    }) as never
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].issue.code, "THIN_WALL");
  assert.deepEqual(rows[0].faces, [3, 4, 5]);
  assert.match(rows[0].key, /^cost:cnc_milling#0$/);
});

test("costBlockerLocators: dedup by code|message unions the face samples", () => {
  const rows = costBlockerLocators(
    est({
      dfm_blocker_details: [
        { code: "THIN_WALL", severity: "error", message: "thin", fix_suggestion: null, affected_faces_sample: [1, 2] },
        { code: "THIN_WALL", severity: "error", message: "thin", fix_suggestion: null, affected_faces_sample: [2, 3] },
      ],
    }) as never
  );
  assert.equal(rows.length, 1);
  assert.deepEqual([...rows[0].faces].sort((a, b) => a - b), [1, 2, 3]);
});

test("costBlockerLocators: [] when the report predates the relink", () => {
  assert.deepEqual(costBlockerLocators(est({}) as never), []);
});

test("hasLocatableCostBlocker: true only when a blocker carries faces", () => {
  assert.equal(
    hasLocatableCostBlocker([est({ dfm_blocker_details: [{ code: "A", severity: "error", message: "m", fix_suggestion: null, affected_faces_sample: [1] }] }) as never]),
    true
  );
  assert.equal(
    hasLocatableCostBlocker([est({ dfm_blocker_details: [{ code: "A", severity: "error", message: "m", fix_suggestion: null }] }) as never]),
    false
  );
  assert.equal(hasLocatableCostBlocker([est({}) as never]), false);
});
