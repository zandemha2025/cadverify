import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  REQUIRED_IDS,
  assertSafeFixtureTarget,
  evaluateRunOracle,
  isExpectedNextRscPrefetchAbort,
  isExpectedOrganizationServerActionAbort,
  reconcileHttpOutcomes,
  redactUrl,
} from "./role-notification-browser.mjs";

const source = await readFile(
  new URL("./role-notification-browser.mjs", import.meta.url),
  "utf8",
);

function method(name, nextName) {
  const start = source.indexOf(`async ${name}(`);
  assert.ok(start >= 0, `${name} method is missing`);
  const end = nextName ? source.indexOf(`async ${nextName}(`, start + 1) : source.length;
  assert.ok(end > start, `${name} method boundary is missing`);
  return source.slice(start, end);
}

function ordered(text, needles) {
  let cursor = -1;
  for (const needle of needles) {
    const index = text.indexOf(needle, cursor + 1);
    assert.ok(index > cursor, `${needle} is missing or out of order`);
    cursor = index;
  }
}

function goldenPath(id) {
  return {
    schemaVersion: 2,
    id,
    mode: "browser",
    status: "PASS",
    persona: `Persona ${id}`,
    preconditions: ["real fixture"],
    actions: ["perform exact action"],
    observed: {
      url: "http://localhost:3000/example",
      visible: ["visible outcome"],
      persisted: { ok: true },
      numeric: { status: 200 },
      authorization: { allowed: true },
      recovery: "state survived refresh",
    },
    screenshot: `/tmp/${id}-outcome.png`,
    visualProof: "PROVEN",
    visualSteps: [{ id, stage: "outcome", screenshot: `/tmp/${id}-outcome.png` }],
    consoleErrors: [],
    requestFailures: [],
    assertions: [{ name: "truth", expected: true, actual: true, pass: true }],
  };
}

function passingOracleInput() {
  return {
    requiredIds: REQUIRED_IDS,
    goldenPaths: Object.fromEntries(REQUIRED_IDS.map((id) => [id, goldenPath(id)])),
    validation: { valid: REQUIRED_IDS.length, total: REQUIRED_IDS.length },
    diagnostics: {
      unexpectedConsoleErrors: [],
      unexpectedRequestFailures: [],
      unexpectedHttpErrors: [],
      missingExpectedHttpErrors: [],
    },
    buildBinding: { sameGitHead: true, sameBuildId: true },
    blockers: [],
    defects: [],
    steps: REQUIRED_IDS.map((id) => ({ id, status: "PASS" })),
  };
}

test("fixture provisioning defaults fail closed outside loopback", () => {
  assert.deepEqual(
    assertSafeFixtureTarget({
      appUrl: "http://localhost:3000",
      databaseUrl: "postgresql://user:pass@127.0.0.1:5432/test",
    }),
    { appHost: "localhost", databaseHost: "127.0.0.1", explicitRemoteOverride: false },
  );
  assert.throws(
    () => assertSafeFixtureTarget({
      appUrl: "https://app.example.com",
      databaseUrl: "postgresql://user:pass@db.example.com:5432/prod",
    }),
    /BLOCKER unsafe fixture target/,
  );
  assert.equal(
    assertSafeFixtureTarget({
      appUrl: "https://disposable.example.com",
      databaseUrl: "postgresql://user:pass@disposable-db.example.com:5432/qa",
      allowRemote: true,
    }).explicitRemoteOverride,
    true,
  );
});

test("URL evidence drops query strings and fragments", () => {
  assert.equal(
    redactUrl("https://app.example.com/orgs/accept?token=one-time-secret#fragment"),
    "https://app.example.com/orgs/accept",
  );
  assert.equal(redactUrl("/api/proxy/items/1?secret=yes"), "/api/proxy/items/1");
});

test("negative HTTP accounting is an exact multiset, not a status allowlist", () => {
  const expected = [
    { pathId: "ROLE-02", persona: "member", channel: "browser", method: "POST", path: "/api/proxy/rate-library/7/publish", status: 403 },
    { pathId: "ROLE-04", persona: "owner-a", channel: "browser", method: "GET", path: "/api/proxy/cost-decisions/B", status: 404 },
  ];
  const observed = [
    { ...expected[1], path: "http://localhost:3000/api/proxy/cost-decisions/B?prefetch=0" },
    expected[0],
  ];
  assert.deepEqual(reconcileHttpOutcomes(observed, expected), {
    matched: [
      { pathId: "ROLE-04", persona: "owner-a", channel: "browser", method: "GET", path: "/api/proxy/cost-decisions/B", status: 404 },
      { pathId: "ROLE-02", persona: "member", channel: "browser", method: "POST", path: "/api/proxy/rate-library/7/publish", status: 403 },
    ],
    unexpected: [],
    missing: [],
  });

  const wrongPath = reconcileHttpOutcomes(
    [{ ...expected[0], path: "/api/proxy/material-library/7/publish" }],
    [expected[0]],
  );
  assert.equal(wrongPath.unexpected.length, 1);
  assert.equal(wrongPath.missing.length, 1);

  const duplicate = reconcileHttpOutcomes([expected[0], expected[0]], [expected[0]]);
  assert.equal(duplicate.matched.length, 1);
  assert.equal(duplicate.unexpected.length, 1);
});

test("request-failure classifier accepts only exact Next navigation cancellations", () => {
  const rsc = {
    url: "http://localhost:3000/designs?_rsc=abc",
    method: "GET",
    resourceType: "fetch",
    error: "net::ERR_ABORTED",
  };
  assert.equal(isExpectedNextRscPrefetchAbort(rsc, "http://localhost:3000"), true);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...rsc, url: "https://foreign.example/designs?_rsc=abc" }, "http://localhost:3000"), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...rsc, method: "POST" }, "http://localhost:3000"), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...rsc, url: "http://localhost:3000/designs" }, "http://localhost:3000"), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...rsc, error: "net::ERR_CONNECTION_RESET" }, "http://localhost:3000"), false);

  const serverAction = {
    url: "http://localhost:3000/settings/organization",
    method: "POST",
    resourceType: "fetch",
    error: "net::ERR_ABORTED",
    hasNextAction: true,
  };
  assert.equal(isExpectedOrganizationServerActionAbort(serverAction, "http://localhost:3000"), true);
  assert.equal(isExpectedOrganizationServerActionAbort({ ...serverAction, hasNextAction: false }, "http://localhost:3000"), false);
  assert.equal(isExpectedOrganizationServerActionAbort({ ...serverAction, url: "http://localhost:3000/settings/security" }, "http://localhost:3000"), false);
});

test("release oracle requires all five schema-v2 paths, visuals, no skips, clean diagnostics, and stable build binding", () => {
  const passing = passingOracleInput();
  assert.deepEqual(evaluateRunOracle(passing), { pass: true, failures: [] });

  const schemaOne = structuredClone(passing);
  schemaOne.goldenPaths["VER-04"].schemaVersion = 1;
  assert.ok(evaluateRunOracle(schemaOne).failures.some((item) => item.field === "VER-04.schemaVersion"));

  const missing = structuredClone(passing);
  delete missing.goldenPaths["ROLE-04"];
  assert.equal(evaluateRunOracle(missing).pass, false);

  const skipped = structuredClone(passing);
  skipped.steps[2].status = "SKIP";
  assert.ok(evaluateRunOracle(skipped).failures.some((item) => item.field === "steps.2.status"));

  const unexpectedHttp = structuredClone(passing);
  unexpectedHttp.diagnostics.unexpectedHttpErrors.push({ status: 500 });
  assert.equal(evaluateRunOracle(unexpectedHttp).pass, false);

  const missingExpected = structuredClone(passing);
  missingExpected.diagnostics.missingExpectedHttpErrors.push({ status: 404 });
  assert.equal(evaluateRunOracle(missingExpected).pass, false);

  const changedBuild = structuredClone(passing);
  changedBuild.buildBinding.sameGitHead = false;
  assert.equal(evaluateRunOracle(changedBuild).pass, false);

  const blocked = structuredClone(passing);
  blocked.blockers.push({ message: "database unavailable" });
  assert.equal(evaluateRunOracle(blocked).pass, false);
});

test("runner is import-safe real Playwright orchestration with no mocked network branch", () => {
  assert.match(source, /createRequire\(new URL\("\.\.\/\.\.\/frontend\/package\.json"/);
  assert.match(source, /require\("playwright-core"\)/);
  assert.match(source, /chromium\.launch\(\{ \.\.\.launchOptions, channel: "chrome" \}\)/);
  assert.match(source, /const invokedAsScript = process\.argv\[1\]/);
  assert.match(source, /assertSafeFixtureTarget\(\{/);
  assert.match(source, /ROLE_E2E_ALLOW_REMOTE_SEED/);
  assert.match(source, /"frontend login surface"/);
  assert.match(source, /"backend OpenAPI surface"/);
  assert.match(source, /BLOCKER service preflight failed before fixture provisioning/);
  assert.match(source, /missing required live operations/);
  assert.doesNotMatch(source, /\.route\s*\(/);
  assert.doesNotMatch(source, /\.fulfill\s*\(/);
  assert.doesNotMatch(source, /status:\s*"SKIP"/);
  assert.match(source, /skips: \[\]/);
});

test("fixture logins wait for hydration and prove controlled values before submit", () => {
  const body = method("login", "api");
  ordered(body, [
    'getByRole("button", { name: /^Log in$/i })',
    'button[type="submit"]',
    "!button.disabled",
    "email.fill(person.email)",
    "password.fill(this.password)",
    "email.inputValue() === person.email",
    "password.inputValue() === this.password",
    "waitForResponse",
    "submit.click()",
  ]);
});

test("cost fixtures upload through the authenticated browser surface", () => {
  const multipart = method("browserMultipart", "browserActionResponse");
  assert.match(multipart, /actor\.page\.evaluate/);
  assert.match(multipart, /new FormData\(\)/);
  assert.match(multipart, /new File\(/);
  assert.match(multipart, /await fetch\(target/);
  assert.doesNotMatch(multipart, /context\.request/);

  const create = method("createCost", "createDrafts");
  assert.match(create, /this\.browserMultipart\(/);
  assert.doesNotMatch(create, /this\.api\(/);
});

test("VER-04 anchors unread, read, and dismiss persistence to UI actions and full refreshes", () => {
  const body = method("runVer04", "runRole01");
  ordered(body, [
    "initial row is visibly unread",
    "unread state survives full refresh",
    "unread-after-refresh",
    "/read`",
    "read timestamp survives full refresh",
    "read-after-refresh",
    "/dismiss`",
    "dismiss timestamp survives full refresh",
    "dismissed-after-refresh",
  ]);
  assert.match(body, /data-read-at/);
  assert.match(body, /data-dismissed-at/);
  assert.match(body, /dismissed API persists exact timestamp/);
  assert.match(body, /organization A inbox excludes organization B title/);
});

test("ROLE-01 anchors readable exports, absent mutation controls, exact denials, and unchanged persistence", () => {
  const body = method("runRole01", "runRole02");
  assert.match(body, /cost-decision-read-only/);
  assert.match(body, /mutationControlCount/);
  assert.match(body, /waitForEvent\("download"/);
  assert.match(body, /visible JSON export HTTP status/);
  assert.match(body, /viewer approval denial[\s\S]*expectedStatus: 403/);
  assert.match(body, /viewer invitation denial code/);
  assert.match(body, /denied approval leaves complete decision unchanged/);
  assert.match(body, /Admins only/);
});

test("ROLE-02 probes all three governed publish endpoints from the analyst/member browser", () => {
  const body = method("runRole02", "createInviteThroughUi");
  assert.match(source, /key: "rate", path: "rate-library"/);
  assert.match(source, /key: "material", path: "material-library"/);
  assert.match(source, /key: "shop", path: "shop-library"/);
  assert.match(body, /for \(const library of LIBRARIES\)/);
  assert.match(body, /\/publish`/);
  assert.match(body, /expectedStatus: 403/);
  assert.match(body, /insufficient_org_role/);
  assert.match(body, /denied publish leaves exact draft unchanged/);
});

test("ROLE-03 uses invitation, acceptance, revocation, and removal UI before persistence reads", () => {
  const body = method("runRole03", "opaquePair");
  ordered(body, [
    "admin creates member invitation",
    "created invitation persisted pending",
    "invited account accepts exact token",
    "accepted member persisted exactly once",
    "accepted-member-persisted",
    "admin creates revocable invitation",
    "Revoke invite",
    "revoked invitation persisted",
    "Remove member",
    "removed member absent from durable admin collection",
    "removed member has no organizations",
    "removed-member-revoked-invite",
  ]);
  assert.match(body, /\/api\/proxy\/orgs\/invites\/accept/);
  assert.match(body, /\/api\/proxy\/orgs\/members/);
  assert.match(body, /candidateOrgs\.body\.active_org_id, null/);
});

test("ROLE-04 checks read, mutate, and download opacity in both tenant directions", () => {
  const body = method("runRole04", "runPath");
  assert.match(body, /own: "A", foreign: "B"/);
  assert.match(body, /own: "B", foreign: "A"/);
  assert.match(body, /cost read/);
  assert.match(body, /cost approve/);
  assert.match(body, /cost PDF/);
  assert.match(body, /notification read/);
  assert.match(body, /notification dismiss/);
  assert.match(body, /for \(const library of LIBRARIES\)/);
  assert.match(body, /owning cost unchanged/);
  assert.match(body, /owning \$\{library\.key\} unchanged/);
  assert.match(method("opaquePair", "runRole04"), /known\/unknown response body/);
  assert.match(body, /foreign-identifier-not-found/);
});

test("schema-v2 evidence, diagnostics, build identity, and no-skip oracle are live release anchors", () => {
  assert.match(source, /captureVisualStep\(actor\.page/);
  assert.match(source, /makeGoldenPathEvidence\(\{/);
  assert.match(source, /validateGoldenPathMap\(REQUIRED_IDS, goldenPaths\)/);
  assert.match(source, /captureBuildIdentity\(repoRoot\)/);
  assert.match(source, /reconcileHttpOutcomes\(this\.observedHttpErrors, this\.expectedHttpErrors\)/);
  assert.match(source, /releaseEvidence: \{\s*schemaVersion: 2,/);
  assert.match(source, /evaluateRunOracle\(\{/);
  assert.match(source, /unexpectedConsoleErrors/);
  assert.match(source, /unexpectedRequestFailures/);
  assert.match(source, /unexpectedHttpErrors/);
  assert.match(source, /missingExpectedHttpErrors/);
});

test("main executes every required live journey exactly once in declared order", () => {
  ordered(source, [
    "await runner.init();",
    "await runner.preflight();",
    "await runner.provisionFixtures();",
    "await runner.setupLiveResources();",
  ]);
  let cursor = -1;
  for (const id of REQUIRED_IDS) {
    const needle = `await runner.runPath("${id}"`;
    const index = source.indexOf(needle, cursor + 1);
    assert.ok(index > cursor, `${id} live orchestration call is missing or out of order`);
    assert.equal(source.indexOf(needle, index + 1), -1, `${id} is orchestrated more than once`);
    cursor = index;
  }
});
