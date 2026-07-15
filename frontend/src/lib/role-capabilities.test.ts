import assert from "node:assert/strict";
import test from "node:test";

import { canMutateWorkspace } from "./role-capabilities.ts";

test("workspace mutations are visible only to recognized analyst-or-higher roles", () => {
  assert.equal(canMutateWorkspace("analyst"), true);
  assert.equal(canMutateWorkspace("admin"), true);
  assert.equal(canMutateWorkspace("superadmin"), true);
});

test("viewer, auditor-like, missing, and malformed roles fail closed", () => {
  for (const role of ["viewer", "auditor", "member", "", "Analyst", null, undefined]) {
    assert.equal(canMutateWorkspace(role), false, String(role));
  }
});
