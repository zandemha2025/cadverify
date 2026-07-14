import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  OUTCOME_SCHEMA_VERSION,
  PUBLIC_NAV_TARGETS,
  REQUIRED_OUTCOME_DEFINITIONS,
  REQUIRED_OUTCOME_IDS,
  TEMPORARY_BUSY_COPY,
  VERIFY_SECTIONS,
  VIEWPORTS,
  expectedServedBuildId,
  horizontalOverflowResult,
  isExpectedRequestFailure,
  makeOutcomeRecord,
  terminalBlockersFromSnapshot,
  validateOutcomeMap,
} from "./full-mobile-browser.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const runnerPath = path.join(__dirname, "full-mobile-browser.mjs");
const source = await readFile(runnerPath, "utf8");

function method(name, nextName) {
  const start = source.indexOf(`  async ${name}(`);
  assert.ok(start >= 0, `${name} method is missing`);
  const asyncBoundary = nextName ? source.indexOf(`  async ${nextName}(`, start + 1) : -1;
  const syncBoundary = nextName ? source.indexOf(`  ${nextName}(`, start + 1) : -1;
  const boundaries = [asyncBoundary, syncBoundary].filter((index) => index > start);
  const end = boundaries.length > 0 ? Math.min(...boundaries) : nextName ? -1 : source.length;
  assert.ok(end > start, `${name} method boundary is missing`);
  return source.slice(start, end);
}

function ordered(text, needles) {
  let cursor = -1;
  for (const needle of needles) {
    const next = text.indexOf(needle, cursor + 1);
    assert.ok(next > cursor, `${needle} was missing or out of order`);
    cursor = next;
  }
}

function visualStep(definition, viewportKey, index = 0) {
  return {
    id: definition.id,
    stage: `${viewportKey}-oracle-${index}`,
    terminal: true,
    screenshot: `/tmp/${definition.id.toLowerCase()}-${viewportKey}-oracle-${index}.png`,
    capturedAt: "2026-07-14T12:00:00.000Z",
    url: `https://proofshape.example/oracle/${definition.id}`,
    requiredVisible: ["Terminal evidence"],
    forbiddenVisible: [...TEMPORARY_BUSY_COPY, "COMPUTING", "Loading"],
    capture: {
      text: "Terminal evidence",
      ariaBusyCount: 0,
      skeletonCount: 0,
      loadingIndicatorCount: 0,
    },
    viewportKey,
  };
}

function validOutcome(definition) {
  return makeOutcomeRecord({
    definition,
    persona: "human operator",
    preconditions: ["The expected production build is serving the browser."],
    actions: ["Used the visible browser target and inspected its terminal state."],
    observed: {
      url: `https://proofshape.example/oracle/${definition.id}`,
      visible: ["Terminal evidence"],
      persisted: { id: `${definition.id}-stable` },
      numeric: { status: 200 },
      authorization: { allowed: true },
      recovery: "The same durable state remained available after reopening.",
    },
    visualSteps: definition.requiredViewportKeys.map((key, index) => visualStep(definition, key, index)),
  });
}

test("the release matrix is exact, exhaustive, unique, and schema v2", () => {
  assert.equal(OUTCOME_SCHEMA_VERSION, 2);
  assert.deepEqual(
    VIEWPORTS.map(({ width, height }) => [width, height]),
    [[375, 812], [390, 844], [768, 1024]],
  );
  assert.equal(new Set(VIEWPORTS.map((item) => item.key)).size, 3);
  assert.equal(REQUIRED_OUTCOME_DEFINITIONS.length, 13);
  assert.equal(new Set(REQUIRED_OUTCOME_IDS).size, REQUIRED_OUTCOME_IDS.length);
  assert.deepEqual(REQUIRED_OUTCOME_IDS, REQUIRED_OUTCOME_DEFINITIONS.map((item) => item.id));
  assert.deepEqual(PUBLIC_NAV_TARGETS.map((item) => item.label), [
    "Method", "Platform", "Teams", "Security", "Developers", "Company",
  ]);
  assert.deepEqual(VERIFY_SECTIONS.map((item) => item.label), [
    "Home", "Verify", "Parts", "Records", "Programs", "Your machines", "Triage", "Calibration & truth",
  ]);
  for (const definition of REQUIRED_OUTCOME_DEFINITIONS) {
    assert.ok(definition.requiredViewportKeys.length > 0, `${definition.id} has no viewport oracle`);
    assert.equal(
      definition.requiredViewportKeys.every((key) => VIEWPORTS.some((viewport) => viewport.key === key)),
      true,
      `${definition.id} references an unsupported viewport`,
    );
  }
});

test("terminal oracle rejects every busy, loading, and temporary-failure state", () => {
  const clean = {
    text: "Saved and ready for an operator decision.",
    ariaBusyCount: 0,
    skeletonCount: 0,
    loadingIndicatorCount: 0,
  };
  assert.deepEqual(terminalBlockersFromSnapshot(clean), []);
  for (const text of TEMPORARY_BUSY_COPY) {
    assert.ok(
      terminalBlockersFromSnapshot({ ...clean, text }).length > 0,
      `temporary state was accepted: ${text}`,
    );
  }
  for (const field of ["ariaBusyCount", "skeletonCount", "loadingIndicatorCount"]) {
    assert.deepEqual(terminalBlockersFromSnapshot({ ...clean, [field]: 1 }), [`${field}=1`]);
  }
});

test("horizontal overflow oracle uses a one-pixel rendering tolerance and fails closed", () => {
  assert.equal(horizontalOverflowResult({ viewportWidth: 375, documentScrollWidth: 375, bodyScrollWidth: 375 }).pass, true);
  assert.equal(horizontalOverflowResult({ viewportWidth: 375, documentScrollWidth: 376, bodyScrollWidth: 375 }).pass, true);
  const overflow = horizontalOverflowResult({ viewportWidth: 375, documentScrollWidth: 377, bodyScrollWidth: 376 });
  assert.equal(overflow.pass, false);
  assert.equal(overflow.overflowPx, 2);
  assert.equal(horizontalOverflowResult({ viewportWidth: 0, documentScrollWidth: 0, bodyScrollWidth: 0 }).pass, false);
});

test("build identity oracle requires an exact explicit remote id and supports loopback git identity", () => {
  const identity = { gitHead: "a".repeat(40) };
  assert.deepEqual(
    expectedServedBuildId("https://staging.proofshape.example", identity, { E2E_BUILD_ID: "release-123" }),
    { buildId: "release-123", source: "E2E_BUILD_ID" },
  );
  assert.deepEqual(
    expectedServedBuildId("http://localhost:3000", identity, {}),
    { buildId: identity.gitHead, source: "local-git-head" },
  );
  assert.deepEqual(
    expectedServedBuildId("http://[::1]:3000", identity, {}),
    { buildId: identity.gitHead, source: "local-git-head" },
  );
  assert.throws(
    () => expectedServedBuildId("https://staging.proofshape.example", identity, {}),
    /requires E2E_BUILD_ID/,
  );
});

test("request-failure oracle exempts only same-origin aborted Next RSC prefetches", () => {
  const appUrl = "https://proofshape.example";
  const expected = {
    url: "https://proofshape.example/designs?_rsc=abc123",
    method: "GET",
    resourceType: "fetch",
    error: "net::ERR_ABORTED",
  };
  assert.equal(isExpectedRequestFailure(expected, appUrl), true);
  assert.equal(isExpectedRequestFailure({ ...expected, url: "https://other.example/designs?_rsc=abc123" }, appUrl), false);
  assert.equal(isExpectedRequestFailure({ ...expected, url: "https://proofshape.example/designs" }, appUrl), false);
  assert.equal(isExpectedRequestFailure({ ...expected, method: "POST" }, appUrl), false);
  assert.equal(isExpectedRequestFailure({ ...expected, resourceType: "document" }, appUrl), false);
  assert.equal(isExpectedRequestFailure({ ...expected, error: "net::ERR_CONNECTION_RESET" }, appUrl), false);
});

test("schema-v2 outcome map accepts complete evidence and has no skip representation", () => {
  const outcomes = Object.fromEntries(
    REQUIRED_OUTCOME_DEFINITIONS.map((definition) => [definition.id, validOutcome(definition)]),
  );
  const validation = validateOutcomeMap(outcomes);
  assert.equal(validation.total, REQUIRED_OUTCOME_IDS.length);
  assert.equal(validation.valid, validation.total, JSON.stringify(validation.problems));
  assert.equal(Object.values(outcomes).every((outcome) => outcome.schemaVersion === 2), true);
  assert.equal(Object.values(outcomes).every((outcome) => outcome.status === "PASS"), true);
  assert.equal(Object.values(outcomes).some((outcome) => /skip/i.test(outcome.status)), false);
});

test("outcome validation rejects HTTP errors, failed assertions, wrong viewports, FAIL, and missing records", () => {
  const definition = REQUIRED_OUTCOME_DEFINITIONS[1];
  const base = validOutcome(definition);
  const cases = [
    { label: "HTTP error", value: { ...base, unexpectedHttpErrors: [{ status: 500 }] }, field: "unexpectedHttpErrors" },
    { label: "wrong viewport", value: { ...base, viewportKeys: ["390x844"] }, field: "viewportKeys" },
    { label: "FAIL status", value: { ...base, status: "FAIL" }, field: "status" },
    {
      label: "failed assertion",
      value: { ...base, assertions: [...base.assertions, { name: "oracle", expected: true, actual: false, pass: false }] },
      field: "assertions",
    },
  ];
  for (const item of cases) {
    const validation = validateOutcomeMap({ [definition.id]: item.value }, [definition]);
    assert.equal(validation.valid, 0, `${item.label} unexpectedly passed`);
    assert.equal(validation.problems.some((problem) => problem.field.includes(item.field)), true, JSON.stringify(validation.problems));
  }
  const missing = validateOutcomeMap({}, [definition]);
  assert.equal(missing.valid, 0);
  assert.equal(missing.problems.some((problem) => problem.id === definition.id), true);
});

test("supported CAD fixture is tracked, non-empty, and byte-stable", async () => {
  const bytes = await readFile(path.join(repoRoot, "backend", "tests", "assets", "cube.step"));
  assert.ok(bytes.length > 128);
  assert.equal(
    createHash("sha256").update(bytes).digest("hex"),
    "76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a",
  );
  const body = method("runSupportedCad", "runDispositionPersistence");
  ordered(body, [
    'getByRole("button", { name: "Verify a part", exact: true })',
    'waitForVerificationPipeline(this.page',
    "input.setInputFiles(fixturePath)",
    'getByText("What it really takes"',
    "assertTruthfulTerminalCase",
    'captureStage(',
  ]);
  for (const endpoint of ["/api/proxy/validate/assembly", "/api/proxy/validate", "/api/proxy/validate/cost"]) {
    assert.ok(body.includes(endpoint), `CAD workflow omits ${endpoint}`);
  }
});

test("every journey is attempted in order and the CLI exposes no skip flag", () => {
  const body = method("runAllOutcomes", "ensureAllOutcomeRecords");
  ordered(body, REQUIRED_OUTCOME_IDS.map((id) => `byId["${id}"]`));
  for (const id of REQUIRED_OUTCOME_IDS) {
    assert.equal((body.match(new RegExp(`byId\\["${id}"\\]`, "g")) || []).length, 2, `${id} is not wired exactly once`);
  }
  assert.doesNotMatch(source, /\b(?:SKIP|SKIPPED)\b/);
  assert.match(source, /noSkippedOutcomes/);

  const help = spawnSync(process.execPath, [runnerPath, "--help"], { cwd: repoRoot, encoding: "utf8" });
  assert.equal(help.status, 0, help.stderr);
  assert.match(help.stdout, /\[--headed\]/);
  assert.doesNotMatch(help.stdout, /skip/i);

  const skipped = spawnSync(process.execPath, [runnerPath, "--skip-design"], { cwd: repoRoot, encoding: "utf8" });
  assert.notEqual(skipped.status, 0);
  assert.match(`${skipped.stdout}\n${skipped.stderr}`, /unknown argument: --skip-design/);
});

test("primary-target, overflow, terminal, screenshot, diagnostics, and build gates fail closed", () => {
  const target = method("assertPrimaryTarget", "clickPrimary");
  ordered(target, [
    'waitFor({ state: "visible"',
    "scrollIntoViewIfNeeded()",
    "boundingBox()",
    "box.x >= -1",
    "isDisabled()",
    'click({ trial: true',
    "target.focus()",
    "document.activeElement",
  ]);
  const capture = method("captureStage", "failureScreenshot");
  assert.match(capture, /waitForSettled/);
  assert.match(capture, /assertNoHorizontalOverflow/);
  assert.match(capture, /forbiddenVisible: TEMPORARY_BUSY_COPY/);
  assert.match(capture, /screenshotStat\.size > 0/);

  const watcher = source.slice(source.indexOf("  watchPage("), source.indexOf("  async init("));
  assert.match(watcher, /message\.type\(\) !== "error"/);
  assert.match(watcher, /page\.on\("pageerror"/);
  assert.match(watcher, /page\.on\("requestfailed"/);
  assert.match(watcher, /isExpectedRequestFailure/);
  assert.match(watcher, /response\.status\(\) >= 400/);

  const build = method("probeBuildIdentity", "setViewport");
  assert.match(build, /x-proofshape-build/);
  assert.match(build, /served && served !== "unknown"/);
  assert.match(build, /served === this\.expectedBuild\.buildId/);
});

test("disposition persists the exact decision through refresh, all viewports, records, and session recovery", () => {
  const disposition = method("runDispositionPersistence", "waitForDesignReady");
  ordered(disposition, [
    '"PUT", `/api/proxy/cost-decisions/${truth.savedDecisionId}/disposition`',
    "this.clickPrimary(disposition",
    'filter({ hasText: `✓ ${expectedDisposition.label} — recorded` })',
    "for (const viewport of VIEWPORTS)",
    "this.reload(`record refresh ${viewport.key}`)",
    "this.navigateVerifySection(VERIFY_SECTIONS[3])",
    '"GET", `/api/proxy/cost-decisions/${truth.savedDecisionId}`',
    "detail.id === truth.savedDecisionId",
    "detail.user_disposition === expectedDisposition.key",
    "this.dispositionEvidence =",
  ]);

  const recovery = method("runSessionRecovery", "runAllOutcomes");
  ordered(recovery, [
    '"POST", "/api/auth/logout"',
    'getByRole("menuitem", { name: "Sign out", exact: true })',
    'this.goto("/verify", "gated Verify after logout")',
    'getByLabel("Email")',
    'getByLabel("Password")',
    '"POST", "/api/auth/login"',
    "orgBody?.active_org_id === this.account.orgId",
    "detail.id === decisionId",
    "this.sessionRecoveryEvidence =",
  ]);
});

test("Design Studio proves preview-or-fallback, immutable handoff ids, and a non-busy terminal", () => {
  const body = method("runDesignStudio", "openMobileNavigationDestination");
  ordered(body, [
    'getByTestId("design-mutation-workspace")',
    'getByRole("button", { name: "Mounting plate", exact: true })',
    'getByLabel("Width")',
    'getByLabel("Depth")',
    'getByLabel("Thickness")',
    'getByRole("button", { name: /^Generate design$/ })',
    '"Interactive 3D is unavailable in this browser."',
    "preview.canvasVisible || preview.fallbackVisible",
    'getByRole("link", { name: /^Verify revision 1$/ })',
    'handoffUrl.searchParams.get("design")',
    'handoffUrl.searchParams.get("revision") === "1"',
    "waitForVerificationPipeline(this.page",
    "assertTruthfulTerminalCase",
    '"768x1024-verify-handoff-terminal"',
    "this.designEvidence =",
  ]);
  assert.match(body, /intentionally forbids[\s\S]*Verification is[\s\S]*running\./);
  assert.ok(TEMPORARY_BUSY_COPY.includes("Verification is running."));
});

test("remaining public, Verify, palette, ledger, settings, batch, and reconstruction-boundary surfaces have concrete browser oracles", () => {
  const publicBody = method("runPublicNavigation", "runSignupDayZero");
  assert.match(publicBody, /for \(const viewport of VIEWPORTS\)/);
  assert.match(publicBody, /for \(const target of PUBLIC_NAV_TARGETS\)/);

  const signup = method("runSignupDayZero", "navigateVerifySection");
  ordered(signup, [
    'getByLabel("Email")',
    'getByLabel("Password")',
    '"POST", "/api/auth/signup"',
    'getByText("DAY ZERO SETUP"',
    '"/api/proxy/orgs"',
    'activeOrg.org_role === "admin"',
  ]);

  const sections = method("runVerifySections", "runVerifyCommandPalette");
  assert.match(sections, /for \(const viewport of VIEWPORTS\)/);
  assert.match(sections, /for \(const section of VERIFY_SECTIONS\)/);
  assert.match(sections, /assertion\("Verify section viewport captures", 24, visualSteps\.length\)/);

  const palette = method("runVerifyCommandPalette", "runSupportedCad");
  ordered(palette, ["Jump to a surface", "Command palette search", 'fillPrimary(search, "triage"', "Go to Triage"]);

  const history = method("runHistory", "runNotifications");
  ordered(history, ["Recent analyses", 'getByRole("heading", { name: "History"', 'getByRole("combobox")']);
  const notifications = method("runNotifications", "openAccountDestination");
  ordered(notifications, ['name: "Notifications"', 'name: "Open Verify"', '"Source of truth"']);

  const settings = method("runSettings", "runBatchEntry");
  for (const target of ["Settings · Organization", "Send invite", "Admins only", "Settings · Security", "Set password", "Settings · Developer", "Create key"]) {
    assert.ok(settings.includes(target), `settings workflow omits ${target}`);
  }

  const batch = method("runBatchEntry", "runReconstructionEntry");
  ordered(batch, ["Batch run", 'accept=".zip"', "setInputFiles", 'name: "Start batch"']);
  assert.doesNotMatch(batch, /clickPrimary\(this\.page\.getByRole\("button", \{ name: "Start batch"/);

  const reconstruction = method("runReconstructionEntry", "runSessionRecovery");
  ordered(reconstruction, [
    '"GET", "/api/proxy/reconstruct/capability"',
    "capability?.available === false",
    "Image-to-3D is not enabled",
    "No image has been uploaded or sent to a third party.",
    'locator(\'input[type="file"]\')',
    "Verify CAD instead",
    'url.pathname === "/verify"',
    "Drop a part to begin the walk.",
  ]);
  assert.doesNotMatch(reconstruction, /setInputFiles|submitReconstruction|Reconstruct \(1 image\)/);
});
