/**
 * Unit tests for the Home desk's pure derivations (home-derive.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest, no jsdom.
 *
 * Proves the honesty contract of the Home surface:
 *   (a) an org with nothing real to act on yields an EMPTY queue — no fabricated
 *       "decision pending" rows, no ported demo fixtures;
 *   (b) a nudge appears ONLY on a KNOWN zero, never on an unknown (null) count;
 *   (c) governed change-requests surface only while status === "proposed";
 *   (d) the activity feed merges only real records + real governance events,
 *       newest-first, and invents nothing.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildQueue,
  buildActivity,
  proposedCount,
  assetLabel,
  shortDate,
  buildDayZeroSetup,
} from "./home-derive.ts";
import type { ChangeRequest } from "./governance-api.ts";
import type { CostDecisionSummary } from "@/lib/api";

function cr(over: Partial<ChangeRequest>): ChangeRequest {
  return {
    id: 1,
    ulid: "cr_1",
    org_id: "org_1",
    asset_type: "rate_card",
    target_version_id: 14,
    status: "proposed",
    title: "",
    note: "",
    proposed_by: 7,
    reviewed_by: null,
    created_at: "2026-07-04T10:00:00Z",
    decided_at: null,
    ...over,
  };
}

function rec(over: Partial<CostDecisionSummary>): CostDecisionSummary {
  return {
    id: "V1",
    filename: "part.stl",
    file_type: "stl",
    label: null,
    make_now_process: "mjf",
    crossover_qty: null,
    quantities: [1],
    created_at: "2026-07-01T00:00:00Z",
    is_public: false,
    share_url: null,
    ...over,
  };
}

test("empty org → empty queue (no fabricated rows), but counts still unknown", () => {
  // Everything unknown (null) → no nudges: we never guess.
  const q = buildQueue({
    changeRequests: [],
    machineCount: null,
    recordCount: null,
    realActualCount: null,
  });
  assert.equal(q.length, 0);
});

test("machineCount KNOWN 0 → declare-floor nudge; null → no nudge", () => {
  const withZero = buildQueue({
    changeRequests: [],
    machineCount: 0,
    recordCount: 0,
    realActualCount: null,
  });
  assert.equal(withZero.length, 1);
  assert.equal(withZero[0].key, "declare-floor");
  assert.equal(withZero[0].severity, "fail");
  assert.equal(withZero[0].go, "machines");

  const withNull = buildQueue({
    changeRequests: [],
    machineCount: null,
    recordCount: 0,
    realActualCount: null,
  });
  assert.equal(withNull.length, 0);
});

test("proposed change-requests surface; approved/rejected/draft do not", () => {
  const q = buildQueue({
    changeRequests: [
      cr({ id: 1, status: "proposed", title: "labor_rate bump" }),
      cr({ id: 2, status: "approved" }),
      cr({ id: 3, status: "rejected" }),
      cr({ id: 4, status: "draft" }),
    ],
    machineCount: 5,
    recordCount: 3,
    realActualCount: 2,
  });
  assert.equal(q.length, 1);
  assert.equal(q[0].key, "cr-1");
  assert.equal(q[0].title, "labor_rate bump");
  assert.equal(q[0].action, "Review");
  assert.equal(q[0].go, "calibration");
});

test("proposed CR with blank title falls back to an honest generated label", () => {
  const q = buildQueue({
    changeRequests: [cr({ id: 9, status: "proposed", title: "", asset_type: "shop_profile" })],
    machineCount: 5,
    recordCount: 1,
    realActualCount: 1,
  });
  assert.equal(q[0].title, "Shop profile change awaiting review");
});

test("send-actuals nudge only when records exist AND real actuals is a KNOWN 0", () => {
  // records present, actuals KNOWN 0 → nudge (hatched)
  const nudge = buildQueue({
    changeRequests: [],
    machineCount: 5,
    recordCount: 4,
    realActualCount: 0,
  });
  assert.equal(nudge.length, 1);
  assert.equal(nudge[0].key, "send-actuals");
  assert.equal(nudge[0].hatched, true);

  // no records yet → no send-actuals nudge (nothing to validate)
  const noRecords = buildQueue({
    changeRequests: [],
    machineCount: 5,
    recordCount: 0,
    realActualCount: 0,
  });
  assert.equal(noRecords.length, 0);

  // actuals unknown (null) → no nudge
  const unknown = buildQueue({
    changeRequests: [],
    machineCount: 5,
    recordCount: 4,
    realActualCount: null,
  });
  assert.equal(unknown.length, 0);

  // real actuals present → no nudge
  const validated = buildQueue({
    changeRequests: [],
    machineCount: 5,
    recordCount: 4,
    realActualCount: 3,
  });
  assert.equal(validated.length, 0);
});

test("day-zero org (machines 0, no records) shows only the floor nudge", () => {
  const q = buildQueue({
    changeRequests: [],
    machineCount: 0,
    recordCount: 0,
    realActualCount: 0,
  });
  assert.equal(q.length, 1);
  assert.equal(q[0].key, "declare-floor");
});

test("proposedCount counts only proposed", () => {
  assert.equal(
    proposedCount([
      cr({ id: 1, status: "proposed" }),
      cr({ id: 2, status: "proposed" }),
      cr({ id: 3, status: "approved" }),
      cr({ id: 4, status: "draft" }),
    ]),
    2
  );
  assert.equal(proposedCount([]), 0);
});

test("activity merges records + governance events, newest first, no fabrication", () => {
  const feed = buildActivity({
    records: [
      rec({ id: "V1", filename: "shaft.stl", created_at: "2026-07-01T00:00:00Z" }),
      rec({ id: "V2", filename: "bracket.step", label: "Bracket L", created_at: "2026-07-03T00:00:00Z" }),
    ],
    changeRequests: [
      cr({ id: 5, status: "approved", asset_type: "rate_card", target_version_id: 13, created_at: "2026-06-30T00:00:00Z", decided_at: "2026-07-04T00:00:00Z" }),
      cr({ id: 6, status: "draft" }), // not an event → skipped
    ],
  });
  // 2 records + 1 approved event = 3 items (draft skipped)
  assert.equal(feed.length, 3);
  // newest first: approved (Jul 4) → verified Bracket (Jul 3) → verified shaft (Jul 1)
  assert.equal(feed[0].t, "approved Rate card v13 → published");
  assert.equal(feed[0].d, "Jul 4");
  assert.equal(feed[1].t, "engine verified Bracket L");
  assert.equal(feed[2].t, "engine verified shaft.stl");
});

test("activity is empty for an org with no activity", () => {
  assert.equal(buildActivity({ records: [], changeRequests: [] }).length, 0);
});

test("activity respects the limit", () => {
  const records = Array.from({ length: 10 }, (_, i) =>
    rec({ id: `V${i}`, filename: `p${i}.stl`, created_at: `2026-07-${String(i + 1).padStart(2, "0")}T00:00:00Z` })
  );
  assert.equal(buildActivity({ records, changeRequests: [] }, 6).length, 6);
});

test("assetLabel + shortDate helpers are honest/deterministic", () => {
  assert.equal(assetLabel("rate_card"), "Rate card");
  assert.equal(assetLabel("shop_profile"), "Shop profile");
  assert.equal(assetLabel("something_else"), "something else");
  assert.equal(shortDate("2026-07-04T10:00:00Z"), "Jul 4");
  assert.equal(shortDate(null), "");
  assert.equal(shortDate("not-a-date"), "");
});

test("day-zero setup follows achievable dependencies and labels enrichment optional", () => {
  const steps = buildDayZeroSetup({
    machineCount: 0,
    recordCount: 0,
    programCount: 0,
    realActualCount: 0,
  });

  assert.deepEqual(steps.map((step) => step.key), ["machines", "verify", "program", "truth"]);
  assert.equal(steps[0].state, "needed");
  assert.equal(steps[1].state, "needed");
  assert.equal(steps[2].state, "locked");
  assert.match(steps[2].meta, /after your first verified part/i);
  assert.equal(steps[3].state, "locked");
  assert.doesNotMatch(steps[3].title, /rates/i);
});

test("day-zero completion is derived from persisted records, programs, and actuals", () => {
  const steps = buildDayZeroSetup({
    machineCount: 2,
    recordCount: 3,
    programCount: 1,
    realActualCount: 8,
  });

  assert.deepEqual(steps.map((step) => step.state), ["done", "done", "done", "done"]);
  assert.equal(steps[0].meta, "2 machines declared");
  assert.equal(steps[1].meta, "3 records");
  assert.equal(steps[2].meta, "1 program declared");
  assert.equal(steps[3].meta, "8 actuals received");
});

test("post-verification program and ground-truth steps are available but optional", () => {
  const steps = buildDayZeroSetup({
    machineCount: 1,
    recordCount: 1,
    programCount: 0,
    realActualCount: 0,
  });

  assert.equal(steps[2].state, "optional");
  assert.match(steps[2].meta, /^optional/i);
  assert.equal(steps[3].state, "optional");
  assert.match(steps[3].meta, /^optional/i);
});
