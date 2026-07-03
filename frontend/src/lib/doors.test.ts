import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DOORS,
  DOOR_STORAGE_KEY,
  parseDoor,
  doorById,
  roleToDoor,
  resolveDoor,
} from "./doors.ts";

test("DOORS: exactly the three co-equal doors, each with a first verb", () => {
  assert.deepEqual(
    DOORS.map((d) => d.id),
    ["part", "cost", "portfolio"]
  );
  assert.deepEqual(
    DOORS.map((d) => d.verb),
    ["DROP", "OVERRIDE", "TRIAGE"]
  );
  // every door names its persona and its hero object
  for (const d of DOORS) {
    assert.ok(d.persona.length > 0, `${d.id} has a persona`);
    assert.ok(d.object.length > 0, `${d.id} has an object`);
    assert.ok(d.blurb.length > 0, `${d.id} has a blurb`);
  }
});

test("DOORS: only the part door is live; cost/portfolio carry an honest phase", () => {
  assert.equal(doorById("part").phase, undefined);
  assert.equal(typeof doorById("cost").phase, "string");
  assert.equal(typeof doorById("portfolio").phase, "string");
});

test("DOOR_STORAGE_KEY is the persisted cv_door key", () => {
  assert.equal(DOOR_STORAGE_KEY, "cv_door");
});

test("parseDoor accepts only the three known ids", () => {
  assert.equal(parseDoor("part"), "part");
  assert.equal(parseDoor("cost"), "cost");
  assert.equal(parseDoor("portfolio"), "portfolio");
  assert.equal(parseDoor("PART"), null);
  assert.equal(parseDoor("catalog"), null);
  assert.equal(parseDoor(""), null);
  assert.equal(parseDoor(null), null);
  assert.equal(parseDoor(undefined), null);
});

test("doorById returns the door, and falls back to part for a bad id", () => {
  assert.equal(doorById("cost").id, "cost");
  // @ts-expect-error — deliberately passing an out-of-type id to test the fallback
  assert.equal(doorById("nope").id, "part");
});

test("roleToDoor maps recognised persona tokens (case/space-insensitive)", () => {
  assert.equal(roleToDoor("design"), "part");
  assert.equal(roleToDoor("MFG"), "part");
  assert.equal(roleToDoor("  Manufacturing  "), "part");
  assert.equal(roleToDoor("cost"), "cost");
  assert.equal(roleToDoor("sourcing"), "cost");
  assert.equal(roleToDoor("buyer"), "cost");
  assert.equal(roleToDoor("portfolio"), "portfolio");
  assert.equal(roleToDoor("mro"), "portfolio");
});

test("roleToDoor does NOT resolve RBAC account roles or unknowns → null", () => {
  // account roles are not personas; they must fall through to the chooser
  assert.equal(roleToDoor("analyst"), null);
  assert.equal(roleToDoor("admin"), null);
  assert.equal(roleToDoor("viewer"), null);
  assert.equal(roleToDoor("superadmin"), null);
  assert.equal(roleToDoor(""), null);
  assert.equal(roleToDoor(null), null);
  assert.equal(roleToDoor(undefined), null);
});

test("resolveDoor: a persisted choice always wins over role", () => {
  assert.equal(resolveDoor({ persisted: "cost", role: "design" }), "cost");
  assert.equal(resolveDoor({ persisted: "portfolio", role: "mfg" }), "portfolio");
});

test("resolveDoor: falls back to a recognised role when nothing persisted", () => {
  assert.equal(resolveDoor({ persisted: null, role: "design" }), "part");
  assert.equal(resolveDoor({ persisted: "garbage", role: "sourcing" }), "cost");
});

test("resolveDoor: unknown persisted + unknown role → null (first-run chooser)", () => {
  assert.equal(resolveDoor({ persisted: null, role: "analyst" }), null);
  assert.equal(resolveDoor({ persisted: undefined, role: null }), null);
  assert.equal(resolveDoor({}), null);
});
