import assert from "node:assert/strict";
import test from "node:test";
import {
  captureVisualStep,
  makeGoldenPathEvidence,
  REQUIRED_VISUAL_STAGE_FORBIDDEN_TEXT,
  REQUIRED_VISUAL_STAGE_TEXT,
  REQUIRED_VISUAL_STAGES,
  TERMINAL_FORBIDDEN_VISIBLE,
  validateGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";

function visualStep(id, stage = "outcome", overrides = {}) {
  const requiredVisible = overrides.requiredVisible ??
    REQUIRED_VISUAL_STAGE_TEXT[id]?.[stage] ??
    ["Expected state is visible"];
  return {
    id,
    stage,
    terminal: true,
    screenshot: `/tmp/${id}-${stage}.png`,
    capturedAt: "2026-07-14T00:00:00.000Z",
    url: "http://localhost:3000/verify",
    requiredVisible,
    forbiddenVisible: [
      ...TERMINAL_FORBIDDEN_VISIBLE,
      ...(REQUIRED_VISUAL_STAGE_FORBIDDEN_TEXT[id]?.[stage] ?? []),
    ],
    capture: {
      text: requiredVisible.join(" "),
      ariaBusyCount: 0,
      skeletonCount: 0,
      loadingIndicatorCount: 0,
    },
    ...overrides,
  };
}

function validEntry(id = "VER-04", overrides = {}) {
  const stages = REQUIRED_VISUAL_STAGES[id] ?? ["outcome"];
  const visualSteps = stages.map((stage) => visualStep(id, stage));
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
    screenshot: visualSteps.at(-1).screenshot,
    visualSteps,
    consoleErrors: [],
    requestFailures: [],
    assertions: [
      { name: "read state survives reload", expected: 0, actual: 0, pass: true },
    ],
    ...overrides,
  });
}

function legacyEntry(id = "VER-04") {
  const entry = validEntry(id);
  return makeGoldenPathEvidence({
    ...entry,
    screenshot: `/tmp/${id}.png`,
    visualSteps: undefined,
  });
}

test("a complete schema-v2 browser outcome validates", () => {
  const result = validateGoldenPathEvidence("VER-04", validEntry());
  assert.equal(result.valid, true);
  assert.deepEqual(result.failures, []);
});

test("legacy schema remains readable only for paths without a required v2 stage contract", () => {
  assert.equal(validateGoldenPathEvidence("VER-04", legacyEntry("VER-04")).valid, true);
  const required = validateGoldenPathEvidence("VER-05", legacyEntry("VER-05"));
  assert.equal(required.valid, false);
  assert.ok(required.failures.some((item) => item.field === "visualProof" && item.actual === "NOT_VISUALLY_PROVABLE"));
  assert.ok(required.failures.some((item) => item.field === "visualSteps"));
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

test("failure and recovery stage contracts cannot be collapsed into one screenshot", () => {
  const entry = validEntry("FAIL-03");
  entry.visualSteps = entry.visualSteps.filter((step) => step.stage !== "failure");
  const result = validateGoldenPathEvidence("FAIL-03", entry);
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field === "visualSteps.required.failure"));
});

test("a required settled stage cannot opt out of terminal blocker checks", () => {
  const entry = validEntry("VER-05");
  entry.visualSteps[0].terminal = false;
  entry.visualSteps[0].capture.text = "Expected state is visible COMPUTING";
  const result = validateGoldenPathEvidence("VER-05", entry);
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field === "visualSteps.required.terminal.terminal"));
});

test("a named stage cannot substitute generic text for its canonical visual oracle", () => {
  const entry = validEntry("FAIL-10");
  entry.visualSteps[0].requiredVisible = ["ProofShape"];
  entry.visualSteps[0].capture.text = "ProofShape";
  const result = validateGoldenPathEvidence("FAIL-10", entry);
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field.includes("visualSteps.required.failure.text.Could not load progress")));
});

test("recovery cannot omit its path-specific stale-state prohibition", () => {
  const entry = validEntry("FAIL-08");
  const recovery = entry.visualSteps.find((step) => step.stage === "recovery");
  recovery.forbiddenVisible = [...TERMINAL_FORBIDDEN_VISIBLE];
  const result = validateGoldenPathEvidence("FAIL-08", entry);
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field.includes("visualSteps.required.recovery.forbidden.Cost history")));
});

test("required text must exist in the DOM snapshot captured with the PNG", () => {
  const entry = validEntry("AUTH-03");
  entry.visualSteps[0].requiredVisible = ["Invalid email or password."];
  entry.visualSteps[0].capture.text = "Log in to ProofShape";
  const result = validateGoldenPathEvidence("AUTH-03", entry);
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field.endsWith("requiredVisible.0.present")));
});

test("terminal captures reject COMPUTING, Loading, skeletons, and aria-busy", () => {
  const blockers = [
    ["text", "Expected state is visible COMPUTING"],
    ["text", "Expected state is visible Loading"],
    ["skeletonCount", 1],
    ["ariaBusyCount", 1],
    ["loadingIndicatorCount", 1],
  ];
  for (const [field, value] of blockers) {
    const entry = validEntry("VER-05");
    if (field === "text") entry.visualSteps[0].capture.text = value;
    else entry.visualSteps[0].capture[field] = value;
    const result = validateGoldenPathEvidence("VER-05", entry);
    assert.equal(result.valid, false, `${field} should block terminal proof`);
    assert.ok(result.failures.some((item) => item.field.includes("terminal")), `${field} had no terminal failure`);
  }
});

test("visual proof cannot use a screenshot associated with another path ID", () => {
  const entry = validEntry("AUTH-03");
  entry.visualSteps[0].screenshot = "/tmp/AUTH-05-invalid-credentials.png";
  entry.screenshot = entry.visualSteps[0].screenshot;
  const result = validateGoldenPathEvidence("AUTH-03", entry);
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field === "visualSteps.0.screenshot.id"));
});

test("not-visually-provable is preserved truthfully and cannot pass the gate", () => {
  const entry = validEntry("VER-05", { visualProof: "NOT_VISUALLY_PROVABLE" });
  const result = validateGoldenPathEvidence("VER-05", entry);
  assert.equal(result.valid, false);
  assert.ok(result.failures.some((item) => item.field === "visualProof"));
});

test("the capture helper binds terminal DOM facts and screenshot to one step", async () => {
  const screenshots = [];
  let evaluateCalls = 0;
  const page = {
    async evaluate() {
      evaluateCalls += 1;
      if (evaluateCalls === 1) return undefined;
      return {
        text: "Invalid email or password.",
        ariaBusyCount: 0,
        skeletonCount: 0,
        loadingIndicatorCount: 0,
      };
    },
    async screenshot(options) {
      screenshots.push(options);
    },
    url() {
      return "http://localhost:3000/login";
    },
  };
  const step = await captureVisualStep(page, {
    id: "AUTH-03",
    stage: "invalid-credentials",
    screenshot: "/tmp/AUTH-03-invalid-credentials.png",
    terminal: true,
    requiredVisible: ["Invalid email or password."],
  });
  assert.equal(evaluateCalls, 2);
  assert.equal(screenshots.length, 1);
  assert.equal(step.capture.text, "Invalid email or password.");
  assert.deepEqual(step.forbiddenVisible, [...TERMINAL_FORBIDDEN_VISIBLE]);
  assert.equal(step.screenshot, screenshots[0].path);
});

test("the map reports exact missing fields per requirement", () => {
  const result = validateGoldenPathMap(["VER-04", "ROLE-04"], {
    "VER-04": validEntry("VER-04"),
  });
  assert.equal(result.total, 2);
  assert.equal(result.valid, 1);
  assert.ok(result.problems.some((item) => item.id === "ROLE-04" && item.field === "schemaVersion"));
});
