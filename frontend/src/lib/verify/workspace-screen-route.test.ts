import assert from "node:assert/strict";
import test from "node:test";

import { workspaceScreenFromSearch } from "./workspace-screen-route.ts";

test("all ID-free Verify workspace screens have stable deep links", () => {
  for (const screen of [
    "home",
    "verify",
    "catalog",
    "records",
    "programs",
    "machines",
    "triage",
    "calibration",
    "compare",
  ] as const) {
    assert.equal(workspaceScreenFromSearch(`?screen=${screen}`), screen);
  }
});

test("workspace deep links reject ambiguous, detail, and malformed destinations", () => {
  assert.equal(workspaceScreenFromSearch(""), null);
  assert.equal(workspaceScreenFromSearch("?screen=part"), null);
  assert.equal(workspaceScreenFromSearch("?screen=program"), null);
  assert.equal(workspaceScreenFromSearch("?screen=records%2F.."), null);
  assert.equal(workspaceScreenFromSearch("?screen=records&screen=machines"), null);
  assert.equal(workspaceScreenFromSearch("?screen=Machines"), null);
});
