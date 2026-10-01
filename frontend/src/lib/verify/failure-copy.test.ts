import { test } from "node:test";
import assert from "node:assert/strict";

import { analysisFailureCopy } from "./failure-copy.ts";
import { apiRecoveryMessage } from "../api-recovery.ts";

test("exhausted trial allowance is not a temporary capacity or geometry failure", () => {
  const copy = analysisFailureCopy(apiRecoveryMessage({
    status: 429, resource: "verification",
    payload: { code: "org_validation_cap_exceeded", message: "100 validations used in total" },
  }));
  assert.equal(copy.kind, "quota");
  assert.match(copy.explanation, /100 validations used in total/);
  assert.doesNotMatch(copy.title + copy.action + copy.toast, /temporarily|retry shortly|re-export/i);
});

test("capacity failures never blame customer geometry", () => {
  const copy = analysisFailureCopy(
    "this organization has reached its concurrent-analysis limit of 3",
  );
  assert.equal(copy.kind, "capacity");
  assert.match(copy.title, /temporarily busy/i);
  assert.match(copy.action, /does not need to be re-exported/i);
  assert.doesNotMatch(copy.title + copy.explanation + copy.action, /tessellat/i);
  assert.equal(analysisFailureCopy(apiRecoveryMessage({
    status: 429, resource: "verification", retryAfter: "2",
  })).kind, "capacity");
});

test("unsupported, unreadable, and actual mesher failures get distinct recovery copy", () => {
  assert.equal(analysisFailureCopy("Unsupported file type; use .stl").kind, "unsupported");
  assert.equal(
    analysisFailureCopy(
      "File does not appear to be a valid STEP file (missing ISO-10303-21 header).",
    ).kind,
    "unreadable",
  );
  assert.equal(
    analysisFailureCopy(
      "Cannot ingest .sldprt (SolidWorks part): it is a proprietary/native CAD format that requires a licensed reader.",
    ).kind,
    "unsupported",
  );
  assert.equal(
    analysisFailureCopy("geometry contains an unsupported surface the mesher cannot triangulate").kind,
    "geometry",
  );
});

test("invalid STEP magic gets actionable format recovery without a tessellation diagnosis", () => {
  const copy = analysisFailureCopy(
    "File does not appear to be a valid STEP file (missing ISO-10303-21 header).",
  );
  assert.equal(copy.kind, "unreadable");
  assert.equal(copy.title, "We couldn’t read this file.");
  assert.match(copy.action, /STL, STEP, STP, IGES, or IGS/i);
  assert.doesNotMatch(copy.title + copy.explanation + copy.action, /tessellat/i);
});

test("supported STEP with corrupt exchange contents gets re-export guidance", () => {
  const copy = analysisFailureCopy(
    "Could not read STEP geometry (not a valid/supported STEP file).",
  );
  assert.equal(copy.kind, "unreadable");
  assert.equal(copy.title, "We couldn’t read this file.");
  assert.match(copy.explanation, /supported CAD format.*could not be parsed/i);
  assert.match(copy.action, /Re-export.*clean STL, STEP, STP, IGES, or IGS/i);
  assert.doesNotMatch(copy.title + copy.explanation + copy.action, /tessellat/i);
});

test("unknown failures do not invent a geometry diagnosis", () => {
  const copy = analysisFailureCopy("upstream request failed (503)");
  assert.equal(copy.kind, "unknown");
  assert.match(copy.title, /could not finish/i);
  assert.doesNotMatch(copy.title + copy.explanation, /geometry|tessellat/i);
});

test("truncated STL keeps the requested plain client refusal", () => {
  const copy = analysisFailureCopy("this STL looks truncated or corrupt - re-export it");
  assert.equal(copy.kind, "unreadable");
  assert.equal(copy.toast, "this STL looks truncated or corrupt - re-export it");
});

test("rolling quota copy preserves allowance timing and remains retryable", () => {
  const copy = analysisFailureCopy(apiRecoveryMessage({ status: 429, resource: "verification",
    payload: { code: "org_quota_exceeded", message: "Daily cap; rolling ~24h window" } }));
  assert.equal(copy.kind, "quota-window");
  assert.match(copy.title, /for now/);
  assert.match(copy.explanation, /rolling ~24h window/);
  assert.doesNotMatch(copy.title, /busy/);
});
