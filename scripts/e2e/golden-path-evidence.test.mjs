import assert from "node:assert/strict";
import test from "node:test";
import {
  makeGoldenPathEvidence,
  validateGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";

function validEntry(id = "VER-04") {
  return makeGoldenPathEvidence({
    id,
    status: "PASS",
    persona: "Authenticated CAD engineer",
    preconditions: ["One unread notification exists in organization A."],
    actions: ["Open Notifications.", "Mark the row read.", "Reload the page."],
    observed: {
      url: "http://localhost:3000/notifications",
      visible: ["Notification row remains visible and is marked read."],
      persisted: { unreadBefore: 1, unreadAfterReload: 0 },
      numeric: "not-applicable",
      authorization: { organization: "A", otherOrganizationVisible: false },
      recovery: "Reload retained the read state.",
    },
    screenshot: "/tmp/VER-04.png",
    consoleErrors: [],
    requestFailures: [],
    assertions: [
      { name: "read state survives reload", expected: 0, actual: 0, pass: true },
    ],
  });
}

test("a complete browser outcome envelope validates", () => {
  const result = validateGoldenPathEvidence("VER-04", validEntry());
  assert.equal(result.valid, true);
  assert.deepEqual(result.failures, []);
});

test("a matching path name cannot pass without observed outcomes", () => {
  const result = validateGoldenPathEvidence("VER-04", {
    id: "VER-04",
    status: "PASS",
  });
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field === "observed.persisted"));
  assert.ok(result.failures.some((item) => item.field === "assertions"));
});

test("one failed assertion invalidates the path", () => {
  const entry = validEntry();
  entry.assertions[0].pass = false;
  const result = validateGoldenPathEvidence("VER-04", entry);
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field === "assertions.0.pass"));
});

test("the map reports exact missing fields per requirement", () => {
  const result = validateGoldenPathMap(["VER-04", "ROLE-04"], {
    "VER-04": validEntry("VER-04"),
  });
  assert.equal(result.total, 2);
  assert.equal(result.valid, 1);
  assert.ok(result.problems.some((item) => item.id === "ROLE-04" && item.field === "schemaVersion"));
});
