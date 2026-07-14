import { execFile } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import {
  captureVisualStep,
  makeGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const backendRoot = path.join(repoRoot, "backend");

export const REQUIRED_IDS = Object.freeze([
  "VER-04",
  "ROLE-01",
  "ROLE-02",
  "ROLE-03",
  "ROLE-04",
]);

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const LIBRARIES = Object.freeze([
  { key: "rate", path: "rate-library", create: (tag) => ({ name: `QA rate ${tag}`, change_note: "ROLE-02 publication denial fixture" }) },
  { key: "material", path: "material-library", create: (tag) => ({ name: `QA material ${tag}`, change_note: "ROLE-02 publication denial fixture" }) },
  { key: "shop", path: "shop-library", create: (tag) => ({ slug: `qa-shop-${tag}`.slice(0, 80), name: `QA shop ${tag}`, change_note: "ROLE-02 publication denial fixture" }) },
]);

const PATH_META = Object.freeze({
  "VER-04": Object.freeze({
    persona: "organization viewer managing a durable workflow inbox",
    preconditions: Object.freeze([
      "A real viewer session belongs to organization A.",
      "Organizations A and B contain distinct durable notification rows with unique private markers.",
    ]),
    actions: Object.freeze([
      "Open Notifications and refresh the exact unread row.",
      "Open the row through its visible UI control and retain the exact read response timestamp.",
      "Reopen and refresh Notifications, then dismiss the row through its visible UI control.",
      "Refresh again and compare the active/dismissed API collections with the rendered timestamp attributes.",
    ]),
  }),
  "ROLE-01": Object.freeze({
    persona: "read-only organization viewer reviewing same-organization evidence",
    preconditions: Object.freeze([
      "Organization A owns a real persisted cost decision created from the tracked STEP fixture.",
      "The viewer has platform role viewer and organization role viewer in A.",
    ]),
    actions: Object.freeze([
      "Open the same-organization decision through its real detail page.",
      "Download its JSON evidence through the visible export control.",
      "Inspect the read-only governance state and absence of every mutation control.",
      "Attempt approval and organization invitation mutations from the viewer browser, then re-read the unchanged decision.",
    ]),
  }),
  "ROLE-02": Object.freeze({
    persona: "platform analyst who is only an organization member",
    preconditions: Object.freeze([
      "The analyst/member belongs to A but is not an organization admin.",
      "An A admin has created one real draft in each governed rate, material, and shop library.",
    ]),
    actions: Object.freeze([
      "Open Organization settings and inspect the honest member-only admin gate.",
      "Read each governed draft from the member browser.",
      "Attempt to publish each draft from an actual browser fetch and require exact organization-role denial.",
      "Re-read every draft and prove no denied publication changed its persisted state.",
    ]),
  }),
  "ROLE-03": Object.freeze({
    persona: "organization admin managing invitation and membership lifecycle",
    preconditions: Object.freeze([
      "Organization A has one authenticated admin and two existing accounts with no memberships.",
      "Local deterministic fixture provisioning is explicitly constrained to loopback application and database targets.",
    ]),
    actions: Object.freeze([
      "Create a member invitation through Organization settings and redeem it in the exact invited account's browser.",
      "Refresh the admin member table and API collection to prove the accepted membership.",
      "Create and revoke a second invitation through the visible confirmation dialog.",
      "Remove the accepted member through the visible confirmation dialog and prove both sessions observe durable removal.",
    ]),
  }),
  "ROLE-04": Object.freeze({
    persona: "administrators in two unrelated organizations substituting known foreign identifiers",
    preconditions: Object.freeze([
      "A and B each own a cost decision, notification, and governed-library drafts with unique markers.",
      "Both administrators are authorized for the same operations inside their own organization.",
    ]),
    actions: Object.freeze([
      "Open a known foreign cost URL in the real viewer UI.",
      "Probe cost read, approval mutation, and PDF download in both tenant directions and compare known foreign IDs with unknown IDs.",
      "Probe notification read/dismiss and governed-library read/publish in both tenant directions.",
      "Re-read all owning-organization resources and prove every foreign operation left them unchanged.",
    ]),
  }),
});

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function evidenceValue(value) {
  if (value === null) return "<null>";
  if (value === "") return "<empty-string>";
  if (value === undefined) return "<undefined>";
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) {
    return { bytes: value.length, sha256: sha256(value) };
  }
  return value;
}

function cleanText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function sameValue(a, b) {
  return stableJson(a) === stableJson(b);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function errorCode(body) {
  return body?.code ?? body?.detail?.code ?? null;
}

function isoMilliseconds(value) {
  const milliseconds = Date.parse(value);
  invariant(Number.isFinite(milliseconds), `invalid ISO timestamp: ${value}`);
  return milliseconds;
}

function ghostUlid() {
  return "0".repeat(26);
}

function appPath(raw, appUrl) {
  const url = new URL(raw, `${appUrl}/`);
  return `${url.pathname}${url.search}${url.hash}`;
}

export function redactUrl(raw) {
  try {
    const url = new URL(raw, "http://local.invalid");
    const origin = url.origin === "http://local.invalid" ? "" : url.origin;
    return `${origin}${url.pathname}`;
  } catch {
    return String(raw).split(/[?#]/, 1)[0];
  }
}

function httpPath(raw) {
  try {
    return new URL(raw, "http://local.invalid").pathname;
  } catch {
    return String(raw).split(/[?#]/, 1)[0];
  }
}

function canonicalHttpReceipt(entry) {
  return {
    pathId: entry.pathId || "RUNNER",
    persona: entry.persona || "unknown",
    channel: entry.channel || "browser",
    method: String(entry.method || "GET").toUpperCase(),
    path: httpPath(entry.path || entry.url || ""),
    status: Number(entry.status),
  };
}

/**
 * Reconcile intentional negative HTTP receipts as a multiset. A blanket
 * "403/404 is expected" filter can hide a broken endpoint, so persona, channel,
 * method, path, status, and path ID must all match exactly and only once.
 */
export function reconcileHttpOutcomes(observedEntries, expectedEntries) {
  const observed = observedEntries.map(canonicalHttpReceipt);
  const expected = expectedEntries.map(canonicalHttpReceipt);
  const consumed = new Set();
  const matched = [];
  const unexpected = [];

  for (const actual of observed) {
    const index = expected.findIndex((candidate, candidateIndex) =>
      !consumed.has(candidateIndex) && sameValue(candidate, actual));
    if (index === -1) unexpected.push(actual);
    else {
      consumed.add(index);
      matched.push(actual);
    }
  }

  return {
    matched,
    unexpected,
    missing: expected.filter((_, index) => !consumed.has(index)),
  };
}

export function isExpectedNextRscPrefetchAbort(entry, appUrl) {
  try {
    const expectedOrigin = new URL(appUrl).origin;
    const url = new URL(entry.url);
    return entry.error === "net::ERR_ABORTED" &&
      entry.method === "GET" &&
      entry.resourceType === "fetch" &&
      url.origin === expectedOrigin &&
      url.searchParams.has("_rsc");
  } catch {
    return false;
  }
}

export function isExpectedOrganizationServerActionAbort(entry, appUrl) {
  try {
    const expectedOrigin = new URL(appUrl).origin;
    const url = new URL(entry.url);
    return entry.error === "net::ERR_ABORTED" &&
      entry.method === "POST" &&
      entry.resourceType === "fetch" &&
      entry.hasNextAction === true &&
      url.origin === expectedOrigin &&
      url.pathname === "/settings/organization";
  } catch {
    return false;
  }
}

function reconcileConsoleErrors(consoleErrors, matchedBrowserHttp) {
  const expected = [];
  const unexpected = [];
  for (const entry of consoleErrors) {
    const match = entry.text.match(/^Failed to load resource: the server responded with a status of (\d{3})(?:\s|$)/i);
    const status = match ? Number(match[1]) : null;
    const locationPath = entry.locationUrl ? httpPath(entry.locationUrl) : "";
    const receipt = status === null ? null : matchedBrowserHttp.find((candidate) =>
      candidate.channel === "browser" &&
      candidate.persona === entry.persona &&
      candidate.status === status &&
      locationPath &&
      candidate.path === locationPath);
    if (receipt) expected.push({ ...entry, matchedHttp: receipt });
    else unexpected.push(entry);
  }
  return { expected, unexpected };
}

export function assertSafeFixtureTarget({ appUrl, databaseUrl, allowRemote = false }) {
  const app = new URL(appUrl);
  const database = new URL(databaseUrl);
  const appLocal = LOCAL_HOSTS.has(app.hostname);
  const databaseLocal = LOCAL_HOSTS.has(database.hostname);
  if (!allowRemote && (!appLocal || !databaseLocal)) {
    throw new Error(
      `BLOCKER unsafe fixture target: APP_URL host=${app.hostname} DATABASE_URL host=${database.hostname}; ` +
      "this runner seeds destructive test-only rows only when both targets are loopback. " +
      "Set ROLE_E2E_ALLOW_REMOTE_SEED=1 only for an explicitly disposable environment.",
    );
  }
  return { appHost: app.hostname, databaseHost: database.hostname, explicitRemoteOverride: allowRemote };
}

/** Pure, unit-testable release oracle used by the live runner. */
export function evaluateRunOracle({
  requiredIds = REQUIRED_IDS,
  goldenPaths,
  validation,
  diagnostics,
  buildBinding,
  blockers = [],
  defects = [],
  steps = [],
}) {
  const failures = [];
  const actualIds = Object.keys(goldenPaths || {}).sort();
  const expectedIds = [...requiredIds].sort();
  if (!sameValue(actualIds, expectedIds)) {
    failures.push({ field: "releaseEvidence.goldenPaths", expected: expectedIds, actual: actualIds });
  }
  for (const id of requiredIds) {
    const entry = goldenPaths?.[id];
    if (entry?.schemaVersion !== 2) failures.push({ field: `${id}.schemaVersion`, expected: 2, actual: entry?.schemaVersion });
    if (entry?.status !== "PASS") failures.push({ field: `${id}.status`, expected: "PASS", actual: entry?.status });
    if (!Array.isArray(entry?.visualSteps) || entry.visualSteps.length === 0) {
      failures.push({ field: `${id}.visualSteps`, expected: "one or more real captures", actual: entry?.visualSteps });
    }
    if (!Array.isArray(entry?.actions) || entry.actions.length === 0) {
      failures.push({ field: `${id}.actions`, expected: "exact actions", actual: entry?.actions });
    }
  }
  for (const [index, step] of steps.entries()) {
    if (step?.status === "SKIP") failures.push({ field: `steps.${index}.status`, expected: "PASS", actual: "SKIP" });
  }
  if (validation?.valid !== requiredIds.length || validation?.total !== requiredIds.length) {
    failures.push({ field: "releaseEvidence.validation", expected: `${requiredIds.length}/${requiredIds.length}`, actual: `${validation?.valid}/${validation?.total}` });
  }
  for (const field of ["unexpectedConsoleErrors", "unexpectedRequestFailures", "unexpectedHttpErrors", "missingExpectedHttpErrors"]) {
    const value = diagnostics?.[field];
    if (!Array.isArray(value) || value.length !== 0) failures.push({ field: `diagnostics.${field}`, expected: [], actual: value });
  }
  if (buildBinding?.sameGitHead !== true || buildBinding?.sameBuildId !== true) {
    failures.push({ field: "buildBinding", expected: "same git head and build ID", actual: buildBinding });
  }
  if (blockers.length > 0) failures.push({ field: "blockers", expected: [], actual: blockers });
  if (defects.length > 0) failures.push({ field: "defects", expected: [], actual: defects });
  return { pass: failures.length === 0, failures };
}

function runtimeConfig(env = process.env) {
  const appUrl = (env.APP_URL || "http://localhost:3000").replace(/\/+$/, "");
  const apiUrl = (env.API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const databaseUrl = env.DATABASE_URL || "postgresql://cadverify:localdev@127.0.0.1:5432/cadverify";
  const runId = env.E2E_RUN_ID || `role-notification-${new Date().toISOString().replace(/[:.]/g, "-")}-${process.pid}`;
  const outputRoot = env.E2E_ARTIFACT_DIR
    ? path.resolve(env.E2E_ARTIFACT_DIR)
    : path.join(repoRoot, ".gstack", "qa-reports");
  return {
    appUrl,
    apiUrl,
    databaseUrl,
    runId,
    outputRoot,
    screenshotDir: path.join(outputRoot, "screenshots", `role-notification-${runId}`),
    artifacts: {
      json: path.join(outputRoot, `role-notification-browser-${runId}.json`),
      markdown: path.join(outputRoot, `role-notification-browser-${runId}.md`),
    },
    cubePath: path.join(backendRoot, "tests", "assets", "cube.step"),
    headed: false,
    allowRemoteSeed: env.ROLE_E2E_ALLOW_REMOTE_SEED === "1",
  };
}

function parseArgs(argv) {
  const options = { headed: false, help: false };
  for (const argument of argv) {
    if (argument === "--headed") options.headed = true;
    else if (argument === "--help" || argument === "-h") options.help = true;
    else throw new Error(`unknown argument: ${argument}`);
  }
  return options;
}

function usage() {
  return [
    "Usage: node scripts/e2e/role-notification-browser.mjs [--headed]",
    "",
    "Environment:",
    "  APP_URL / API_URL / DATABASE_URL   local stack coordinates",
    "  E2E_ARTIFACT_DIR / E2E_RUN_ID      evidence location and run identity",
    "  PYTHON                              backend virtualenv Python executable",
    "  ROLE_E2E_ALLOW_REMOTE_SEED=1        explicit disposable-remote override",
  ].join("\n") + "\n";
}

class Diagnostics {
  constructor(appUrl, pathIdProvider) {
    this.appUrl = appUrl;
    this.pathIdProvider = pathIdProvider;
    this.rawConsoleErrors = [];
    this.pageErrors = [];
    this.expectedRequestFailures = [];
    this.unexpectedRequestFailures = [];
    this.observedHttpErrors = [];
    this.expectedHttpErrors = [];
    this.transactions = [];
    this.requestCount = 0;
    this.responseCount = 0;
  }

  expectHttp(entry) {
    this.expectedHttpErrors.push(canonicalHttpReceipt(entry));
  }

  watch(page, persona) {
    page.on("request", () => { this.requestCount += 1; });
    page.on("response", (response) => {
      this.responseCount += 1;
      if (response.status() < 400) return;
      this.observedHttpErrors.push(canonicalHttpReceipt({
        pathId: this.pathIdProvider(),
        persona,
        channel: "browser",
        method: response.request().method(),
        path: response.url(),
        status: response.status(),
      }));
    });
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const location = message.location();
      this.rawConsoleErrors.push({
        pathId: this.pathIdProvider(),
        persona,
        pageUrl: redactUrl(page.url()),
        locationUrl: location?.url ? redactUrl(location.url) : "",
        text: message.text(),
      });
    });
    page.on("pageerror", (error) => {
      this.pageErrors.push({
        pathId: this.pathIdProvider(),
        persona,
        pageUrl: redactUrl(page.url()),
        text: error.message,
      });
    });
    page.on("requestfailed", (request) => {
      const headers = request.headers();
      const entry = {
        pathId: this.pathIdProvider(),
        persona,
        url: request.url(),
        method: request.method(),
        resourceType: request.resourceType(),
        error: request.failure()?.errorText || "request failed",
        hasNextAction: Boolean(headers["next-action"]),
      };
      if (isExpectedNextRscPrefetchAbort(entry, this.appUrl) || isExpectedOrganizationServerActionAbort(entry, this.appUrl)) {
        this.expectedRequestFailures.push({ ...entry, url: redactUrl(entry.url) });
      } else {
        this.unexpectedRequestFailures.push({ ...entry, url: redactUrl(entry.url) });
      }
    });
  }

  recordTransaction(entry) {
    this.transactions.push({
      at: new Date().toISOString(),
      pathId: entry.pathId,
      persona: entry.persona,
      channel: entry.channel,
      label: entry.label,
      method: entry.method,
      path: redactUrl(entry.path),
      status: entry.status,
      expectedStatus: entry.expectedStatus,
      contentType: entry.contentType || "",
      bytes: entry.bytes ?? null,
      sha256: entry.sha256 || null,
      errorCode: entry.errorCode || null,
    });
  }

  finalize() {
    const http = reconcileHttpOutcomes(this.observedHttpErrors, this.expectedHttpErrors);
    const consoleAccounting = reconcileConsoleErrors(
      this.rawConsoleErrors,
      http.matched.filter((entry) => entry.channel === "browser"),
    );
    return {
      requestCount: this.requestCount,
      responseCount: this.responseCount,
      transactions: this.transactions,
      expectedHttpErrors: http.matched,
      unexpectedHttpErrors: http.unexpected,
      missingExpectedHttpErrors: http.missing,
      expectedConsoleErrors: consoleAccounting.expected,
      unexpectedConsoleErrors: [...consoleAccounting.unexpected, ...this.pageErrors],
      expectedRequestFailures: this.expectedRequestFailures,
      unexpectedRequestFailures: this.unexpectedRequestFailures,
    };
  }
}

async function responsePayload(response) {
  const bytes = Buffer.from(await response.body());
  const text = bytes.toString("utf8");
  const contentType = String(response.headers()["content-type"] || "").split(";", 1)[0].toLowerCase();
  let body = text;
  if (/json|problem\+json/.test(contentType)) {
    try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  }
  return {
    status: response.status(),
    headers: response.headers(),
    contentType,
    bytes,
    text,
    body,
  };
}

class RoleNotificationBrowserRunner {
  constructor(config) {
    this.config = config;
    this.startedAt = Date.now();
    this.activePathId = "SETUP";
    this.assertions = Object.fromEntries(REQUIRED_IDS.map((id) => [id, []]));
    this.visualSteps = Object.fromEntries(REQUIRED_IDS.map((id) => [id, []]));
    this.pathResults = {};
    this.steps = [];
    this.blockers = [];
    this.defects = [];
    this.contexts = [];
    this.identities = {};
    this.resources = { costs: {}, drafts: { A: {}, B: {} }, notifications: {} };
    this.shotIndex = 0;
    this.diagnostics = new Diagnostics(config.appUrl, () => this.activePathId);
    this.password = `ProofShape-Role-${randomBytes(9).toString("hex")}-7!`;
    this.tag = `${Date.now().toString(36)}-${process.pid}-${randomBytes(4).toString("hex")}`;
  }

  record(id, name, expected, actual, pass = sameValue(expected, actual), detail = "") {
    invariant(REQUIRED_IDS.includes(id), `assertion used unknown golden ID ${id}`);
    const item = {
      name,
      expected: evidenceValue(expected),
      actual: evidenceValue(actual),
      pass: Boolean(pass),
      ...(detail ? { detail } : {}),
    };
    this.assertions[id].push(item);
    if (!item.pass) {
      throw new Error(`[${id}] ${name}: expected ${stableJson(expected)}, got ${stableJson(actual)}${detail ? ` (${detail})` : ""}`);
    }
    return actual;
  }

  equal(id, name, actual, expected, detail = "") {
    return this.record(id, name, expected, actual, sameValue(expected, actual), detail);
  }

  truth(id, name, actual, detail = "") {
    return this.record(id, name, true, Boolean(actual), Boolean(actual), detail);
  }

  excludes(id, name, value, forbidden) {
    const text = typeof value === "string" ? value : stableJson(value);
    const hits = forbidden.filter((needle) => needle && text.includes(String(needle)));
    return this.record(id, name, "no foreign identifier or marker", hits, hits.length === 0);
  }

  async init() {
    this.fixtureTarget = assertSafeFixtureTarget({
      appUrl: this.config.appUrl,
      databaseUrl: this.config.databaseUrl,
      allowRemote: this.config.allowRemoteSeed,
    });
    this.buildIdentityAtStart = captureBuildIdentity(repoRoot);
    await mkdir(this.config.screenshotDir, { recursive: true });
    this.cubeBytes = await readFile(this.config.cubePath);
    const launchOptions = {
      headless: !this.config.headed,
      args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
    };
    this.browser = await chromium.launch({ ...launchOptions, channel: "chrome" })
      .catch(() => chromium.launch(launchOptions));
  }

  async preflight() {
    const probe = async (url, label) => {
      try {
        const response = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(8_000) });
        return { label, url, response, error: null };
      } catch (error) {
        return { label, url, response: null, error: error instanceof Error ? error.message : String(error) };
      }
    };

    const [loginProbe, openapiProbe] = await Promise.all([
      probe(`${this.config.appUrl}/login`, "frontend login surface"),
      probe(`${this.config.apiUrl}/openapi.json`, "backend OpenAPI surface"),
    ]);
    const failedProbes = [loginProbe, openapiProbe].flatMap((item) => {
      if (item.error) return [`${item.label} unreachable at ${redactUrl(item.url)} (${item.error})`];
      if (item.response.status !== 200) return [`${item.label} HTTP ${item.response.status} at ${redactUrl(item.url)} (expected 200)`];
      return [];
    });
    invariant(failedProbes.length === 0, `BLOCKER service preflight failed before fixture provisioning: ${failedProbes.join("; ")}`);
    const login = loginProbe.response;
    const openapiResponse = openapiProbe.response;
    const openapi = await openapiResponse.json();
    const requiredOperations = [
      ["post", "/api/v1/notifications/{notification_id}/read"],
      ["post", "/api/v1/notifications/{notification_id}/dismiss"],
      ["post", "/api/v1/orgs/invites"],
      ["post", "/api/v1/orgs/invites/accept"],
      ["delete", "/api/v1/orgs/members/{user_id}"],
      ["post", "/api/v1/rate-library/{version_id}/publish"],
      ["post", "/api/v1/material-library/{version_id}/publish"],
      ["post", "/api/v1/shop-library/{version_id}/publish"],
      ["get", "/api/v1/cost-decisions/{decision_id}"],
      ["post", "/api/v1/cost-decisions/{decision_id}/approve"],
      ["get", "/api/v1/cost-decisions/{decision_id}/pdf"],
    ];
    const missingOperations = requiredOperations
      .filter(([method, pathname]) => !openapi?.paths?.[pathname]?.[method])
      .map(([method, pathname]) => `${method.toUpperCase()} ${pathname}`);
    invariant(missingOperations.length === 0, `BLOCKER backend OpenAPI is missing required live operations: ${missingOperations.join(", ")}`);
    this.servicePreflight = {
      frontend: { url: redactUrl(login.url || `${this.config.appUrl}/login`), status: login.status },
      backend: { url: redactUrl(openapiResponse.url || `${this.config.apiUrl}/openapi.json`), status: openapiResponse.status },
      requiredOperations: requiredOperations.map(([method, pathname]) => `${method.toUpperCase()} ${pathname}`),
      missingOperations,
    };
  }

  async provisionFixtures() {
    const script = String.raw`
import asyncio, json, sys
from sqlalchemy import text
from ulid import ULID
from src.auth.hashing import hash_password
import src.db.engine as eng

tag, password = sys.argv[1], sys.argv[2]

async def main():
    orgs = {key: str(ULID()) for key in ("A", "B")}
    people = {
        "owner_a": {"platform": "analyst", "org": "A", "org_role": "admin"},
        "owner_b": {"platform": "analyst", "org": "B", "org_role": "admin"},
        "viewer_a": {"platform": "viewer", "org": "A", "org_role": "viewer"},
        "member_a": {"platform": "analyst", "org": "A", "org_role": "member"},
        "lifecycle_candidate": {"platform": "viewer", "org": None, "org_role": None},
        "revoked_candidate": {"platform": "viewer", "org": None, "org_role": None},
    }
    out = {"tag": tag, "orgs": {}, "people": {}, "notifications": {}}
    async with eng.get_session_factory()() as session:
        for key, org_id in orgs.items():
            name = f"QA Role Notification Org {key} {tag}"
            await session.execute(text("INSERT INTO organizations (id,name,slug,created_at) VALUES (:id,:name,:slug,now())"), {
                "id": org_id, "name": name, "slug": f"qa-role-notification-{key.lower()}-{tag}"})
            out["orgs"][key] = {"id": org_id, "name": name}
        for key, spec in people.items():
            email = f"qa-role-notification-{tag}-{key.replace('_','-')}@example.com"
            current_org = orgs[spec["org"]] if spec["org"] else None
            row = (await session.execute(text("INSERT INTO users (email,email_lower,role,auth_provider,password_hash,current_org_id,is_active,session_version) VALUES (:email,:email,:role,'password',:password,:org,true,0) RETURNING id"), {
                "email": email, "role": spec["platform"], "password": hash_password(password), "org": current_org})).first()
            user_id = int(row[0])
            if current_org:
                await session.execute(text("INSERT INTO memberships (id,org_id,user_id,org_role,created_at) VALUES (:id,:org,:user,:role,now())"), {
                    "id": str(ULID()), "org": current_org, "user": user_id, "role": spec["org_role"]})
            out["people"][key] = {"id": user_id, "email": email, "platform_role": spec["platform"], "org_role": spec["org_role"], "org_id": current_org}
        for key, actor_key in (("A", "owner_a"), ("B", "owner_b")):
            notification_id = str(ULID())
            title = f"ROLE-NOTIFICATION-{key}-{tag}"
            body = f"PRIVATE-{key}-NOTIFICATION-BODY-{tag}"
            await session.execute(text("INSERT INTO notifications (ulid,org_id,actor_user_id,kind,severity,status,title,body,dest,source_type,source_id,metadata_json,created_at) VALUES (:id,:org,:actor,'role_e2e','info','open',:title,:body,'verify','role_e2e',:source,:metadata,now())"), {
                "id": notification_id, "org": orgs[key], "actor": out["people"][actor_key]["id"], "title": title,
                "body": body, "source": f"{tag}-{key}", "metadata": json.dumps({"private_marker": f"PRIVATE-{key}-{tag}"})})
            out["notifications"][key] = {"id": notification_id, "title": title, "body": body}
        await session.commit()
    print(json.dumps(out))
    await eng.dispose_engine()

asyncio.run(main())
`;
    const python = process.env.PYTHON?.trim() || path.join(backendRoot, ".venv", "bin", "python");
    const { stdout, stderr } = await execFileAsync(python, ["-c", script, this.tag, this.password], {
      cwd: backendRoot,
      env: {
        ...process.env,
        DATABASE_URL: this.config.databaseUrl,
        PYTHONPATH: backendRoot,
        PYTHONDONTWRITEBYTECODE: "1",
      },
      timeout: 60_000,
      maxBuffer: 1024 * 1024,
    });
    this.seedStderr = stderr.trim().slice(0, 2000);
    this.seed = JSON.parse(stdout);
    this.resources.notifications = this.seed.notifications;
  }

  async newContext(persona) {
    const octet = 30 + (Object.keys(this.identities).length * 17) % 190;
    const context = await this.browser.newContext({
      baseURL: this.config.appUrl,
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      acceptDownloads: true,
      extraHTTPHeaders: { "x-real-ip": `198.51.100.${octet}` },
    });
    this.contexts.push(context);
    const page = await context.newPage();
    this.diagnostics.watch(page, persona);
    return { persona, context, page };
  }

  async login(key) {
    const person = this.seed.people[key];
    invariant(person, `unknown fixture identity ${key}`);
    const actor = await this.newContext(key.replaceAll("_", "-"));
    await actor.page.goto("/login", { waitUntil: "domcontentloaded", timeout: 30_000 });
    const email = actor.page.getByLabel("Email");
    const password = actor.page.getByLabel("Password");
    const submit = actor.page.getByRole("button", { name: /^Log in$/i });
    await submit.waitFor({ state: "visible", timeout: 20_000 });
    await actor.page.waitForFunction(
      () => {
        const button = document.querySelector('form button[type="submit"]');
        return button instanceof HTMLButtonElement && !button.disabled;
      },
      undefined,
      { timeout: 20_000 },
    );
    // Filling before hydration can be lost when React takes control of the
    // server-rendered inputs. Hydration is now proven above; verify the exact
    // values again so native form validation cannot silently swallow a click.
    await email.fill(person.email);
    await password.fill(this.password);
    invariant(await email.inputValue() === person.email, `${key} email did not remain entered after hydration`);
    invariant(await password.inputValue() === this.password, `${key} password did not remain entered after hydration`);
    const responsePromise = actor.page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/auth/login",
    { timeout: 45_000 });
    await submit.click();
    const response = await responsePromise;
    this.diagnostics.recordTransaction({
      pathId: this.activePathId,
      persona: actor.persona,
      channel: "browser",
      label: "visible password login",
      method: "POST",
      path: response.url(),
      status: response.status(),
      expectedStatus: 200,
      contentType: response.headers()["content-type"],
    });
    invariant(response.status() === 200, `${key} visible login returned ${response.status()}`);
    await actor.page.waitForURL((url) => url.pathname !== "/login", { timeout: 20_000 });
    const cookie = (await actor.context.cookies()).find((item) => item.name === "dash_session");
    invariant(cookie?.value, `${key} login did not set dash_session`);
    Object.assign(actor, person, { key, sessionCookie: cookie.value });
    this.identities[key] = actor;
    return actor;
  }

  async api(actor, pathname, options = {}) {
    const pathId = options.pathId || this.activePathId;
    const method = String(options.method || "GET").toUpperCase();
    const expectedStatus = options.expectedStatus ?? 200;
    const channel = options.channel || "api-request";
    if (expectedStatus >= 400) {
      this.diagnostics.expectHttp({ pathId, persona: actor.persona, channel, method, path: pathname, status: expectedStatus });
    }
    const requestOptions = {
      method,
      failOnStatusCode: false,
      timeout: options.timeout || 120_000,
      headers: options.headers,
    };
    if (Object.hasOwn(options, "data")) requestOptions.data = options.data;
    if (options.multipart) requestOptions.multipart = options.multipart;
    const response = await actor.context.request.fetch(pathname, requestOptions);
    const payload = await responsePayload(response);
    if (payload.status >= 400) {
      this.diagnostics.observedHttpErrors.push(canonicalHttpReceipt({
        pathId, persona: actor.persona, channel, method, path: pathname, status: payload.status,
      }));
    }
    this.diagnostics.recordTransaction({
      pathId,
      persona: actor.persona,
      channel,
      label: options.label || pathname,
      method,
      path: pathname,
      status: payload.status,
      expectedStatus,
      contentType: payload.contentType,
      bytes: payload.bytes.length,
      sha256: sha256(payload.bytes),
      errorCode: errorCode(payload.body),
    });
    if (REQUIRED_IDS.includes(pathId)) {
      this.equal(pathId, options.label || `${method} ${redactUrl(pathname)} status`, payload.status, expectedStatus);
    } else {
      invariant(payload.status === expectedStatus, `${method} ${pathname}: expected ${expectedStatus}, got ${payload.status}: ${payload.text.slice(0, 500)}`);
    }
    return payload;
  }

  async browserFetch(actor, pathname, options = {}) {
    const id = options.pathId || this.activePathId;
    const method = String(options.method || "GET").toUpperCase();
    const expectedStatus = options.expectedStatus ?? 200;
    if (expectedStatus >= 400) {
      this.diagnostics.expectHttp({ pathId: id, persona: actor.persona, channel: "browser", method, path: pathname, status: expectedStatus });
    }
    const result = await actor.page.evaluate(async ({ target, requestMethod, data }) => {
      const response = await fetch(target, {
        method: requestMethod,
        headers: data === undefined ? undefined : { "content-type": "application/json" },
        body: data === undefined ? undefined : JSON.stringify(data),
        cache: "no-store",
      });
      const bytes = new Uint8Array(await response.arrayBuffer());
      const text = new TextDecoder().decode(bytes);
      const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
      const digestHex = [...digest].map((value) => value.toString(16).padStart(2, "0")).join("");
      let body = text;
      if (/json|problem\+json/i.test(response.headers.get("content-type") || "")) {
        try { body = text ? JSON.parse(text) : null; } catch { body = text; }
      }
      return {
        status: response.status,
        contentType: response.headers.get("content-type") || "",
        contentDisposition: response.headers.get("content-disposition") || "",
        bytes: bytes.length,
        sha256: digestHex,
        text: text.slice(0, 5000),
        body,
      };
    }, { target: pathname, requestMethod: method, data: options.data });
    this.diagnostics.recordTransaction({
      pathId: id,
      persona: actor.persona,
      channel: "browser",
      label: options.label || pathname,
      method,
      path: pathname,
      status: result.status,
      expectedStatus,
      contentType: result.contentType,
      bytes: result.bytes,
      sha256: result.sha256,
      errorCode: errorCode(result.body),
    });
    this.equal(id, options.label || `${method} ${redactUrl(pathname)} status`, result.status, expectedStatus);
    return result;
  }

  async browserMultipart(actor, pathname, fields, options = {}) {
    const id = options.pathId || this.activePathId;
    const method = String(options.method || "POST").toUpperCase();
    const expectedStatus = options.expectedStatus ?? 200;
    const encodedFields = Object.entries(fields).map(([name, value]) => {
      if (value && typeof value === "object" && Object.hasOwn(value, "buffer")) {
        return {
          name,
          kind: "file",
          filename: value.name,
          mimeType: value.mimeType || "application/octet-stream",
          base64: Buffer.from(value.buffer).toString("base64"),
        };
      }
      return { name, kind: "text", value: String(value) };
    });
    const result = await actor.page.evaluate(async ({ target, requestMethod, formFields }) => {
      const form = new FormData();
      for (const field of formFields) {
        if (field.kind === "file") {
          const binary = atob(field.base64);
          const bytes = new Uint8Array(binary.length);
          for (let index = 0; index < binary.length; index += 1) {
            bytes[index] = binary.charCodeAt(index);
          }
          form.append(field.name, new File([bytes], field.filename, { type: field.mimeType }));
        } else {
          form.append(field.name, field.value);
        }
      }
      const response = await fetch(target, {
        method: requestMethod,
        body: form,
        cache: "no-store",
      });
      const bytes = new Uint8Array(await response.arrayBuffer());
      const text = new TextDecoder().decode(bytes);
      const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
      const digestHex = [...digest].map((value) => value.toString(16).padStart(2, "0")).join("");
      let body = text;
      if (/json|problem\+json/i.test(response.headers.get("content-type") || "")) {
        try { body = text ? JSON.parse(text) : null; } catch { body = text; }
      }
      return {
        status: response.status,
        contentType: response.headers.get("content-type") || "",
        bytes: bytes.length,
        sha256: digestHex,
        text: text.slice(0, 5000),
        body,
      };
    }, { target: pathname, requestMethod: method, formFields: encodedFields });
    this.diagnostics.recordTransaction({
      pathId: id,
      persona: actor.persona,
      channel: "browser",
      label: options.label || pathname,
      method,
      path: pathname,
      status: result.status,
      expectedStatus,
      contentType: result.contentType,
      bytes: result.bytes,
      sha256: result.sha256,
      errorCode: errorCode(result.body),
    });
    this.equal(id, options.label || `${method} ${redactUrl(pathname)} status`, result.status, expectedStatus);
    return result;
  }

  async browserActionResponse(actor, spec, action) {
    const id = spec.pathId || this.activePathId;
    const method = String(spec.method || "GET").toUpperCase();
    if (spec.expectedStatus >= 400) {
      this.diagnostics.expectHttp({ pathId: id, persona: actor.persona, channel: "browser", method, path: spec.path, status: spec.expectedStatus });
    }
    const responsePromise = actor.page.waitForResponse((response) =>
      response.request().method() === method && new URL(response.url()).pathname === spec.path,
    { timeout: spec.timeout || 45_000 });
    await action();
    const response = await responsePromise;
    const payload = await responsePayload(response);
    this.diagnostics.recordTransaction({
      pathId: id,
      persona: actor.persona,
      channel: "browser",
      label: spec.label,
      method,
      path: spec.path,
      status: payload.status,
      expectedStatus: spec.expectedStatus,
      contentType: payload.contentType,
      bytes: payload.bytes.length,
      sha256: sha256(payload.bytes),
      errorCode: errorCode(payload.body),
    });
    this.equal(id, `${spec.label} HTTP status`, payload.status, spec.expectedStatus);
    return payload;
  }

  async capture(id, actor, stage, requiredVisible, forbiddenVisible = [], fullPage = true) {
    const bodyText = cleanText(await actor.page.locator("body").innerText());
    for (const visible of requiredVisible) {
      this.truth(id, `${stage} visibly contains ${visible}`, bodyText.toLocaleLowerCase().includes(visible.toLocaleLowerCase()));
    }
    for (const forbidden of forbiddenVisible) {
      this.equal(id, `${stage} visibly excludes ${forbidden}`, bodyText.toLocaleLowerCase().includes(forbidden.toLocaleLowerCase()), false);
    }
    this.shotIndex += 1;
    const screenshot = path.join(
      this.config.screenshotDir,
      `${String(this.shotIndex).padStart(2, "0")}-${id}-${stage}.png`,
    );
    const visual = await captureVisualStep(actor.page, {
      id,
      stage,
      terminal: false,
      screenshot,
      requiredVisible,
      forbiddenVisible,
      fullPage,
    });
    this.visualSteps[id].push(visual);
    return visual;
  }

  async createCost(actor, orgKey) {
    const filename = `ROLE-NOTIFICATION-${orgKey}-${this.tag}.step`;
    const result = await this.browserMultipart(actor, "/api/proxy/validate/cost", {
      file: { name: filename, mimeType: "application/step", buffer: this.cubeBytes },
      qty: "50",
      material_class: "polymer",
    }, {
      method: "POST",
      expectedStatus: 200,
      label: `setup ${orgKey} real STEP cost decision`,
    });
    invariant(result.body?.saved?.id, `${orgKey} cost response omitted saved.id`);
    return { id: result.body.saved.id, filename, meshHash: result.body?.saved?.mesh_hash || result.body?.mesh_hash || null };
  }

  async createDrafts(actor, orgKey) {
    for (const library of LIBRARIES) {
      const response = await this.api(actor, `/api/proxy/${library.path}`, {
        method: "POST",
        data: library.create(`${orgKey.toLowerCase()}-${this.tag}`),
        expectedStatus: 200,
        label: `setup ${orgKey} ${library.key} draft`,
      });
      invariant(Number.isInteger(response.body?.id), `${orgKey} ${library.key} draft omitted numeric id`);
      invariant(response.body?.status === "draft", `${orgKey} ${library.key} fixture was not draft`);
      this.resources.drafts[orgKey][library.key] = {
        id: response.body.id,
        path: library.path,
        body: response.body,
      };
    }
  }

  async setupLiveResources() {
    this.activePathId = "SETUP";
    const ownerA = await this.login("owner_a");
    const ownerB = await this.login("owner_b");
    await this.login("viewer_a");
    await this.login("member_a");
    this.resources.costs.A = await this.createCost(ownerA, "A");
    this.resources.costs.B = await this.createCost(ownerB, "B");
    await this.createDrafts(ownerA, "A");
    await this.createDrafts(ownerB, "B");
  }

  async notificationList(actor, { unread = false, dismissed = false, id = "VER-04", label = "notification collection" } = {}) {
    return this.api(actor, `/api/proxy/notifications?status=open&unread=${unread}&dismissed=${dismissed}&limit=100`, {
      pathId: id,
      expectedStatus: 200,
      label,
    });
  }

  async runVer04() {
    const id = "VER-04";
    const actor = this.identities.viewer_a;
    const target = this.resources.notifications.A;
    const foreign = this.resources.notifications.B;
    await actor.page.goto("/notifications", { waitUntil: "domcontentloaded", timeout: 30_000 });
    let row = actor.page.locator(`[data-notification-id="${target.id}"]`);
    await row.waitFor({ state: "visible", timeout: 20_000 });
    this.equal(id, "organization A inbox excludes organization B title", await actor.page.getByText(foreign.title, { exact: true }).count(), 0);
    this.equal(id, "initial read timestamp attribute", await row.getAttribute("data-read-at"), "");
    this.truth(id, "initial row is visibly unread", (await row.innerText()).includes("Unread"));

    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    row = actor.page.locator(`[data-notification-id="${target.id}"]`);
    await row.waitFor({ state: "visible", timeout: 20_000 });
    this.equal(id, "unread state survives full refresh", await row.getAttribute("data-read-at"), "");
    const unreadApi = await this.notificationList(actor, { unread: true, id, label: "unread collection after refresh" });
    this.equal(id, "unread API retains exact target once", unreadApi.body.notifications.filter((item) => item.id === target.id).length, 1);
    const unreadVisual = await this.capture(id, actor, "unread-after-refresh", [target.title, target.body, "Unread"]);

    const readStarted = Date.now();
    const readResponse = await this.browserActionResponse(actor, {
      pathId: id,
      method: "POST",
      path: `/api/proxy/notifications/${target.id}/read`,
      expectedStatus: 200,
      label: "Open notification mark-read",
    }, () => actor.page.getByRole("link", { name: `Open notification: ${target.title}`, exact: true }).click());
    const readFinished = Date.now();
    const readState = readResponse.body?.notification;
    this.equal(id, "read response notification id", readState?.id, target.id);
    this.equal(id, "read response boolean", readState?.is_read, true);
    this.equal(id, "read response remains active", readState?.is_dismissed, false);
    this.truth(id, "read timestamp bounded by visible action", isoMilliseconds(readState?.read_at) >= readStarted - 1000 && isoMilliseconds(readState?.read_at) <= readFinished + 1000);
    await actor.page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });

    const allAfterRead = await this.notificationList(actor, { id, label: "active collection after read" });
    const unreadAfterRead = await this.notificationList(actor, { unread: true, id, label: "unread collection after read" });
    const persistedRead = allAfterRead.body.notifications.find((item) => item.id === target.id);
    this.equal(id, "API persisted exact read timestamp", persistedRead?.read_at, readState.read_at);
    this.equal(id, "read target absent from unread API", unreadAfterRead.body.notifications.some((item) => item.id === target.id), false);

    await actor.page.goto("/notifications", { waitUntil: "domcontentloaded", timeout: 30_000 });
    row = actor.page.locator(`[data-notification-id="${target.id}"]`);
    await row.waitFor({ state: "visible", timeout: 20_000 });
    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    row = actor.page.locator(`[data-notification-id="${target.id}"]`);
    await row.waitFor({ state: "visible", timeout: 20_000 });
    this.equal(id, "read timestamp survives full refresh", await row.getAttribute("data-read-at"), readState.read_at);
    this.truth(id, "refreshed row visibly says Read", (await row.innerText()).includes("Read "));
    const readVisual = await this.capture(id, actor, "read-after-refresh", [target.title, target.body, "Read "]);

    const dismissedStarted = Date.now();
    const dismissResponse = await this.browserActionResponse(actor, {
      pathId: id,
      method: "POST",
      path: `/api/proxy/notifications/${target.id}/dismiss`,
      expectedStatus: 200,
      label: "Dismiss notification",
    }, () => actor.page.getByRole("button", { name: `Dismiss notification: ${target.title}`, exact: true }).click());
    const dismissedFinished = Date.now();
    const dismissedState = dismissResponse.body?.notification;
    this.equal(id, "dismiss response notification id", dismissedState?.id, target.id);
    this.equal(id, "dismiss preserves exact read timestamp", dismissedState?.read_at, readState.read_at);
    this.equal(id, "dismiss response boolean", dismissedState?.is_dismissed, true);
    this.truth(id, "dismiss timestamp bounded by visible action", isoMilliseconds(dismissedState?.dismissed_at) >= dismissedStarted - 1000 && isoMilliseconds(dismissedState?.dismissed_at) <= dismissedFinished + 1000);

    const activeAfterDismiss = await this.notificationList(actor, { id, label: "active collection after dismiss" });
    const dismissedAfterDismiss = await this.notificationList(actor, { dismissed: true, id, label: "dismissed collection after dismiss" });
    this.equal(id, "dismiss removes exact row from active API", activeAfterDismiss.body.notifications.some((item) => item.id === target.id), false);
    const persistedDismissed = dismissedAfterDismiss.body.notifications.find((item) => item.id === target.id);
    this.equal(id, "dismissed API persists exact timestamp", persistedDismissed?.dismissed_at, dismissedState.dismissed_at);
    this.equal(id, "dismissed API preserves read timestamp", persistedDismissed?.read_at, readState.read_at);

    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    const dismissedRow = actor.page.locator(`[data-notification-id="${target.id}"][data-dismissed-at]`);
    await dismissedRow.waitFor({ state: "visible", timeout: 20_000 });
    this.equal(id, "dismiss timestamp survives full refresh", await dismissedRow.getAttribute("data-dismissed-at"), dismissedState.dismissed_at);
    this.truth(id, "dismissed row visibly labels terminal state", (await dismissedRow.innerText()).includes("Dismissed "));
    const dismissedVisual = await this.capture(id, actor, "dismissed-after-refresh", [target.title, target.body, "Dismissed "]);

    return {
      observed: {
        url: actor.page.url(),
        visible: [target.title, target.body, "Unread", "Read", "Dismissed"],
        persisted: { unread: unreadApi.body.notifications.find((item) => item.id === target.id), read: persistedRead, dismissed: persistedDismissed },
        numeric: { readStatus: readResponse.status, dismissStatus: dismissResponse.status, unreadAfterRead: 0, activeAfterDismiss: 0, dismissedAfterDismiss: 1 },
        authorization: { organization: "A", foreignBTitleVisible: false },
        recovery: "Each browser refresh re-read the server state: unread before open, the exact read_at after open, and the exact dismissed_at after dismissal.",
      },
      screenshot: dismissedVisual.screenshot,
      visuals: [unreadVisual, readVisual, dismissedVisual],
    };
  }

  async runRole01() {
    const id = "ROLE-01";
    const actor = this.identities.viewer_a;
    const own = this.resources.costs.A;
    const detail = await this.browserActionResponse(actor, {
      pathId: id,
      method: "GET",
      path: `/api/proxy/cost-decisions/${own.id}`,
      expectedStatus: 200,
      label: "same-organization evidence detail",
    }, () => actor.page.goto(`/cost-decisions/${own.id}`, { waitUntil: "domcontentloaded", timeout: 30_000 }));
    await actor.page.getByText(own.filename, { exact: true }).first().waitFor({ timeout: 20_000 });
    await actor.page.getByTestId("cost-decision-read-only").waitFor({ state: "visible", timeout: 20_000 });
    await actor.page.getByText("Read-only access. An analyst can record an outcome or change its note.", { exact: true }).waitFor();

    const mutationControls = [
      actor.page.getByRole("button", { name: "Approve", exact: true }),
      actor.page.getByRole("button", { name: "Reopen", exact: true }),
      actor.page.getByRole("button", { name: "Share", exact: true }),
      actor.page.getByRole("button", { name: "RFQ ZIP", exact: true }),
      actor.page.getByTestId("record-disposition-inhouse"),
      actor.page.getByTestId("record-disposition-outside"),
      actor.page.getByTestId("record-disposition-capability"),
      actor.page.getByTestId("record-disposition-redesign"),
      actor.page.getByTestId("record-disposition-note"),
      actor.page.getByTestId("record-disposition-note-save"),
    ];
    const mutationControlCount = (await Promise.all(mutationControls.map((locator) => locator.count()))).reduce((sum, count) => sum + count, 0);
    this.equal(id, "viewer mutation controls rendered", mutationControlCount, 0);
    for (const label of ["Download PDF", "JSON", "CSV"]) {
      this.equal(id, `viewer readable export control ${label}`, await actor.page.getByRole("button", { name: label, exact: true }).count(), 1);
    }

    const exportResponsePromise = actor.page.waitForResponse((response) =>
      response.request().method() === "GET" && new URL(response.url()).pathname === `/api/proxy/cost-decisions/${own.id}/export.json`,
    { timeout: 45_000 });
    const downloadPromise = actor.page.waitForEvent("download", { timeout: 45_000 });
    await actor.page.getByRole("button", { name: "JSON", exact: true }).click();
    const [exportResponse, download] = await Promise.all([exportResponsePromise, downloadPromise]);
    const exportPayload = await responsePayload(exportResponse);
    this.equal(id, "visible JSON export HTTP status", exportPayload.status, 200);
    this.truth(id, "visible JSON export returned nonempty evidence", exportPayload.bytes.length > 100);
    this.truth(id, "visible JSON download retained cost filename", download.suggestedFilename().includes(own.filename.replace(/\.step$/i, "")));
    this.diagnostics.recordTransaction({
      pathId: id, persona: actor.persona, channel: "browser", label: "visible JSON evidence download", method: "GET",
      path: `/api/proxy/cost-decisions/${own.id}/export.json`, status: exportPayload.status, expectedStatus: 200,
      contentType: exportPayload.contentType, bytes: exportPayload.bytes.length, sha256: sha256(exportPayload.bytes),
    });

    await actor.page.getByRole("button", { name: "JSON", exact: true }).waitFor({ state: "visible", timeout: 10_000 });
    this.equal(id, "JSON export control re-enabled after download", await actor.page.getByRole("button", { name: "JSON", exact: true }).isEnabled(), true);

    const evidenceVisual = await this.capture(id, actor, "viewer-readable-no-mutations", [own.filename, "Read-only access", "Download PDF", "JSON", "CSV"]);
    const before = detail.body;
    const deniedApproval = await this.browserFetch(actor, `/api/proxy/cost-decisions/${own.id}/approve`, {
      pathId: id,
      method: "POST",
      data: { note: "viewer must not sign" },
      expectedStatus: 403,
      label: "viewer approval denial",
    });
    this.equal(id, "viewer approval denial code", errorCode(deniedApproval.body), "insufficient_role");
    const after = await this.browserFetch(actor, `/api/proxy/cost-decisions/${own.id}`, {
      pathId: id,
      expectedStatus: 200,
      label: "decision after denied viewer approval",
    });
    this.equal(id, "denied approval leaves complete decision unchanged", after.body, before);

    await actor.page.goto("/settings/organization", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await actor.page.getByText("Admins only", { exact: true }).waitFor({ timeout: 20_000 });
    const gateText = cleanText(await actor.page.locator("body").innerText());
    this.truth(id, "organization gate names viewer role", gateText.includes("You're a viewer"));
    this.equal(id, "viewer invite control absent", await actor.page.getByRole("button", { name: "Send invite", exact: true }).count(), 0);
    const deniedInvite = await this.browserFetch(actor, "/api/proxy/orgs/invites", {
      pathId: id,
      method: "POST",
      data: { email: `denied-${this.tag}@example.com`, role: "viewer" },
      expectedStatus: 403,
      label: "viewer organization-admin denial",
    });
    this.equal(id, "viewer invitation denial code", errorCode(deniedInvite.body), "insufficient_org_role");
    const gateVisual = await this.capture(id, actor, "viewer-admin-gate", ["Organization", "Admins only", "You're a viewer"]);

    return {
      observed: {
        url: actor.page.url(),
        visible: [own.filename, "Read-only access. An analyst can record an outcome or change its note.", "Admins only", "You're a viewer"],
        persisted: { decisionBefore: before, decisionAfter: after.body, exportSha256: sha256(exportPayload.bytes) },
        numeric: { readableDetailStatus: detail.status, jsonDownloadStatus: exportPayload.status, mutationControls: mutationControlCount, approvalStatus: deniedApproval.status, inviteStatus: deniedInvite.status },
        authorization: { platformRole: "viewer", orgRole: "viewer", readableEvidence: 200, approvalMutation: 403, organizationMutation: 403 },
        recovery: "After both exact 403 denials, the persisted decision remained byte-for-byte equal to the pre-denial API document.",
      },
      screenshot: evidenceVisual.screenshot,
      visuals: [evidenceVisual, gateVisual],
    };
  }

  async runRole02() {
    const id = "ROLE-02";
    const actor = this.identities.member_a;
    await actor.page.goto("/settings/organization", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await actor.page.getByText("Admins only", { exact: true }).waitFor({ timeout: 20_000 });
    const body = cleanText(await actor.page.locator("body").innerText());
    this.truth(id, "organization gate names member role", body.includes("You're a member"));
    this.equal(id, "member invite control absent", await actor.page.getByRole("button", { name: "Send invite", exact: true }).count(), 0);
    const visual = await this.capture(id, actor, "analyst-member-admin-gate", ["Organization", "Admins only", "You're a member"]);

    const outcomes = {};
    for (const library of LIBRARIES) {
      const draft = this.resources.drafts.A[library.key];
      const before = await this.browserFetch(actor, `/api/proxy/${library.path}/${draft.id}`, {
        pathId: id,
        expectedStatus: 200,
        label: `${library.key} member reads draft`,
      });
      this.equal(id, `${library.key} starts draft`, before.body?.status, "draft");
      const denied = await this.browserFetch(actor, `/api/proxy/${library.path}/${draft.id}/publish`, {
        pathId: id,
        method: "POST",
        data: {},
        expectedStatus: 403,
        label: `${library.key} analyst/member publish denial`,
      });
      this.equal(id, `${library.key} publication denial code`, errorCode(denied.body), "insufficient_org_role");
      const after = await this.browserFetch(actor, `/api/proxy/${library.path}/${draft.id}`, {
        pathId: id,
        expectedStatus: 200,
        label: `${library.key} draft after denied publish`,
      });
      this.equal(id, `${library.key} denied publish leaves exact draft unchanged`, after.body, before.body);
      this.equal(id, `${library.key} remains draft`, after.body?.status, "draft");
      outcomes[library.key] = { id: draft.id, denialStatus: denied.status, denialCode: errorCode(denied.body), before: before.body, after: after.body };
    }

    return {
      observed: {
        url: actor.page.url(),
        visible: ["Organization", "Admins only", "You're a member"],
        persisted: outcomes,
        numeric: { governedLibraries: LIBRARIES.length, publishAttempts: LIBRARIES.length, denied: Object.values(outcomes).filter((item) => item.denialStatus === 403).length },
        authorization: { platformRole: "analyst", orgRole: "member", ratePublish: 403, materialPublish: 403, shopPublish: 403 },
        recovery: "Every governed draft was re-read after denial and remained exactly equal to its pre-attempt draft document.",
      },
      screenshot: visual.screenshot,
      visuals: [visual],
    };
  }

  async createInviteThroughUi(owner, email, id, label) {
    await owner.page.locator("#invite-email").fill(email);
    const response = await this.browserActionResponse(owner, {
      pathId: id,
      method: "POST",
      path: "/settings/organization",
      expectedStatus: 200,
      label,
    }, () => owner.page.getByRole("button", { name: "Send invite", exact: true }).click());
    const message = owner.page.getByText(/One-time accept link \(shown once\):/i);
    await message.waitFor({ state: "visible", timeout: 20_000 });
    const link = cleanText(await message.locator("xpath=..").locator("code").innerText()).replace(/\s/g, "");
    invariant(link.includes("token="), `${label} did not expose the one-time accept link`);
    await owner.page.getByRole("row").filter({ hasText: email }).waitFor({ state: "visible", timeout: 20_000 });
    return { link, responseStatus: response.status };
  }

  async runRole03() {
    const id = "ROLE-03";
    const owner = this.identities.owner_a;
    const candidatePerson = this.seed.people.lifecycle_candidate;
    const revokedPerson = this.seed.people.revoked_candidate;
    await owner.page.goto("/settings/organization", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await owner.page.getByText(/Manage members, invites, and SSO for/i).waitFor({ timeout: 20_000 });

    const acceptedInvite = await this.createInviteThroughUi(owner, candidatePerson.email, id, "admin creates member invitation");
    const pendingInvites = await this.api(owner, "/api/proxy/orgs/invites", { pathId: id, expectedStatus: 200, label: "pending invitation persistence" });
    const pending = pendingInvites.body.invites.find((item) => item.email === candidatePerson.email);
    this.equal(id, "created invitation persisted pending", pending?.status, "pending");
    this.equal(id, "created invitation persisted role", pending?.role, "member");

    const candidate = await this.login("lifecycle_candidate");
    const acceptResponse = await this.browserActionResponse(candidate, {
      pathId: id,
      method: "POST",
      path: "/api/proxy/orgs/invites/accept",
      expectedStatus: 200,
      label: "invited account accepts exact token",
    }, () => candidate.page.goto(appPath(acceptedInvite.link, this.config.appUrl), { waitUntil: "domcontentloaded", timeout: 30_000 }));
    await candidate.page.getByText("Invitation accepted.", { exact: true }).waitFor({ timeout: 20_000 });
    await candidate.page.getByText("You joined the organization as member.", { exact: true }).waitFor();
    this.equal(id, "accept response role", acceptResponse.body?.org_role, "member");
    this.equal(id, "accept response created membership", acceptResponse.body?.created, true);
    await candidate.page.goto("/settings/organization", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await candidate.page.getByText("Admins only", { exact: true }).waitFor({ timeout: 20_000 });

    await owner.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    const memberRow = owner.page.getByRole("row").filter({
      hasText: candidatePerson.email,
      has: owner.page.getByRole("button", { name: "Remove", exact: true }),
    });
    await memberRow.waitFor({ state: "visible", timeout: 20_000 });
    await memberRow.getByText("member", { exact: true }).waitFor();
    const membersAfterAccept = await this.api(owner, "/api/proxy/orgs/members", { pathId: id, expectedStatus: 200, label: "member collection after accept" });
    this.equal(id, "accepted member persisted exactly once", membersAfterAccept.body.members.filter((item) => item.user_id === candidatePerson.id).length, 1);
    const acceptedVisual = await this.capture(id, owner, "accepted-member-persisted", ["Members", candidatePerson.email, "member"]);

    const revokedInvite = await this.createInviteThroughUi(owner, revokedPerson.email, id, "admin creates revocable invitation");
    let revokedRow = owner.page.getByRole("row").filter({ hasText: revokedPerson.email });
    await revokedRow.getByRole("button", { name: "Revoke", exact: true }).click();
    const revokeResponse = await this.browserActionResponse(owner, {
      pathId: id,
      method: "POST",
      path: "/settings/organization",
      expectedStatus: 200,
      label: "admin confirms invitation revocation",
    }, () => owner.page.getByRole("alertdialog").getByRole("button", { name: "Revoke invite", exact: true }).click());
    revokedRow = owner.page.getByRole("row").filter({ hasText: revokedPerson.email });
    await revokedRow.getByText("revoked", { exact: true }).waitFor({ timeout: 20_000 });
    const invitesAfterRevoke = await this.api(owner, "/api/proxy/orgs/invites", { pathId: id, expectedStatus: 200, label: "revoked invitation persistence" });
    this.equal(id, "revoked invitation persisted", invitesAfterRevoke.body.invites.find((item) => item.email === revokedPerson.email)?.status, "revoked");

    let removableRow = owner.page.getByRole("row").filter({
      hasText: candidatePerson.email,
      has: owner.page.getByRole("button", { name: "Remove", exact: true }),
    });
    await removableRow.getByRole("button", { name: "Remove", exact: true }).click();
    const removeResponse = await this.browserActionResponse(owner, {
      pathId: id,
      method: "POST",
      path: "/settings/organization",
      expectedStatus: 200,
      label: "admin confirms member removal",
    }, () => owner.page.getByRole("alertdialog").getByRole("button", { name: "Remove member", exact: true }).click());
    removableRow = owner.page.getByRole("row").filter({
      hasText: candidatePerson.email,
      has: owner.page.getByRole("button", { name: "Remove", exact: true }),
    });
    await removableRow.waitFor({ state: "detached", timeout: 20_000 });
    const membersAfterRemoval = await this.api(owner, "/api/proxy/orgs/members", { pathId: id, expectedStatus: 200, label: "member collection after removal" });
    this.equal(id, "removed member absent from durable admin collection", membersAfterRemoval.body.members.some((item) => item.user_id === candidatePerson.id), false);
    const candidateOrgs = await this.api(candidate, "/api/proxy/orgs", { pathId: id, expectedStatus: 200, label: "removed member live-session organizations" });
    this.equal(id, "removed member has no active organization", candidateOrgs.body.active_org_id, null);
    this.equal(id, "removed member has no organizations", candidateOrgs.body.organizations, []);
    await owner.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    await owner.page.getByRole("row").filter({ hasText: revokedPerson.email }).getByText("revoked", { exact: true }).waitFor({ timeout: 20_000 });
    const refreshedMemberRows = owner.page.getByRole("row").filter({
      hasText: candidatePerson.email,
      has: owner.page.getByRole("button", { name: "Remove", exact: true }),
    });
    this.equal(id, "removed member remains absent after admin refresh", await refreshedMemberRows.count(), 0);
    const removedVisual = await this.capture(id, owner, "removed-member-revoked-invite", ["Members", "Invitations", revokedPerson.email, "revoked"]);

    return {
      observed: {
        url: owner.page.url(),
        visible: [candidatePerson.email, "member", revokedPerson.email, "revoked"],
        persisted: { pending, acceptedMember: membersAfterAccept.body.members.find((item) => item.user_id === candidatePerson.id), revokedInvite: invitesAfterRevoke.body.invites.find((item) => item.email === revokedPerson.email), membersAfterRemoval: membersAfterRemoval.body.members, candidateOrganizations: candidateOrgs.body },
        numeric: { inviteUiStatus: acceptedInvite.responseStatus, acceptStatus: acceptResponse.status, revokeUiStatus: revokeResponse.status, removeUiStatus: removeResponse.status, membershipsAfterRemoval: candidateOrgs.body.organizations.length },
        authorization: { adminOrgRole: "admin", acceptedOrgRole: "member", removedActiveOrg: null },
        recovery: "The admin refresh retained the revoked invitation while the removed account's already-open session immediately returned an empty organization collection.",
      },
      screenshot: removedVisual.screenshot,
      visuals: [acceptedVisual, removedVisual],
      sensitiveRuntimeOnly: { revokedLinkWasGenerated: revokedInvite.link.includes("token=") },
    };
  }

  async opaquePair(id, actor, label, knownPath, unknownPath, options = {}) {
    const known = await this.browserFetch(actor, knownPath, {
      pathId: id,
      method: options.method || "GET",
      data: options.data,
      expectedStatus: 404,
      label: `${label} known foreign`,
    });
    const unknown = await this.browserFetch(actor, unknownPath, {
      pathId: id,
      method: options.method || "GET",
      data: options.data,
      expectedStatus: 404,
      label: `${label} unknown identifier`,
    });
    this.equal(id, `${label} known/unknown response body`, known.body, unknown.body);
    this.excludes(id, `${label} response excludes foreign markers`, known.body, options.forbidden || []);
    return { knownStatus: known.status, unknownStatus: unknown.status, body: known.body };
  }

  async runRole04() {
    const id = "ROLE-04";
    const viewer = this.identities.viewer_a;
    const foreignCost = this.resources.costs.B;
    const foreignUi = await this.browserActionResponse(viewer, {
      pathId: id,
      method: "GET",
      path: `/api/proxy/cost-decisions/${foreignCost.id}`,
      expectedStatus: 404,
      label: "known foreign cost detail UI",
    }, () => viewer.page.goto(`/cost-decisions/${foreignCost.id}`, { waitUntil: "domcontentloaded", timeout: 30_000 }));
    await viewer.page.getByText("Cost decision not found", { exact: true }).waitFor({ timeout: 20_000 });
    const foreignPageText = cleanText(await viewer.page.locator("body").innerText());
    this.excludes(id, "foreign UI excludes B evidence", foreignPageText, [foreignCost.filename, this.resources.notifications.B.title, this.resources.notifications.B.body]);
    const visual = await this.capture(id, viewer, "foreign-identifier-not-found", ["Cost decision not found"], [foreignCost.filename, this.resources.notifications.B.title]);

    const directions = [
      { actor: this.identities.owner_a, own: "A", foreign: "B" },
      { actor: this.identities.owner_b, own: "B", foreign: "A" },
    ];
    const costOutcomes = {};
    const libraryOutcomes = {};
    const notificationOutcomes = {};
    const ghost = ghostUlid();

    for (const direction of directions) {
      const key = `${direction.own}->${direction.foreign}`;
      const ownCost = this.resources.costs[direction.own];
      const otherCost = this.resources.costs[direction.foreign];
      const ownBefore = await this.browserFetch(direction.actor, `/api/proxy/cost-decisions/${ownCost.id}`, {
        pathId: id,
        expectedStatus: 200,
        label: `${key} owning cost baseline`,
      });
      const forbidden = [otherCost.id, otherCost.filename, this.resources.notifications[direction.foreign].title, this.resources.notifications[direction.foreign].body];
      const read = await this.opaquePair(id, direction.actor, `${key} cost read`, `/api/proxy/cost-decisions/${otherCost.id}`, `/api/proxy/cost-decisions/${ghost}`, { forbidden });
      const mutate = await this.opaquePair(id, direction.actor, `${key} cost approve`, `/api/proxy/cost-decisions/${otherCost.id}/approve`, `/api/proxy/cost-decisions/${ghost}/approve`, { method: "POST", data: { note: `foreign-${this.tag}` }, forbidden });
      const download = await this.opaquePair(id, direction.actor, `${key} cost PDF`, `/api/proxy/cost-decisions/${otherCost.id}/pdf`, `/api/proxy/cost-decisions/${ghost}/pdf`, { forbidden });
      const ownAfter = await this.browserFetch(direction.actor, `/api/proxy/cost-decisions/${ownCost.id}`, {
        pathId: id,
        expectedStatus: 200,
        label: `${key} owning cost after foreign probes`,
      });
      this.equal(id, `${key} owning cost unchanged`, ownAfter.body, ownBefore.body);
      costOutcomes[key] = { read, mutate, download, ownBefore: ownBefore.body, ownAfter: ownAfter.body };

      const foreignNotification = this.resources.notifications[direction.foreign];
      const unknownNotification = ghost;
      const notifForbidden = [foreignNotification.id, foreignNotification.title, foreignNotification.body];
      const readNotification = await this.opaquePair(id, direction.actor, `${key} notification read`, `/api/proxy/notifications/${foreignNotification.id}/read`, `/api/proxy/notifications/${unknownNotification}/read`, { method: "POST", data: {}, forbidden: notifForbidden });
      const dismissNotification = await this.opaquePair(id, direction.actor, `${key} notification dismiss`, `/api/proxy/notifications/${foreignNotification.id}/dismiss`, `/api/proxy/notifications/${unknownNotification}/dismiss`, { method: "POST", data: {}, forbidden: notifForbidden });
      const ownNotifications = await this.notificationList(direction.actor, { id, label: `${key} owning notification list` });
      this.equal(id, `${key} notification list excludes foreign id`, ownNotifications.body.notifications.some((item) => item.id === foreignNotification.id), false);
      notificationOutcomes[key] = { readNotification, dismissNotification, ownCount: ownNotifications.body.notifications.length };

      libraryOutcomes[key] = {};
      for (const library of LIBRARIES) {
        const ownDraft = this.resources.drafts[direction.own][library.key];
        const otherDraft = this.resources.drafts[direction.foreign][library.key];
        const ownDraftBefore = await this.browserFetch(direction.actor, `/api/proxy/${library.path}/${ownDraft.id}`, {
          pathId: id,
          expectedStatus: 200,
          label: `${key} owning ${library.key} baseline`,
        });
        const readDraft = await this.opaquePair(id, direction.actor, `${key} ${library.key} read`, `/api/proxy/${library.path}/${otherDraft.id}`, `/api/proxy/${library.path}/2147483647`, { forbidden: [String(otherDraft.id), this.tag] });
        const publishDraft = await this.opaquePair(id, direction.actor, `${key} ${library.key} publish`, `/api/proxy/${library.path}/${otherDraft.id}/publish`, `/api/proxy/${library.path}/2147483647/publish`, { method: "POST", data: {}, forbidden: [String(otherDraft.id), this.tag] });
        const ownDraftAfter = await this.browserFetch(direction.actor, `/api/proxy/${library.path}/${ownDraft.id}`, {
          pathId: id,
          expectedStatus: 200,
          label: `${key} owning ${library.key} after foreign probes`,
        });
        this.equal(id, `${key} owning ${library.key} unchanged`, ownDraftAfter.body, ownDraftBefore.body);
        libraryOutcomes[key][library.key] = { read: readDraft, publish: publishDraft, ownStatus: ownDraftAfter.body?.status };
      }
    }

    const viewerDismissed = await this.notificationList(viewer, { dismissed: true, id, label: "viewer A dismissed state after all foreign probes" });
    const viewerAState = viewerDismissed.body.notifications.find((item) => item.id === this.resources.notifications.A.id);
    this.truth(id, "foreign probes preserve viewer A dismissed state", Boolean(viewerAState?.is_dismissed && viewerAState?.read_at && viewerAState?.dismissed_at));
    this.equal(id, "foreign UI detail status", foreignUi.status, 404);

    return {
      observed: {
        url: viewer.page.url(),
        visible: ["Cost decision not found"],
        persisted: { costs: costOutcomes, libraries: libraryOutcomes, notifications: notificationOutcomes, viewerAState },
        numeric: { directions: directions.length, costOperationsPerDirection: 3, libraryKinds: LIBRARIES.length, notificationOperationsPerDirection: 2, foreignUiStatus: foreignUi.status },
        authorization: { "A->B": "all known foreign and unknown probes returned opaque 404", "B->A": "all known foreign and unknown probes returned opaque 404", markerLeaks: 0 },
        recovery: "After every bidirectional read/mutate/download probe, each owner re-read unchanged own resources and the viewer retained the exact dismissed notification state.",
      },
      screenshot: visual.screenshot,
      visuals: [visual],
    };
  }

  async runPath(id, fn) {
    const started = Date.now();
    this.activePathId = id;
    try {
      const result = await fn();
      invariant(this.assertions[id].length > 0, `${id} emitted no field-level assertions`);
      invariant(this.visualSteps[id].length > 0, `${id} emitted no real screenshot evidence`);
      this.pathResults[id] = result;
      this.steps.push({ id, status: "PASS", durationMs: Date.now() - started });
    } catch (error) {
      const message = error instanceof Error ? error.stack || error.message : String(error);
      this.defects.push({ id, kind: "path-defect", message });
      this.steps.push({ id, status: "FAIL", durationMs: Date.now() - started, error: message });
    } finally {
      await Promise.all(Object.values(this.identities).map((actor) => actor.page.waitForTimeout(50).catch(() => {})));
      this.activePathId = "SETUP";
    }
  }

  buildGoldenPaths(diagnostics) {
    const goldenPaths = {};
    for (const id of REQUIRED_IDS) {
      const meta = PATH_META[id];
      const result = this.pathResults[id];
      const pathDefect = this.defects.find((item) => item.id === id);
      const pathConsoleErrors = diagnostics.unexpectedConsoleErrors.filter((item) => item.pathId === id);
      const pathRequestFailures = diagnostics.unexpectedRequestFailures.filter((item) => item.pathId === id);
      const visuals = this.visualSteps[id];
      goldenPaths[id] = makeGoldenPathEvidence({
        id,
        status: result && !pathDefect && pathConsoleErrors.length === 0 && pathRequestFailures.length === 0 ? "PASS" : "FAIL",
        persona: meta.persona,
        preconditions: [...meta.preconditions],
        actions: [...meta.actions],
        observed: result?.observed || {
          url: this.config.appUrl,
          visible: [`Path failed before complete evidence: ${pathDefect?.message || "setup blocker"}`],
          persisted: "not-observed",
          numeric: "not-observed",
          authorization: "not-observed",
          recovery: "not-observed",
        },
        screenshot: result?.screenshot || visuals.at(-1)?.screenshot || "",
        visualSteps: visuals,
        consoleErrors: pathConsoleErrors,
        requestFailures: pathRequestFailures,
        assertions: this.assertions[id],
      });
    }
    return goldenPaths;
  }

  markdown(report) {
    const rows = REQUIRED_IDS.map((id) => {
      const evidence = report.releaseEvidence.goldenPaths[id];
      const result = report.releaseEvidence.validation.byId[id];
      return `| ${result.valid ? "PASS" : "FAIL"} | ${id} | ${evidence.assertions.length} | ${evidence.visualSteps.length} | ${evidence.screenshot || "—"} |`;
    }).join("\n");
    const issues = [...report.blockers, ...report.defects].map((item) => `- ${item.id || item.kind}: ${String(item.message).replaceAll("\n", " ")}`).join("\n") || "- none";
    return `# Role and notification real-browser evidence\n\n` +
      `- Status: ${report.status}\n` +
      `- Run: ${report.runId}\n` +
      `- Build: \`${report.buildIdentity.gitHead}\` / \`${report.buildIdentity.buildId}\`\n` +
      `- Build dirty: ${report.buildIdentity.gitDirty}\n` +
      `- Structured schema-v2 evidence: ${report.releaseEvidence.validation.valid}/${report.releaseEvidence.validation.total}\n` +
      `- Unexpected HTTP errors: ${report.diagnostics.unexpectedHttpErrors.length}\n` +
      `- Missing expected HTTP errors: ${report.diagnostics.missingExpectedHttpErrors.length}\n` +
      `- Unexpected console errors: ${report.diagnostics.unexpectedConsoleErrors.length}\n` +
      `- Unexpected request failures: ${report.diagnostics.unexpectedRequestFailures.length}\n\n` +
      `| Result | Path | Assertions | Visual captures | Primary screenshot |\n| --- | --- | ---: | ---: | --- |\n${rows}\n\n` +
      `## Blockers and defects\n\n${issues}\n`;
  }

  async finish() {
    await Promise.all(Object.values(this.identities).map((actor) => actor.page.waitForTimeout(100).catch(() => {})));
    const diagnostics = this.diagnostics.finalize();
    const goldenPaths = this.buildGoldenPaths(diagnostics);
    const validation = validateGoldenPathMap(REQUIRED_IDS, goldenPaths);
    const buildIdentity = captureBuildIdentity(repoRoot);
    const buildBinding = {
      startGitHead: this.buildIdentityAtStart?.gitHead || null,
      finalGitHead: buildIdentity.gitHead,
      startBuildId: this.buildIdentityAtStart?.buildId || null,
      finalBuildId: buildIdentity.buildId,
      sameGitHead: this.buildIdentityAtStart?.gitHead === buildIdentity.gitHead,
      sameBuildId: this.buildIdentityAtStart?.buildId === buildIdentity.buildId,
      dirtyAtStart: this.buildIdentityAtStart?.gitDirty ?? null,
      dirtyAtFinish: buildIdentity.gitDirty,
    };
    const oracle = evaluateRunOracle({
      requiredIds: REQUIRED_IDS,
      goldenPaths,
      validation,
      diagnostics,
      buildBinding,
      blockers: this.blockers,
      defects: this.defects,
      steps: this.steps,
    });
    const finishedAt = Date.now();
    const report = {
      schemaVersion: 2,
      suite: "role-notification-browser",
      runId: this.config.runId,
      status: oracle.pass ? "PASS" : "FAIL",
      startedAt: new Date(this.startedAt).toISOString(),
      finishedAt: new Date(finishedAt).toISOString(),
      durationMs: finishedAt - this.startedAt,
      runtime: {
        appUrl: this.config.appUrl,
        apiUrl: this.config.apiUrl,
        fixtureTarget: this.fixtureTarget || null,
        localFixtureProvisioning: true,
        externalSaasRequired: false,
        servicePreflight: this.servicePreflight || null,
      },
      buildIdentityAtStart: this.buildIdentityAtStart || null,
      buildIdentity,
      buildBinding,
      fixtureBinding: this.seed ? {
        tag: this.tag,
        organizations: Object.fromEntries(Object.entries(this.seed.orgs).map(([key, value]) => [key, { id: value.id, name: value.name }])),
        personas: Object.fromEntries(Object.entries(this.seed.people).map(([key, value]) => [key, { id: value.id, email: value.email, platformRole: value.platform_role, orgRole: value.org_role }])),
        notifications: this.seed.notifications,
        costs: this.resources.costs,
        drafts: Object.fromEntries(Object.entries(this.resources.drafts).map(([org, drafts]) => [org, Object.fromEntries(Object.entries(drafts).map(([key, value]) => [key, { id: value.id, path: value.path }]))])),
        cube: { path: this.config.cubePath, bytes: this.cubeBytes?.length || 0, sha256: this.cubeBytes ? sha256(this.cubeBytes) : null },
      } : null,
      steps: this.steps,
      blockers: this.blockers,
      defects: this.defects,
      skips: [],
      diagnostics,
      releaseEvidence: {
        schemaVersion: 2,
        goldenPaths,
        validation,
        buildBinding,
        oracle,
      },
      artifacts: this.config.artifacts,
    };
    await mkdir(this.config.outputRoot, { recursive: true });
    await writeFile(this.config.artifacts.json, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    await writeFile(this.config.artifacts.markdown, this.markdown(report), "utf8");
    return report;
  }

  async close() {
    await Promise.all(this.contexts.map((context) => context.close().catch(() => {})));
    await this.browser?.close().catch(() => {});
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(usage());
    return;
  }
  const config = { ...runtimeConfig(), headed: options.headed };
  const runner = new RoleNotificationBrowserRunner(config);
  let report;
  try {
    await runner.init();
    await runner.preflight();
    await runner.provisionFixtures();
    await runner.setupLiveResources();
    await runner.runPath("VER-04", () => runner.runVer04());
    await runner.runPath("ROLE-01", () => runner.runRole01());
    await runner.runPath("ROLE-02", () => runner.runRole02());
    await runner.runPath("ROLE-03", () => runner.runRole03());
    await runner.runPath("ROLE-04", () => runner.runRole04());
  } catch (error) {
    const message = error instanceof Error ? error.stack || error.message : String(error);
    runner.blockers.push({ id: "RUNNER", kind: "setup-blocker", message });
    for (const id of REQUIRED_IDS) {
      if (!runner.steps.some((step) => step.id === id)) {
        runner.steps.push({ id, status: "FAIL", durationMs: 0, error: `Not executed because setup failed: ${message}` });
      }
    }
  } finally {
    try {
      report = await runner.finish();
    } catch (error) {
      process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
      process.exitCode = 1;
    }
    await runner.close();
  }
  if (!report) return;
  process.stdout.write(`${JSON.stringify({
    status: report.status,
    schemaVersion: report.schemaVersion,
    valid: report.releaseEvidence.validation.valid,
    total: report.releaseEvidence.validation.total,
    steps: report.steps,
    blockers: report.blockers,
    defects: report.defects,
    diagnostics: {
      unexpectedConsoleErrors: report.diagnostics.unexpectedConsoleErrors.length,
      unexpectedRequestFailures: report.diagnostics.unexpectedRequestFailures.length,
      unexpectedHttpErrors: report.diagnostics.unexpectedHttpErrors.length,
      missingExpectedHttpErrors: report.diagnostics.missingExpectedHttpErrors.length,
    },
    artifacts: report.artifacts,
  }, null, 2)}\n`);
  if (report.status !== "PASS") process.exitCode = 1;
}

const invokedAsScript = process.argv[1] && path.resolve(process.argv[1]) === __filename;
if (invokedAsScript) {
  await main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
