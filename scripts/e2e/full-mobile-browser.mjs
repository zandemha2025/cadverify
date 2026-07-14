#!/usr/bin/env node

/**
 * Full mobile/tablet human-simulation gate.
 *
 * This runner deliberately exercises the shipped UI instead of seeding browser
 * state or calling product mutations behind the page. It creates one account,
 * follows public and authenticated navigation, verifies a real tracked STEP
 * fixture, records a human disposition, proves the immutable record survives a
 * refresh at every supported viewport, and then exercises the adjacent product
 * entry points. Every outcome is schema v2. There is no exclusion flag and no
 * successful partial mode: missing or failed outcomes make the report fail.
 */

import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  captureVisualStep,
  makeGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";
import {
  assertTruthfulTerminalCase,
  dispositionForCost,
  isExpectedNextRscPrefetchAbort,
  waitForVerificationPipeline,
} from "./representative-cad-browser.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const requireFromFrontend = createRequire(new URL("../../frontend/package.json", import.meta.url));

export const OUTCOME_SCHEMA_VERSION = 2;

export const VIEWPORTS = Object.freeze([
  Object.freeze({ key: "375x812", width: 375, height: 812, kind: "mobile" }),
  Object.freeze({ key: "390x844", width: 390, height: 844, kind: "mobile" }),
  Object.freeze({ key: "768x1024", width: 768, height: 1024, kind: "tablet" }),
]);

const ALL_VIEWPORT_KEYS = Object.freeze(VIEWPORTS.map((viewport) => viewport.key));

export const REQUIRED_OUTCOME_DEFINITIONS = Object.freeze([
  Object.freeze({ id: "FULL-MOB-01", title: "public navigation", requiredViewportKeys: ALL_VIEWPORT_KEYS }),
  Object.freeze({ id: "FULL-MOB-02", title: "signup and Day Zero", requiredViewportKeys: Object.freeze(["375x812"]) }),
  Object.freeze({ id: "FULL-MOB-03", title: "every Verify section", requiredViewportKeys: ALL_VIEWPORT_KEYS }),
  Object.freeze({ id: "FULL-MOB-04", title: "Verify command palette", requiredViewportKeys: Object.freeze(["390x844"]) }),
  Object.freeze({ id: "FULL-MOB-05", title: "supported CAD terminal result", requiredViewportKeys: Object.freeze(["390x844"]) }),
  Object.freeze({ id: "FULL-MOB-06", title: "disposition refresh and reopen", requiredViewportKeys: ALL_VIEWPORT_KEYS }),
  Object.freeze({ id: "FULL-MOB-07", title: "Design Studio fallback and handoff", requiredViewportKeys: Object.freeze(["768x1024"]) }),
  Object.freeze({ id: "FULL-MOB-08", title: "history", requiredViewportKeys: Object.freeze(["375x812"]) }),
  Object.freeze({ id: "FULL-MOB-09", title: "notifications", requiredViewportKeys: Object.freeze(["390x844"]) }),
  Object.freeze({ id: "FULL-MOB-10", title: "organization and settings", requiredViewportKeys: Object.freeze(["768x1024"]) }),
  Object.freeze({ id: "FULL-MOB-11", title: "batch entry", requiredViewportKeys: Object.freeze(["375x812"]) }),
  Object.freeze({ id: "FULL-MOB-12", title: "reconstruction capability boundary", requiredViewportKeys: Object.freeze(["390x844"]) }),
  Object.freeze({ id: "FULL-MOB-13", title: "logout and login recovery", requiredViewportKeys: Object.freeze(["768x1024"]) }),
]);

export const REQUIRED_OUTCOME_IDS = Object.freeze(
  REQUIRED_OUTCOME_DEFINITIONS.map((definition) => definition.id),
);

export const PUBLIC_NAV_TARGETS = Object.freeze([
  Object.freeze({ label: "Method", path: "/method", signal: /method|geometry/i }),
  Object.freeze({ label: "Platform", path: "/platform", signal: /platform|verification|decision layer/i }),
  Object.freeze({ label: "Teams", path: "/teams", signal: /teams|sourcing|engineering/i }),
  Object.freeze({ label: "Security", path: "/security", signal: /security|CAD/i }),
  Object.freeze({ label: "Developers", path: "/developers", signal: /developers|API/i }),
  Object.freeze({ label: "Company", path: "/company", signal: /company|pilot|ProofShape/i }),
]);

export const VERIFY_SECTIONS = Object.freeze([
  Object.freeze({ key: "home", label: "Home", requiredVisible: "Good morning.", heading: "Good morning." }),
  Object.freeze({ key: "verify", label: "Verify", requiredVisible: "Drop a part to begin the walk.", text: "Drop a part to begin the walk." }),
  Object.freeze({ key: "catalog", label: "Parts", requiredVisible: "Parts", heading: "Parts" }),
  Object.freeze({ key: "records", label: "Records", requiredVisible: "Records", heading: "Records" }),
  Object.freeze({ key: "programs", label: "Programs", requiredVisible: "Programs", heading: "Programs" }),
  Object.freeze({ key: "machines", label: "Your machines", requiredVisible: "Your machines", heading: "Your machines" }),
  Object.freeze({ key: "triage", label: "Triage", requiredVisible: "Triage at scale", heading: "Triage at scale" }),
  Object.freeze({ key: "calibration", label: "Calibration & truth", requiredVisible: "Calibration & truth", heading: "Calibration & truth" }),
]);

export const TEMPORARY_BUSY_COPY = Object.freeze([
  "Verification is running.",
  "Verification is temporarily busy.",
  "Cost history is temporarily unavailable. Retry shortly.",
  "Reading current states...",
  "Submitting…",
  "Uploading…",
  "Generating real CAD",
  "Could not load progress",
]);

const UNEXPECTED_FAILURE_COPY = /(?:couldn[’']?t load|could not load|failed to load|request failed|network error|health endpoint unreachable|temporarily (?:busy|unavailable)|retry shortly)/i;
const TRANSIENT_COPY = /(?:\b(?:loading|computing|submitting|uploading|preparing|checking|analy[sz]ing)[^\n]{0,48}(?:…|\.\.\.)|Generating real CAD|Reading current states\.\.\.|Verification is running\.)/i;
const BUILD_ENV_KEYS = Object.freeze([
  "E2E_BUILD_ID",
  "PROOFSHAPE_BUILD_ID",
  "VERCEL_GIT_COMMIT_SHA",
  "GITHUB_SHA",
  "CI_COMMIT_SHA",
  "NEXT_PUBLIC_BUILD_SHA",
]);

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function slug(value) {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

function unique(values) {
  return [...new Set(values)];
}

function pathnameOf(rawUrl) {
  try {
    return new URL(rawUrl).pathname;
  } catch {
    return rawUrl;
  }
}

function isResponse(response, method, pathname) {
  return response.request().method() === method && pathnameOf(response.url()) === pathname;
}

async function responseJson(response, label) {
  try {
    return await response.json();
  } catch (error) {
    const body = await response.text().catch(() => "");
    throw new Error(`${label} did not return JSON: ${body.slice(0, 500)} (${error.message})`);
  }
}

async function browserJson(page, method, pathname) {
  return page.evaluate(async ({ requestMethod, requestPath }) => {
    const response = await fetch(requestPath, {
      method: requestMethod,
      credentials: "same-origin",
      cache: "no-store",
    });
    const text = await response.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { invalid_json: true, text: text.slice(0, 500) };
    }
    return { status: response.status, body };
  }, { requestMethod: method, requestPath: pathname });
}

function assertion(name, expected, actual, pass = Object.is(expected, actual)) {
  return { name, expected, actual, pass };
}

function sameStringSet(left, right) {
  return JSON.stringify(unique(left).sort()) === JSON.stringify(unique(right).sort());
}

export function terminalBlockersFromSnapshot(snapshot) {
  const blockers = [];
  for (const field of ["ariaBusyCount", "skeletonCount", "loadingIndicatorCount"]) {
    if (Number(snapshot?.[field] || 0) > 0) blockers.push(`${field}=${snapshot[field]}`);
  }
  const text = typeof snapshot?.text === "string" ? snapshot.text : "";
  const transient = text.match(TRANSIENT_COPY)?.[0];
  const failure = text.match(UNEXPECTED_FAILURE_COPY)?.[0];
  if (transient) blockers.push(`transient copy: ${transient}`);
  if (failure) blockers.push(`failure copy: ${failure}`);
  return blockers;
}

export function horizontalOverflowResult(metrics, tolerance = 1) {
  const viewportWidth = Number(metrics?.viewportWidth || 0);
  const documentScrollWidth = Number(metrics?.documentScrollWidth || 0);
  const bodyScrollWidth = Number(metrics?.bodyScrollWidth || 0);
  const maxScrollWidth = Math.max(documentScrollWidth, bodyScrollWidth);
  return {
    pass: viewportWidth > 0 && maxScrollWidth <= viewportWidth + tolerance,
    viewportWidth,
    documentScrollWidth,
    bodyScrollWidth,
    overflowPx: Math.max(0, maxScrollWidth - viewportWidth),
  };
}

export function expectedServedBuildId(appUrl, identity, env = process.env) {
  const explicitKey = BUILD_ENV_KEYS.find((key) => String(env[key] || "").trim());
  if (explicitKey) return { buildId: String(env[explicitKey]).trim(), source: explicitKey };
  const hostname = new URL(appUrl).hostname;
  if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1" || hostname === "[::1]") {
    invariant(identity?.gitHead, "local build identity is missing gitHead");
    return { buildId: identity.gitHead, source: "local-git-head" };
  }
  throw new Error("A remote APP_URL requires E2E_BUILD_ID (or another supported build-id environment variable).");
}

export function isExpectedRequestFailure(item, appUrl) {
  return isExpectedNextRscPrefetchAbort(item, appUrl);
}

function visualViewportKeys(visualSteps) {
  return unique((visualSteps || []).map((step) => step?.viewportKey).filter(Boolean));
}

export function makeOutcomeRecord({
  definition,
  persona,
  preconditions,
  actions,
  observed,
  visualSteps,
  consoleErrors = [],
  requestFailures = [],
  unexpectedHttpErrors = [],
  assertions = [],
}) {
  invariant(definition?.id, "outcome definition is missing an id");
  invariant(Array.isArray(visualSteps) && visualSteps.length > 0, `${definition.id} has no visual steps`);
  const viewportKeys = visualViewportKeys(visualSteps);
  const evidence = makeGoldenPathEvidence({
    id: definition.id,
    status: "PASS",
    persona,
    preconditions,
    actions,
    observed,
    screenshot: visualSteps.at(-1).screenshot,
    visualSteps,
    consoleErrors,
    requestFailures,
    assertions: [
      ...assertions,
      assertion("zero unexpected console errors", 0, consoleErrors.length),
      assertion("zero unexpected request failures", 0, requestFailures.length),
      assertion("zero unexpected HTTP failures", 0, unexpectedHttpErrors.length),
      assertion(
        "required viewport evidence",
        definition.requiredViewportKeys.join(","),
        viewportKeys.join(","),
        sameStringSet(definition.requiredViewportKeys, viewportKeys),
      ),
    ],
  });
  return {
    ...evidence,
    schemaVersion: OUTCOME_SCHEMA_VERSION,
    title: definition.title,
    viewportKeys,
    unexpectedHttpErrors,
  };
}

export function validateOutcomeMap(outcomes, definitions = REQUIRED_OUTCOME_DEFINITIONS) {
  const requiredIds = definitions.map((definition) => definition.id);
  const common = validateGoldenPathMap(requiredIds, outcomes);
  const problems = [...common.problems];
  for (const definition of definitions) {
    const outcome = outcomes?.[definition.id];
    if (outcome?.schemaVersion !== OUTCOME_SCHEMA_VERSION) {
      problems.push({ id: definition.id, field: "schemaVersion", expected: OUTCOME_SCHEMA_VERSION, actual: outcome?.schemaVersion ?? null });
    }
    if (outcome?.status !== "PASS") {
      problems.push({ id: definition.id, field: "status", expected: "PASS", actual: outcome?.status ?? null });
    }
    if (!sameStringSet(outcome?.viewportKeys || [], definition.requiredViewportKeys)) {
      problems.push({
        id: definition.id,
        field: "viewportKeys",
        expected: definition.requiredViewportKeys,
        actual: outcome?.viewportKeys ?? null,
      });
    }
    if (!Array.isArray(outcome?.unexpectedHttpErrors) || outcome.unexpectedHttpErrors.length !== 0) {
      problems.push({ id: definition.id, field: "unexpectedHttpErrors", expected: [], actual: outcome?.unexpectedHttpErrors ?? null });
    }
  }
  const deduped = [];
  const seen = new Set();
  for (const problem of problems) {
    const key = JSON.stringify(problem);
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(problem);
    }
  }
  const validIds = requiredIds.filter((id) => !deduped.some((problem) => problem.id === id));
  return {
    total: requiredIds.length,
    valid: validIds.length,
    byId: common.byId,
    problems: deduped,
  };
}

function failedOutcomeRecord(definition, error, screenshot, viewportKey, diagnostics) {
  return {
    schemaVersion: OUTCOME_SCHEMA_VERSION,
    id: definition.id,
    title: definition.title,
    mode: "browser",
    status: "FAIL",
    persona: "human browser operator",
    preconditions: ["The full mobile browser gate was running against the configured application build."],
    actions: ["Attempted the required browser journey without bypassing the failed assertion."],
    observed: {
      url: diagnostics.url || "not-reached",
      visible: [error.message],
      persisted: "not proven because the journey failed",
      numeric: "not proven because the journey failed",
      authorization: "not proven because the journey failed",
      recovery: "No assertion was weakened; the failure is recorded as a defect.",
    },
    screenshot,
    visualProof: "NOT_PROVEN",
    visualSteps: [],
    viewportKeys: viewportKey ? [viewportKey] : [],
    consoleErrors: diagnostics.consoleErrors || [],
    requestFailures: diagnostics.requestFailures || [],
    unexpectedHttpErrors: diagnostics.unexpectedHttpErrors || [],
    assertions: [assertion("journey completed", true, false, false)],
    error: error.stack || error.message,
  };
}

class FullMobileBrowserRun {
  constructor(options = {}) {
    this.baseUrl = options.baseUrl || process.env.APP_URL || "http://localhost:3000";
    this.runId = options.runId || process.env.E2E_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");
    this.outputRoot = options.outputRoot || (process.env.E2E_ARTIFACT_DIR
      ? path.resolve(process.env.E2E_ARTIFACT_DIR)
      : path.join(repoRoot, ".gstack", "qa-reports"));
    this.screenshotDir = path.join(this.outputRoot, "screenshots", `full-mobile-browser-${this.runId}`);
    this.reportPath = path.join(this.outputRoot, `full-mobile-browser-${this.runId}.json`);
    this.markdownPath = path.join(this.outputRoot, `qa-report-full-mobile-browser-${this.runId}.md`);
    this.headed = options.headed === true;
    this.actionTimeoutMs = Number(process.env.FULL_MOBILE_ACTION_TIMEOUT_MS || 20_000);
    this.cadTimeoutMs = Number(process.env.FULL_MOBILE_CAD_TIMEOUT_MS || 150_000);
    this.settleTimeoutMs = Number(process.env.FULL_MOBILE_SETTLE_TIMEOUT_MS || 30_000);
    this.outcomes = {};
    this.steps = [];
    this.defects = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.expectedRequestAborts = [];
    this.unexpectedHttpErrors = [];
    this.pageErrors = [];
    this.screenshots = [];
    this.primaryTargetChecks = [];
    this.overflowChecks = [];
    this.settleChecks = [];
    this.servedBuildIds = new Set();
    this.currentOutcomeId = null;
    this.currentViewport = VIEWPORTS[0];
    this.startedAt = new Date().toISOString();
    this.buildIdentityAtStart = captureBuildIdentity(repoRoot);
    this.expectedBuild = expectedServedBuildId(this.baseUrl, this.buildIdentityAtStart);
    this.clientIp = process.env.E2E_CLIENT_IP || `198.51.100.${20 + (randomBytes(1)[0] % 200)}`;
    this.account = null;
    this.cadEvidence = null;
    this.dispositionEvidence = null;
    this.designEvidence = null;
    this.sessionRecoveryEvidence = null;
  }

  watchPage(page) {
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      this.consoleErrors.push({
        outcomeId: this.currentOutcomeId,
        url: page.url(),
        text: message.text(),
        location: message.location(),
      });
    });
    page.on("pageerror", (error) => {
      const item = { outcomeId: this.currentOutcomeId, url: page.url(), text: error.message };
      this.pageErrors.push(item);
      this.consoleErrors.push(item);
    });
    page.on("requestfailed", (request) => {
      const item = {
        outcomeId: this.currentOutcomeId,
        url: request.url(),
        method: request.method(),
        resourceType: request.resourceType(),
        error: request.failure()?.errorText || "request failed",
      };
      if (isExpectedRequestFailure(item, this.baseUrl)) this.expectedRequestAborts.push(item);
      else this.requestFailures.push(item);
    });
    page.on("response", (response) => {
      const build = response.headers()["x-proofshape-build"];
      if (build) this.servedBuildIds.add(build);
      if (response.status() >= 400) {
        this.unexpectedHttpErrors.push({
          outcomeId: this.currentOutcomeId,
          url: response.url(),
          method: response.request().method(),
          resourceType: response.request().resourceType(),
          status: response.status(),
        });
      }
    });
    page.on("crash", () => {
      this.consoleErrors.push({ outcomeId: this.currentOutcomeId, url: page.url(), text: "page crashed" });
    });
  }

  async init() {
    await mkdir(this.screenshotDir, { recursive: true });
    const { chromium } = requireFromFrontend("playwright-core");
    const launch = {
      headless: !this.headed,
      args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
    };
    try {
      this.browser = await chromium.launch({ ...launch, channel: "chrome" });
    } catch {
      this.browser = await chromium.launch(launch);
    }
    this.context = await this.browser.newContext({
      baseURL: this.baseUrl,
      viewport: { width: VIEWPORTS[0].width, height: VIEWPORTS[0].height },
      hasTouch: true,
      isMobile: false,
      reducedMotion: "reduce",
      acceptDownloads: true,
      extraHTTPHeaders: { "x-real-ip": this.clientIp },
    });
    this.page = await this.context.newPage();
    this.page.setDefaultTimeout(this.actionTimeoutMs);
    this.watchPage(this.page);
    await this.probeBuildIdentity();
  }

  async probeBuildIdentity() {
    const response = await this.context.request.get(new URL("/", this.baseUrl).toString(), {
      failOnStatusCode: false,
      timeout: this.actionTimeoutMs,
    });
    invariant(response.status() < 400, `build probe returned HTTP ${response.status()}`);
    const served = response.headers()["x-proofshape-build"] || "";
    invariant(served && served !== "unknown", "build probe omitted a concrete x-proofshape-build header");
    invariant(
      served === this.expectedBuild.buildId,
      `served build ${served} does not match expected ${this.expectedBuild.buildId} (${this.expectedBuild.source})`,
    );
    this.servedBuildIds.add(served);
  }

  offsets() {
    return {
      console: this.consoleErrors.length,
      requests: this.requestFailures.length,
      http: this.unexpectedHttpErrors.length,
    };
  }

  diagnosticsSince(offsets) {
    return {
      consoleErrors: this.consoleErrors.slice(offsets.console),
      requestFailures: this.requestFailures.slice(offsets.requests),
      unexpectedHttpErrors: this.unexpectedHttpErrors.slice(offsets.http),
    };
  }

  assertNoDiagnosticsSince(offsets, label) {
    const diagnostics = this.diagnosticsSince(offsets);
    invariant(diagnostics.consoleErrors.length === 0, `${label} produced console errors: ${JSON.stringify(diagnostics.consoleErrors)}`);
    invariant(diagnostics.requestFailures.length === 0, `${label} produced request failures: ${JSON.stringify(diagnostics.requestFailures)}`);
    invariant(diagnostics.unexpectedHttpErrors.length === 0, `${label} produced HTTP failures: ${JSON.stringify(diagnostics.unexpectedHttpErrors)}`);
    return diagnostics;
  }

  async setViewport(viewport) {
    this.currentViewport = viewport;
    await this.page.setViewportSize({ width: viewport.width, height: viewport.height });
  }

  assertDocumentResponse(response, label) {
    invariant(response, `${label} produced no document response`);
    invariant(response.status() < 400, `${label} returned HTTP ${response.status()}`);
    const served = response.headers()["x-proofshape-build"] || "";
    invariant(served && served !== "unknown", `${label} omitted a concrete x-proofshape-build header`);
    invariant(served === this.expectedBuild.buildId, `${label} served build ${served}, expected ${this.expectedBuild.buildId}`);
    this.servedBuildIds.add(served);
  }

  async goto(pathname, label = pathname) {
    const response = await this.page.goto(pathname, {
      waitUntil: "domcontentloaded",
      timeout: this.actionTimeoutMs,
    });
    this.assertDocumentResponse(response, label);
    await this.waitForSettled(label);
    await this.assertNoHorizontalOverflow(label);
    return response;
  }

  async reload(label) {
    const response = await this.page.reload({
      waitUntil: "domcontentloaded",
      timeout: this.actionTimeoutMs,
    });
    this.assertDocumentResponse(response, label);
    await this.waitForSettled(label);
    await this.assertNoHorizontalOverflow(label);
    return response;
  }

  async browserSnapshot() {
    return this.page.evaluate(() => {
      const visible = (element) => {
        if (!(element instanceof HTMLElement) && !(element instanceof SVGElement)) return false;
        const style = window.getComputedStyle(element);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
        if (element.hidden || element.getAttribute("aria-hidden") === "true") return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      const countVisible = (selector) => [...document.querySelectorAll(selector)].filter(visible).length;
      return {
        text: (document.body?.innerText || "").replace(/\s+/g, " ").trim(),
        ariaBusyCount: countVisible('[aria-busy="true"]'),
        skeletonCount: countVisible('[data-skeleton], [class*="skeleton" i], [class~="animate-pulse"]'),
        loadingIndicatorCount: countVisible('[data-loading="true"], [data-state="loading"], [aria-label*="loading" i], [class~="animate-spin"]'),
      };
    });
  }

  async waitForSettled(label) {
    const deadline = Date.now() + this.settleTimeoutMs;
    let lastSnapshot = null;
    let cleanObservations = 0;
    while (Date.now() < deadline) {
      lastSnapshot = await this.browserSnapshot();
      const blockers = terminalBlockersFromSnapshot(lastSnapshot);
      if (blockers.length === 0) {
        cleanObservations += 1;
        if (cleanObservations >= 2) {
          this.settleChecks.push({ label, viewport: this.currentViewport.key, pass: true });
          return lastSnapshot;
        }
      } else {
        cleanObservations = 0;
      }
      await this.page.waitForTimeout(175);
    }
    const blockers = terminalBlockersFromSnapshot(lastSnapshot);
    this.settleChecks.push({ label, viewport: this.currentViewport.key, pass: false, blockers });
    throw new Error(`${label} did not settle: ${blockers.join("; ") || "unknown busy state"}`);
  }

  async assertNoHorizontalOverflow(label) {
    const metrics = await this.page.evaluate(() => ({
      viewportWidth: window.innerWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body?.scrollWidth || 0,
    }));
    const result = horizontalOverflowResult(metrics);
    this.overflowChecks.push({ label, viewport: this.currentViewport.key, ...result });
    invariant(result.pass, `${label} has ${result.overflowPx}px horizontal overflow at ${this.currentViewport.key}: ${JSON.stringify(result)}`);
    return result;
  }

  async assertNoElementOverlap(first, second, label) {
    const [firstBox, secondBox] = await Promise.all([
      first.first().boundingBox(),
      second.first().boundingBox(),
    ]);
    invariant(firstBox && secondBox, `${label} could not measure both visible elements`);
    const horizontal = Math.min(firstBox.x + firstBox.width, secondBox.x + secondBox.width) -
      Math.max(firstBox.x, secondBox.x);
    const vertical = Math.min(firstBox.y + firstBox.height, secondBox.y + secondBox.height) -
      Math.max(firstBox.y, secondBox.y);
    invariant(
      horizontal <= 0 || vertical <= 0,
      `${label} overlaps by ${Math.round(horizontal)}×${Math.round(vertical)}px`,
    );
  }

  async assertPrimaryTarget(locator, label) {
    const target = locator.first();
    await target.waitFor({ state: "visible", timeout: this.actionTimeoutMs });
    await target.scrollIntoViewIfNeeded();
    const box = await target.boundingBox();
    invariant(box && box.width > 0 && box.height > 0, `${label} has no visible hit target`);
    const viewport = this.page.viewportSize();
    invariant(viewport, `${label} has no active viewport`);
    invariant(
      box.x >= -1 && box.y >= -1 && box.x + box.width <= viewport.width + 1 && box.y + box.height <= viewport.height + 1,
      `${label} is not fully visible at ${this.currentViewport.key}: ${JSON.stringify({ box, viewport })}`,
    );
    invariant(!(await target.isDisabled().catch(() => false)), `${label} is disabled`);
    await target.click({ trial: true, timeout: this.actionTimeoutMs });
    await target.focus();
    const focused = await target.evaluate((element) => element === document.activeElement || element.contains(document.activeElement));
    invariant(focused, `${label} could not receive focus`);
    const check = { label, viewport: this.currentViewport.key, visible: true, clickable: true, focusable: true };
    this.primaryTargetChecks.push(check);
    return target;
  }

  async clickPrimary(locator, label) {
    const target = await this.assertPrimaryTarget(locator, label);
    await target.click();
    return target;
  }

  async fillPrimary(locator, value, label) {
    const target = await this.assertPrimaryTarget(locator, label);
    await target.fill(value);
    invariant((await target.inputValue()) === value, `${label} did not retain the entered value`);
    return target;
  }

  async selectPrimary(locator, value, label) {
    const target = await this.assertPrimaryTarget(locator, label);
    await target.selectOption(value);
    invariant((await target.inputValue()) === value, `${label} did not select ${value}`);
    return target;
  }

  async captureStage(outcomeId, stage, requiredVisible, { terminal = true, fullPage = false } = {}) {
    await this.waitForSettled(`${outcomeId} ${stage}`);
    await this.assertNoHorizontalOverflow(`${outcomeId} ${stage}`);
    const screenshot = path.join(this.screenshotDir, `${outcomeId.toLowerCase()}-${slug(stage)}.png`);
    const visualStep = await captureVisualStep(this.page, {
      id: outcomeId,
      stage,
      terminal,
      requiredVisible,
      forbiddenVisible: TEMPORARY_BUSY_COPY,
      screenshot,
      fullPage,
    });
    const screenshotStat = await stat(screenshot);
    invariant(screenshotStat.size > 0, `${outcomeId} ${stage} screenshot is empty`);
    this.screenshots.push({ outcomeId, stage, viewport: this.currentViewport.key, path: screenshot, bytes: screenshotStat.size });
    return { ...visualStep, viewportKey: this.currentViewport.key };
  }

  async failureScreenshot(outcomeId) {
    if (!this.page || this.page.isClosed()) return null;
    const screenshot = path.join(
      this.screenshotDir,
      `${outcomeId.toLowerCase()}-failure-${slug(this.currentViewport?.key || "unknown")}.png`,
    );
    try {
      await this.page.screenshot({ path: screenshot, fullPage: false, animations: "disabled", caret: "initial" });
      const screenshotStat = await stat(screenshot);
      if (screenshotStat.size > 0) {
        this.screenshots.push({ outcomeId, stage: "failure", viewport: this.currentViewport?.key || null, path: screenshot, bytes: screenshotStat.size });
        return screenshot;
      }
    } catch {}
    return null;
  }

  async runOutcome(definition, work) {
    this.currentOutcomeId = definition.id;
    const offsets = this.offsets();
    const started = Date.now();
    try {
      const result = await work();
      const diagnostics = this.assertNoDiagnosticsSince(offsets, definition.title);
      const record = makeOutcomeRecord({
        definition,
        ...result,
        ...diagnostics,
      });
      const one = validateOutcomeMap({ [definition.id]: record }, [definition]);
      invariant(one.valid === 1, `${definition.id} schema-v2 outcome is invalid: ${JSON.stringify(one.problems)}`);
      this.outcomes[definition.id] = record;
      this.steps.push({ id: definition.id, title: definition.title, status: "PASS", durationMs: Date.now() - started, screenshot: record.screenshot });
      return record;
    } catch (caught) {
      const error = caught instanceof Error ? caught : new Error(String(caught));
      const screenshot = await this.failureScreenshot(definition.id);
      const diagnostics = this.diagnosticsSince(offsets);
      const url = this.page?.url?.() || "";
      this.outcomes[definition.id] = failedOutcomeRecord(
        definition,
        error,
        screenshot,
        this.currentViewport?.key || null,
        { ...diagnostics, url },
      );
      const defect = {
        id: definition.id,
        title: definition.title,
        severity: "release-blocking",
        viewport: this.currentViewport?.key || null,
        url,
        error: error.message,
        screenshot,
        diagnostics,
      };
      this.defects.push(defect);
      this.steps.push({ id: definition.id, title: definition.title, status: "FAIL", durationMs: Date.now() - started, screenshot, error: error.message });
      return null;
    } finally {
      this.currentOutcomeId = null;
    }
  }

  async clickPublicTarget(target) {
    const mobileToggle = this.page.getByLabel("Open site navigation");
    let link;
    if (await mobileToggle.isVisible().catch(() => false)) {
      await this.clickPrimary(mobileToggle, `open public navigation for ${target.label}`);
      link = this.page
        .getByRole("navigation", { name: "Mobile primary" })
        .getByRole("link", { name: target.label, exact: true });
    } else {
      link = this.page
        .getByRole("navigation", { name: "Primary" })
        .getByRole("link", { name: target.label, exact: true });
    }
    const destination = this.page.waitForURL((url) => url.pathname === target.path, { timeout: this.actionTimeoutMs });
    await this.clickPrimary(link, `public navigation target ${target.label}`);
    await destination;
    await this.waitForSettled(`public ${target.path}`);
    const text = await this.page.locator("body").innerText();
    invariant(target.signal.test(text), `${target.path} did not expose ${target.signal}`);
  }

  async runPublicNavigation(definition) {
    const visualSteps = [];
    for (const viewport of VIEWPORTS) {
      await this.setViewport(viewport);
      await this.goto("/", `public home ${viewport.key}`);
      for (const target of PUBLIC_NAV_TARGETS) {
        await this.clickPublicTarget(target);
        visualSteps.push(await this.captureStage(
          definition.id,
          `${viewport.key}-${slug(target.label)}`,
          [target.label, "ProofShape"],
        ));
      }
    }
    return {
      persona: "prospective manufacturing engineer using touch navigation",
      preconditions: ["No authenticated session exists.", "The public site is served by the expected build."],
      actions: ["Opened the responsive site menu.", "Clicked Method, Platform, Teams, Security, Developers, and Company at every required viewport."],
      observed: {
        url: this.page.url(),
        visible: PUBLIC_NAV_TARGETS.map((target) => target.label),
        persisted: { routes: PUBLIC_NAV_TARGETS.map((target) => target.path) },
        numeric: { routesPerViewport: PUBLIC_NAV_TARGETS.length, viewportCount: VIEWPORTS.length },
        authorization: { public: true, sessionRequired: false },
        recovery: "Each route remained reachable after repeated responsive client-side navigation.",
      },
      visualSteps,
      assertions: [
        assertion("public route count", PUBLIC_NAV_TARGETS.length, PUBLIC_NAV_TARGETS.length),
        assertion("responsive public viewport count", VIEWPORTS.length, visualViewportKeys(visualSteps).length),
      ],
    };
  }

  async runSignupDayZero(definition) {
    await this.setViewport(VIEWPORTS[0]);
    await this.goto("/signup", "signup");
    const email = `full-mobile-${Date.now()}-${process.pid}-${randomBytes(4).toString("hex")}@example.com`;
    const password = `FullMobile-${randomBytes(8).toString("hex")}-9a`;
    await this.fillPrimary(this.page.getByLabel("Email"), email, "signup email");
    await this.fillPrimary(this.page.getByLabel("Password"), password, "signup password");
    const signupResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/auth/signup"),
      { timeout: this.actionTimeoutMs },
    );
    await this.clickPrimary(this.page.getByRole("button", { name: /^Create account$/ }), "Create account");
    const signupResponse = await signupResponsePromise;
    invariant(signupResponse.status() === 200, `signup returned HTTP ${signupResponse.status()}`);
    await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: this.actionTimeoutMs });
    await this.page.getByText("DAY ZERO SETUP", { exact: true }).waitFor({ state: "visible", timeout: this.actionTimeoutMs });
    await this.waitForSettled("signup Day Zero home");

    const setupTarget = this.page.locator(".cv-verify-setup button:not([disabled])").first();
    await this.assertPrimaryTarget(setupTarget, "first actionable Day Zero target");

    // The signup route is a navigation-producing Next mutation. Chromium can
    // complete it and install the HttpOnly cookie even when CDP no longer
    // exposes that response body. Prove the account from authenticated,
    // in-page reads instead of treating a DevTools body-retention detail as a
    // product failure or falling back to Playwright's separate HTTP client.
    const orgResponse = await browserJson(this.page, "GET", "/api/proxy/orgs");
    invariant(orgResponse.status === 200, `organization context returned HTTP ${orgResponse.status}`);
    const orgBody = orgResponse.body;
    const activeOrg = orgBody?.organizations?.find((org) => org.is_active) ||
      orgBody?.organizations?.find((org) => org.org_id === orgBody?.active_org_id) || null;
    const memberResponse = await browserJson(this.page, "GET", "/api/proxy/orgs/members");
    invariant(memberResponse.status === 200, `organization members returned HTTP ${memberResponse.status}`);
    const ownMember = memberResponse.body?.members?.find((member) => member.email === email) || null;
    const userId = ownMember?.user_id;
    invariant(userId !== undefined && userId !== null, "authenticated member record omitted the stable user id");
    invariant(activeOrg?.org_id, "signup did not create an active organization id");
    invariant(activeOrg.org_role === "admin", `fresh signup org role was ${activeOrg?.org_role || "missing"}, expected admin`);

    await this.clickPrimary(this.page.getByRole("button", { name: "Account", exact: true }), "fresh account menu");
    const accountMenu = this.page.getByRole("menu");
    await accountMenu.getByText(email, { exact: true }).waitFor({ state: "visible" });
    const platformRole = (await accountMenu.getByText("analyst", { exact: true }).innerText()).trim();
    await this.page.keyboard.press("Escape");
    this.account = {
      email,
      password,
      userId,
      platformRole,
      orgId: activeOrg.org_id,
      orgRole: activeOrg.org_role,
    };
    const visualSteps = [await this.captureStage(definition.id, "375x812-day-zero", ["DAY ZERO SETUP", "Good morning."])];
    return {
      persona: "new organization administrator starting on a phone",
      preconditions: ["Password signup is enabled for the target environment.", "The browser has no prior session."],
      actions: ["Entered a unique email and strong password.", "Created the account through the real form.", "Inspected the live Day Zero organization checklist."],
      observed: {
        url: this.page.url(),
        visible: ["DAY ZERO SETUP", "Good morning."],
        persisted: { userId, orgId: activeOrg.org_id, email },
        numeric: { signupStatus: signupResponse.status(), enabledSetupTargets: await this.page.locator(".cv-verify-setup button:not([disabled])").count() },
        authorization: { platformRole: this.account.platformRole, orgRole: activeOrg.org_role },
        recovery: "The authenticated Verify home loaded from the newly issued session cookie.",
      },
      visualSteps,
      assertions: [
        assertion("signup HTTP status", 200, signupResponse.status()),
        assertion("fresh organization role", "admin", activeOrg.org_role),
        assertion("stable user id present", true, Boolean(userId)),
        assertion("stable organization id present", true, Boolean(activeOrg.org_id)),
      ],
    };
  }

  async navigateVerifySection(section) {
    const mobileSelect = this.page.getByRole("combobox", { name: "Verify workspace section" });
    if (await mobileSelect.isVisible().catch(() => false)) {
      await this.selectPrimary(mobileSelect, section.key, `Verify section ${section.label}`);
    } else {
      await this.clickPrimary(
        this.page.getByRole("button", { name: section.label, exact: true }),
        `Verify section ${section.label}`,
      );
    }
    if (section.heading) {
      await this.page.getByRole("heading", { name: section.heading, exact: true }).first().waitFor({ state: "visible", timeout: this.actionTimeoutMs });
    } else {
      await this.page.getByText(section.text, { exact: true }).first().waitFor({ state: "visible", timeout: this.actionTimeoutMs });
    }
    await this.waitForSettled(`Verify section ${section.label}`);
  }

  async runVerifySections(definition) {
    invariant(this.account, "signup did not establish the account required for Verify sections");
    const visualSteps = [];
    for (const viewport of VIEWPORTS) {
      await this.setViewport(viewport);
      await this.goto("/verify", `Verify shell ${viewport.key}`);
      for (const section of VERIFY_SECTIONS) {
        await this.navigateVerifySection(section);
        visualSteps.push(await this.captureStage(
          definition.id,
          `${viewport.key}-${slug(section.label)}`,
          [section.requiredVisible],
        ));
      }
    }
    return {
      persona: "authenticated manufacturing engineer moving across the Verify workspace",
      preconditions: ["A fresh admin account is authenticated.", "Organization reads have settled without an error state."],
      actions: ["Used the mobile section selector at phone widths.", "Used the tablet rail controls at 768 px.", "Opened all eight Verify sections."],
      observed: {
        url: this.page.url(),
        visible: VERIFY_SECTIONS.map((section) => section.requiredVisible),
        persisted: { sections: VERIFY_SECTIONS.map((section) => section.key) },
        numeric: { sectionCount: VERIFY_SECTIONS.length, viewportCount: VIEWPORTS.length, captures: visualSteps.length },
        authorization: { orgRole: this.account.orgRole, authenticated: true },
        recovery: "Every section remained reachable after repeatedly changing viewport and returning to /verify.",
      },
      visualSteps,
      assertions: [
        assertion("Verify section count", 8, VERIFY_SECTIONS.length),
        assertion("Verify section viewport captures", 24, visualSteps.length),
      ],
    };
  }

  async runVerifyCommandPalette(definition) {
    await this.setViewport(VIEWPORTS[1]);
    await this.goto("/verify", "Verify command palette");
    await this.navigateVerifySection(VERIFY_SECTIONS[0]);
    await this.clickPrimary(
      this.page.getByRole("button", { name: /Jump to a surface, action, or sample walkthrough/i }),
      "open Verify command palette",
    );
    const search = this.page.getByRole("textbox", { name: "Command palette search" });
    await this.fillPrimary(search, "triage", "Verify command palette search");
    await this.clickPrimary(this.page.getByRole("button", { name: /^Go to Triage/ }), "command palette Triage result");
    await this.page.getByRole("heading", { name: "Triage at scale", exact: true }).waitFor({ state: "visible" });
    const visualSteps = [await this.captureStage(definition.id, "390x844-triage-jump", ["Triage at scale"])];
    return {
      persona: "keyboard-and-touch power user on a phone",
      preconditions: ["The authenticated Verify Home surface is open."],
      actions: ["Opened the local Jump palette.", "Focused and searched for triage.", "Activated the filtered Go to Triage result."],
      observed: {
        url: this.page.url(),
        visible: ["Triage at scale"],
        persisted: "The palette changed the local Verify section without a document reload.",
        numeric: { queryLength: "triage".length, resultCount: 1 },
        authorization: { authenticated: true, orgRole: this.account.orgRole },
        recovery: "The destination remained usable after the palette closed.",
      },
      visualSteps,
      assertions: [assertion("palette destination", "Triage at scale", await this.page.getByRole("heading", { name: "Triage at scale", exact: true }).innerText())],
    };
  }

  async runSupportedCad(definition) {
    await this.setViewport(VIEWPORTS[1]);
    await this.goto("/verify", "supported CAD upload");
    await this.navigateVerifySection(VERIFY_SECTIONS[1]);
    const fixturePath = path.join(repoRoot, "backend", "tests", "assets", "cube.step");
    const fixtureBytes = await readFile(fixturePath);
    const fixtureSha256 = createHash("sha256").update(fixtureBytes).digest("hex");
    const input = this.page.getByTestId("verify-part-cad-input");
    await input.waitFor({ state: "attached" });
    const accept = (await input.getAttribute("accept")) || "";
    invariant(accept.toLowerCase().includes(".step"), "Verify CAD input does not advertise STEP support");
    await this.assertPrimaryTarget(
      this.page.getByRole("button", { name: "Verify a part", exact: true }),
      "Verify a part primary upload target",
    );

    const assemblyPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate/assembly"),
      { timeout: this.cadTimeoutMs },
    );
    const validationPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate"),
      { timeout: this.cadTimeoutMs },
    );
    const costPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate/cost"),
      { timeout: this.cadTimeoutMs },
    );
    const pipelinePromise = waitForVerificationPipeline(this.page, { timeoutMs: this.cadTimeoutMs });
    await input.setInputFiles(fixturePath);
    const [assemblyResponse, validationResponse, costResponse, pipeline] = await Promise.all([
      assemblyPromise,
      validationPromise,
      costPromise,
      pipelinePromise,
    ]);
    invariant(assemblyResponse.status() === 200, `STEP assembly classification returned HTTP ${assemblyResponse.status()}`);
    invariant(validationResponse.status() === 200, `STEP validation returned HTTP ${validationResponse.status()}`);
    invariant(costResponse.status() === 200, `STEP should-cost returned HTTP ${costResponse.status()}`);
    const [assembly, validation, cost] = await Promise.all([
      responseJson(assemblyResponse, "STEP assembly classification"),
      responseJson(validationResponse, "STEP validation"),
      responseJson(costResponse, "STEP should-cost"),
    ]);
    invariant(assembly.kind === "single_part" && assembly.part_count === 1, `cube.step was not classified as one part: ${JSON.stringify(assembly)}`);
    await this.page.getByText("What it really takes", { exact: true }).waitFor({ state: "visible", timeout: this.cadTimeoutMs });
    const openRecord = this.page.getByRole("button", { name: /^Open the record/ });
    await this.assertPrimaryTarget(openRecord, "Open the saved verification record");
    const visibleText = await this.page.locator("body").innerText();
    const fixture = {
      id: "FULL-MOBILE-CUBE",
      filename: "cube.step",
      support_status: "supported",
      expected_browser_outcome: "verified_and_saved",
    };
    const truth = assertTruthfulTerminalCase({ fixture, validation, cost, visibleText });
    invariant(/^[A-Z0-9]{10,}$/i.test(truth.savedDecisionId), `saved decision id is not stable-looking: ${truth.savedDecisionId}`);
    const visualSteps = [await this.captureStage(
      definition.id,
      "390x844-terminal",
      ["cube.step", "What it really takes", "Open the record"],
    )];
    this.cadEvidence = { fixture, fixturePath, fixtureSha256, assembly, validation, cost, truth, pipeline };
    return {
      persona: "manufacturing engineer verifying a supported STEP part on a phone",
      preconditions: ["backend/tests/assets/cube.step is the tracked supported fixture.", "The real Verify file input advertises STEP."],
      actions: ["Selected cube.step through the real file control.", "Observed the pipeline dialog appear and disappear.", "Inspected measured geometry, should-cost, provenance, and the saved record action."],
      observed: {
        url: this.page.url(),
        visible: ["cube.step", "What it really takes", "Open the record", "MEASURED"],
        persisted: { decisionId: truth.savedDecisionId, fixtureSha256 },
        numeric: { assemblyStatus: assemblyResponse.status(), validationStatus: validationResponse.status(), costStatus: costResponse.status(), ...truth.validationGeometry },
        authorization: { authenticated: true, orgId: this.account.orgId },
        recovery: "The pipeline reached a terminal saved result; no API-only completion was accepted.",
      },
      visualSteps,
      assertions: [
        assertion("pipeline appeared", true, pipeline.appeared),
        assertion("pipeline disappeared", true, pipeline.disappeared),
        assertion("assembly part count", 1, assembly.part_count),
        assertion("validation status", 200, validationResponse.status()),
        assertion("cost status", 200, costResponse.status()),
        assertion("durable decision id present", true, Boolean(truth.savedDecisionId)),
      ],
    };
  }

  async runDispositionPersistence(definition) {
    invariant(this.cadEvidence, "supported CAD outcome did not produce a decision to disposition");
    await this.setViewport(VIEWPORTS[1]);
    const { cost, truth, fixture } = this.cadEvidence;
    const expectedDisposition = dispositionForCost(cost);
    const disposition = this.page.getByTestId(`verify-disposition-${expectedDisposition.key}`);
    const dispositionResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "PUT", `/api/proxy/cost-decisions/${truth.savedDecisionId}/disposition`),
      { timeout: this.actionTimeoutMs },
    );
    await this.clickPrimary(disposition, `record ${expectedDisposition.label} disposition`);
    const dispositionResponse = await dispositionResponsePromise;
    invariant(dispositionResponse.status() === 200, `disposition returned HTTP ${dispositionResponse.status()}`);
    await this.page
      .getByTestId("verify-disposition-status")
      .filter({ hasText: `✓ ${expectedDisposition.label} — recorded` })
      .waitFor({ state: "visible", timeout: this.actionTimeoutMs });
    invariant((await disposition.getAttribute("aria-pressed")) === "true", "recorded disposition is not visibly selected");
    const visualSteps = [await this.captureStage(
      definition.id,
      "390x844-disposition-recorded",
      [expectedDisposition.label, "recorded", "Open the record"],
    )];

    const reopened = [];
    for (const viewport of VIEWPORTS) {
      await this.setViewport(viewport);
      await this.reload(`record refresh ${viewport.key}`);
      await this.navigateVerifySection(VERIFY_SECTIONS[3]);
      const recordButton = this.page.getByRole("button", { name: new RegExp(escapeRegExp(fixture.filename), "i") }).first();
      await recordButton.waitFor({ state: "visible", timeout: this.actionTimeoutMs });
      const detailResponsePromise = this.page.waitForResponse(
        (response) => isResponse(response, "GET", `/api/proxy/cost-decisions/${truth.savedDecisionId}`),
        { timeout: this.actionTimeoutMs },
      );
      await this.clickPrimary(recordButton, `open ${fixture.filename} record at ${viewport.key}`);
      const detailResponse = await detailResponsePromise;
      invariant(detailResponse.status() === 200, `record detail returned HTTP ${detailResponse.status()}`);
      const detail = await responseJson(detailResponse, `record detail ${viewport.key}`);
      invariant(detail.id === truth.savedDecisionId, `record id changed after refresh: ${detail.id}`);
      invariant(detail.filename === fixture.filename, `record filename changed after refresh: ${detail.filename}`);
      invariant(detail.user_disposition === expectedDisposition.key, `record disposition changed to ${detail.user_disposition}`);
      const summary = this.page.getByTestId("record-disposition-summary");
      await summary.getByText(expectedDisposition.label, { exact: true }).waitFor({ state: "visible" });
      const governanceLink = summary.locator(`a[href="/cost-decisions/${truth.savedDecisionId}"]`);
      await this.assertPrimaryTarget(governanceLink, `Open governance for ${truth.savedDecisionId}`);
      visualSteps.push(await this.captureStage(
        definition.id,
        `${viewport.key}-record-reopened`,
        [fixture.filename, expectedDisposition.label, "Open governance"],
      ));
      reopened.push({ viewport: viewport.key, id: detail.id, disposition: detail.user_disposition });
    }
    invariant(reopened.every((item) => item.id === truth.savedDecisionId), "one or more responsive reopens changed the persisted decision id");
    this.dispositionEvidence = {
      decisionId: truth.savedDecisionId,
      disposition: expectedDisposition.key,
      reopened,
    };
    return {
      persona: "decision owner recording and reopening a make-vs-buy outcome",
      preconditions: ["A terminal supported CAD result has a durable saved decision id."],
      actions: ["Selected the engine-compatible human disposition.", "Reloaded the browser at every viewport.", "Opened Records and the exact immutable decision each time."],
      observed: {
        url: this.page.url(),
        visible: [expectedDisposition.label, fixture.filename, "Open governance"],
        persisted: { decisionId: truth.savedDecisionId, disposition: expectedDisposition.key, reopened },
        numeric: { dispositionStatus: dispositionResponse.status(), reopenCount: reopened.length },
        authorization: { orgId: this.account.orgId, orgRole: this.account.orgRole },
        recovery: "Refresh destroyed the in-memory Verify result; Records rebuilt the exact id and disposition at all three viewports.",
      },
      visualSteps,
      assertions: [
        assertion("disposition status", 200, dispositionResponse.status()),
        assertion("responsive reopen count", VIEWPORTS.length, reopened.length),
        assertion("stable decision id across reopens", true, reopened.every((item) => item.id === truth.savedDecisionId)),
      ],
    };
  }

  async waitForDesignReady(name) {
    const ready = this.page.getByRole("button", { name: new RegExp(`${escapeRegExp(name)}\\s+Ready`, "i") }).first();
    await ready.waitFor({ state: "visible", timeout: this.cadTimeoutMs });
    await this.clickPrimary(ready, `open ready design ${name}`);
    await this.page.getByRole("heading", { name, exact: true }).waitFor({ state: "visible", timeout: this.actionTimeoutMs });
  }

  async runDesignStudio(definition) {
    await this.setViewport(VIEWPORTS[2]);
    await this.goto("/designs", "Design Studio");
    await this.page.getByRole("heading", { name: "ProofShape Design Studio", exact: true }).waitFor({ state: "visible" });
    invariant(await this.page.getByTestId("design-mutation-workspace").isVisible(), `Design Studio is read-only for fresh ${this.account?.orgRole || "unknown"} signup`);
    const designName = `Full mobile plate ${randomBytes(4).toString("hex")}`;
    await this.clickPrimary(this.page.getByRole("button", { name: "Mounting plate", exact: true }), "Mounting plate template");
    await this.fillPrimary(this.page.getByLabel("Design name"), designName, "Design name");
    await this.fillPrimary(this.page.getByLabel("Width"), "80", "Design width");
    await this.fillPrimary(this.page.getByLabel("Depth"), "50", "Design depth");
    await this.fillPrimary(this.page.getByLabel("Thickness"), "6", "Design thickness");
    const createResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/designs"),
      { timeout: this.actionTimeoutMs },
    );
    await this.clickPrimary(this.page.getByRole("button", { name: /^Generate design$/ }), "Generate design");
    const createResponse = await createResponsePromise;
    invariant(createResponse.status() === 202, `Design Studio create returned HTTP ${createResponse.status()}`);
    await this.waitForDesignReady(designName);
    await this.waitForSettled("Design Studio ready result");

    const preview = await this.page.evaluate(() => {
      const visible = (element) => {
        if (!(element instanceof HTMLElement)) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
      };
      const canvas = [...document.querySelectorAll("canvas")].find(visible);
      const fallback = [...document.querySelectorAll("body *")].find((element) =>
        visible(element) && element.textContent?.trim() === "Interactive 3D is unavailable in this browser."
      );
      return { canvasVisible: Boolean(canvas), fallbackVisible: Boolean(fallback) };
    });
    invariant(preview.canvasVisible || preview.fallbackVisible, "Design Studio exposed neither an interactive preview nor its explicit fallback");
    const previewMode = preview.canvasVisible ? "interactive" : "explicit-fallback";
    const verifyLink = this.page.getByRole("link", { name: /^Verify revision 1$/ });
    const href = await verifyLink.getAttribute("href");
    invariant(href, "Design Studio handoff omitted href");
    const handoffUrl = new URL(href, this.baseUrl);
    const designId = handoffUrl.searchParams.get("design");
    invariant(designId, "Design Studio handoff omitted stable design id");
    invariant(handoffUrl.searchParams.get("revision") === "1", "Design Studio handoff omitted revision=1");
    await this.assertPrimaryTarget(verifyLink, "Verify revision 1 handoff");
    const visualSteps = [await this.captureStage(
      definition.id,
      "768x1024-design-ready",
      [designName, "Ready", "Viewing revision 1"],
    )];

    const artifactPromise = this.page.waitForResponse(
      (response) => isResponse(response, "GET", `/api/proxy/designs/${designId}/revisions/1/download.step`),
      { timeout: this.cadTimeoutMs },
    );
    const assemblyPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate/assembly"),
      { timeout: this.cadTimeoutMs },
    );
    const validationPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate"),
      { timeout: this.cadTimeoutMs },
    );
    const costPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate/cost"),
      { timeout: this.cadTimeoutMs },
    );
    const pipelinePromise = waitForVerificationPipeline(this.page, { timeoutMs: this.cadTimeoutMs });
    const destination = this.page.waitForURL(
      (url) => url.pathname === "/verify" && url.searchParams.get("design") === designId && url.searchParams.get("revision") === "1",
      { timeout: this.actionTimeoutMs },
    );
    await this.clickPrimary(verifyLink, "Verify revision 1 handoff");
    await destination;
    const [artifactResponse, assemblyResponse, validationResponse, costResponse, pipeline] = await Promise.all([
      artifactPromise,
      assemblyPromise,
      validationPromise,
      costPromise,
      pipelinePromise,
    ]);
    invariant(artifactResponse.status() === 200, `design artifact import returned HTTP ${artifactResponse.status()}`);
    invariant(assemblyResponse.status() === 200, `design assembly classification returned HTTP ${assemblyResponse.status()}`);
    invariant(validationResponse.status() === 200, `design validation returned HTTP ${validationResponse.status()}`);
    invariant(costResponse.status() === 200, `design should-cost returned HTTP ${costResponse.status()}`);
    const [assembly, validation, cost] = await Promise.all([
      responseJson(assemblyResponse, "design assembly classification"),
      responseJson(validationResponse, "design validation"),
      responseJson(costResponse, "design should-cost"),
    ]);
    invariant(assembly.kind === "single_part" && assembly.part_count === 1, "generated plate did not re-enter Verify as one real part");
    await this.page.getByText("What it really takes", { exact: true }).waitFor({ state: "visible", timeout: this.cadTimeoutMs });
    const visibleText = await this.page.locator("body").innerText();
    const fixture = {
      id: "FULL-MOBILE-DESIGN-HANDOFF",
      filename: validation.filename,
      support_status: "supported",
      expected_browser_outcome: "verified_and_saved",
    };
    const truth = assertTruthfulTerminalCase({ fixture, validation, cost, visibleText });
    invariant(new URL(this.page.url()).searchParams.get("design") === designId, "Verify handoff changed the stable design id");
    // This capture intentionally forbids the ready-banner text "Verification is
    // running." at terminal state. If the product leaves that message behind,
    // it is a real defect and must not be dismissed or allowlisted by the gate.
    visualSteps.push(await this.captureStage(
      definition.id,
      "768x1024-verify-handoff-terminal",
      [validation.filename, "Imported", "What it really takes"],
    ));
    this.designEvidence = { designId, revision: 1, decisionId: truth.savedDecisionId, previewMode };
    return {
      persona: "design engineer generating safe parametric CAD on a tablet",
      preconditions: ["The fresh signup has an admin/analyst mutation role.", "Design Studio starts with a real allowlisted plate template."],
      actions: ["Generated an 80 × 50 × 6 mm plate.", "Observed interactive CAD or the explicit WebGL fallback.", "Activated Verify revision 1 and waited for the real terminal pipeline."],
      observed: {
        url: this.page.url(),
        visible: [designName, "Ready", validation.filename, "What it really takes"],
        persisted: { designId, revision: 1, decisionId: truth.savedDecisionId },
        numeric: { createStatus: createResponse.status(), artifactStatus: artifactResponse.status(), validationStatus: validationResponse.status(), costStatus: costResponse.status() },
        authorization: { orgRole: this.account.orgRole, mutationAllowed: true },
        recovery: "The exact immutable Design Studio revision re-entered the ordinary Verify pipeline without a privileged shortcut.",
      },
      visualSteps,
      assertions: [
        assertion("design create status", 202, createResponse.status()),
        assertion("preview or explicit fallback", true, preview.canvasVisible || preview.fallbackVisible),
        assertion("stable design id in handoff", designId, new URL(this.page.url()).searchParams.get("design")),
        assertion("handoff pipeline disappeared", true, pipeline.disappeared),
      ],
    };
  }

  async openMobileNavigationDestination(label, pathname) {
    const menu = this.page.getByRole("button", { name: "Open navigation" });
    await this.clickPrimary(menu, `open app navigation for ${label}`);
    const link = this.page.getByRole("menuitem", { name: new RegExp(`^${escapeRegExp(label)}(?:\\s|$)`, "i") }).first();
    const destination = this.page.waitForURL((url) => url.pathname === pathname, { timeout: this.actionTimeoutMs });
    await this.clickPrimary(link, `app navigation target ${label}`);
    await destination;
    await this.waitForSettled(pathname);
    await this.assertNoHorizontalOverflow(pathname);
  }

  async runHistory(definition) {
    await this.setViewport(VIEWPORTS[0]);
    await this.goto("/verify", "history entry origin");
    await this.openMobileNavigationDestination("Recent analyses", "/history");
    await this.page.getByRole("heading", { name: "History", exact: true }).waitFor({ state: "visible" });
    const filter = this.page.getByRole("combobox").first();
    await this.assertPrimaryTarget(filter, "History verdict filter");
    const visualSteps = [await this.captureStage(
      definition.id,
      "375x812-history",
      ["History", "Quota consumption", "Recent analyses"],
    )];
    return {
      persona: "mobile engineer reviewing prior analysis activity",
      preconditions: ["The authenticated account has completed at least one real verification."],
      actions: ["Opened the responsive app navigation.", "Selected Recent analyses.", "Focused the verdict filter after the table settled."],
      observed: {
        url: this.page.url(),
        visible: ["History", "Quota consumption", "Recent analyses"],
        persisted: { decisionId: this.cadEvidence?.truth?.savedDecisionId || "verification id unavailable" },
        numeric: { filterControls: await this.page.getByRole("combobox").count() },
        authorization: { authenticated: true, orgId: this.account.orgId },
        recovery: "The history table reached a terminal loaded or honest empty state without a busy placeholder.",
      },
      visualSteps,
      assertions: [assertion("history pathname", "/history", new URL(this.page.url()).pathname)],
    };
  }

  async runNotifications(definition) {
    await this.setViewport(VIEWPORTS[1]);
    const link = this.page.getByRole("link", { name: "Notifications", exact: true });
    const destination = this.page.waitForURL((url) => url.pathname === "/notifications", { timeout: this.actionTimeoutMs });
    await this.clickPrimary(link, "Notifications header target");
    await destination;
    await this.page.getByRole("heading", { name: "Notifications", exact: true }).waitFor({ state: "visible" });
    await this.waitForSettled("notifications inbox");
    await this.assertPrimaryTarget(this.page.getByRole("link", { name: "Open Verify", exact: true }), "Open Verify from notifications");
    const visualSteps = [await this.captureStage(
      definition.id,
      "390x844-notifications",
      ["Notifications", "Inbox", "Source of truth"],
    )];
    return {
      persona: "mobile workflow owner reviewing durable notifications",
      preconditions: ["The user is authenticated in the same organization used for verification."],
      actions: ["Activated the persistent Notifications target.", "Waited for active and dismissed reads to settle.", "Inspected the canonical-source explanation."],
      observed: {
        url: this.page.url(),
        visible: ["Notifications", "Inbox", "Source of truth"],
        persisted: "Active and dismissed inbox rows came from durable organization reads.",
        numeric: { notificationArticles: await this.page.locator("article[data-notification-id]").count() },
        authorization: { authenticated: true, orgId: this.account.orgId },
        recovery: "The inbox exposed an actionable Open Verify route in both populated and empty states.",
      },
      visualSteps,
      assertions: [assertion("notifications pathname", "/notifications", new URL(this.page.url()).pathname)],
    };
  }

  async openAccountDestination(name, pathname) {
    await this.clickPrimary(this.page.getByRole("button", { name: "Account", exact: true }), `open account menu for ${name}`);
    const item = this.page.getByRole("menuitem", { name, exact: true });
    const destination = this.page.waitForURL((url) => url.pathname === pathname, { timeout: this.actionTimeoutMs });
    await this.clickPrimary(item, name);
    await destination;
    await this.waitForSettled(pathname);
    await this.assertNoHorizontalOverflow(pathname);
  }

  async runSettings(definition) {
    await this.setViewport(VIEWPORTS[2]);
    await this.goto("/verify", "settings entry origin");
    const visualSteps = [];

    await this.openAccountDestination("Settings · Organization", "/settings/organization");
    await this.page.getByRole("heading", { name: "Organization", exact: true }).waitFor({ state: "visible" });
    if (this.account.orgRole === "admin") {
      await this.assertPrimaryTarget(this.page.getByRole("button", { name: "Send invite", exact: true }), "Send invite primary target");
      await this.page.getByText("Members", { exact: true }).first().waitFor({ state: "visible" });
    } else {
      await this.page.getByText("Admins only", { exact: true }).waitFor({ state: "visible" });
    }
    visualSteps.push(await this.captureStage(
      definition.id,
      "768x1024-organization",
      this.account.orgRole === "admin" ? ["Organization", "Members", "Invitations"] : ["Organization", "Admins only"],
    ));

    await this.openAccountDestination("Settings · Security", "/settings/security");
    await this.page.getByRole("heading", { name: "Security", exact: true }).waitFor({ state: "visible" });
    const passwordButton = this.page.getByRole("button", { name: "Set password", exact: true });
    if (await passwordButton.isVisible().catch(() => false)) {
      await this.assertPrimaryTarget(passwordButton, "Set password primary target");
    } else {
      await this.assertPrimaryTarget(this.page.getByRole("button", { name: "Account", exact: true }), "managed-security account target");
    }
    visualSteps.push(await this.captureStage(definition.id, "768x1024-security", ["Security"]));

    await this.openAccountDestination("Settings · Developer", "/settings/developer");
    await this.page.getByRole("heading", { name: "Developer", exact: true }).waitFor({ state: "visible" });
    await this.assertPrimaryTarget(this.page.getByRole("button", { name: "Create key", exact: true }).first(), "Create key primary target");
    visualSteps.push(await this.captureStage(
      definition.id,
      "768x1024-developer",
      ["Developer", "Developer resources"],
    ));
    return {
      persona: "organization administrator reviewing account and workspace settings on a tablet",
      preconditions: ["The account menu reflects the current platform role.", "Organization controls are rendered according to the active org role."],
      actions: ["Opened Organization, Security, and Developer from the account menu.", "Focused each role-appropriate primary action without mutating it."],
      observed: {
        url: this.page.url(),
        visible: ["Organization", "Security", "Developer", "Developer resources"],
        persisted: { userId: this.account.userId, orgId: this.account.orgId },
        numeric: { settingsSurfaces: 3 },
        authorization: { platformRole: this.account.platformRole, orgRole: this.account.orgRole, adminControlsVisible: this.account.orgRole === "admin" },
        recovery: "Every settings route remained reachable through the persistent account menu.",
      },
      visualSteps,
      assertions: [
        assertion("settings surface count", 3, visualSteps.length),
        assertion("organization role retained", "admin", this.account.orgRole),
      ],
    };
  }

  async runBatchEntry(definition) {
    await this.setViewport(VIEWPORTS[0]);
    await this.goto("/verify", "batch entry origin");
    await this.openMobileNavigationDestination("Batch run", "/batch");
    await this.page.getByRole("heading", { name: "Batch", exact: true }).waitFor({ state: "visible" });
    const dropzone = this.page.getByRole("button", { name: /Drag and drop or click to upload.*ZIP archive/i }).first();
    await this.assertPrimaryTarget(dropzone, "Batch ZIP dropzone");
    const input = this.page.locator('input[type="file"][accept=".zip"]').first();
    await input.setInputFiles({
      name: "full-mobile-entry.zip",
      mimeType: "application/zip",
      buffer: Buffer.from("PK\u0003\u0004full-mobile-entry", "utf8"),
    });
    await this.page.getByText(/full-mobile-entry\.zip/i).waitFor({ state: "visible" });
    await this.assertPrimaryTarget(this.page.getByRole("button", { name: "Start batch", exact: true }), "Start batch primary target");
    const visualSteps = [await this.captureStage(
      definition.id,
      "375x812-batch-entry",
      ["Batch", "New batch", "full-mobile-entry.zip", "Start batch"],
    )];
    return {
      persona: "batch operator preparing a ZIP run on a phone",
      preconditions: ["The batch page is authenticated.", "No batch mutation is needed to prove the entry contract."],
      actions: ["Opened Batch run from responsive navigation.", "Focused the ZIP dropzone.", "Selected a ZIP payload and proved Start batch became actionable."],
      observed: {
        url: this.page.url(),
        visible: ["Batch", "New batch", "full-mobile-entry.zip", "Start batch"],
        persisted: "The selected ZIP remained in the form; no batch was submitted by this entry-only outcome.",
        numeric: { selectedFiles: 1, concurrencyLimit: await this.page.getByLabel("Concurrency limit").inputValue() },
        authorization: { authenticated: true, orgId: this.account.orgId },
        recovery: "The operator can leave before submission without creating a duplicate batch.",
      },
      visualSteps,
      assertions: [assertion("batch pathname", "/batch", new URL(this.page.url()).pathname)],
    };
  }

  async runReconstructionEntry(definition) {
    await this.setViewport(VIEWPORTS[1]);
    const capabilityResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "GET", "/api/proxy/reconstruct/capability"),
      { timeout: this.actionTimeoutMs },
    );
    await this.goto("/reconstruct", "reconstruction capability boundary");
    const capabilityResponse = await capabilityResponsePromise;
    const capability = await responseJson(capabilityResponse, "reconstruction capability");
    invariant(capabilityResponse.status() === 200, `reconstruction capability returned HTTP ${capabilityResponse.status()}`);
    invariant(capability?.available === false, "launch configuration unexpectedly advertised Image-to-3D as available");
    await this.page.getByRole("heading", { name: "Image to 3D", exact: true }).waitFor({ state: "visible" });
    await this.page.getByRole("heading", { name: "Image-to-3D is not enabled", exact: true }).waitFor({ state: "visible" });
    await this.page.getByText("No image has been uploaded or sent to a third party.", { exact: true }).waitFor({ state: "visible" });
    const verifyInstead = this.page.getByRole("button", { name: "Verify CAD instead", exact: true });
    await this.assertPrimaryTarget(verifyInstead, "Verify CAD instead");
    invariant(await this.page.locator('input[type="file"]').count() === 0, "unavailable reconstruction boundary exposed a file input");
    invariant(await this.page.getByRole("button", { name: /Reconstruct \(/ }).count() === 0, "unavailable reconstruction boundary exposed a submit action");
    const visualSteps = [await this.captureStage(
      definition.id,
      "390x844-reconstruction-unavailable",
      ["Image to 3D", "Image-to-3D is not enabled", "No image has been uploaded or sent to a third party.", "Verify CAD instead"],
    )];
    await this.clickPrimary(verifyInstead, "Verify CAD instead");
    await this.page.waitForURL(
      (url) => url.pathname === "/verify" && url.searchParams.get("screen") === "verify",
      { timeout: this.actionTimeoutMs },
    );
    await this.page.getByText("Drop a part to begin the walk.", { exact: true }).waitFor({ state: "visible" });
    await this.assertNoElementOverlap(
      this.page.locator(".cv-verify-stage-title"),
      this.page.getByTestId("verify-stage-context"),
      "phone Verify stage title and context card",
    );
    visualSteps.push(await this.captureStage(
      definition.id,
      "390x844-verify-cad-handoff",
      ["Drop a part to begin the walk."],
    ));
    return {
      persona: "mobile operator evaluating an unavailable optional capability",
      preconditions: ["The reconstruction route is authenticated.", "The launch build intentionally has no approved image-to-3D backend."],
      actions: ["Opened Image to 3D.", "Verified the unavailable capability was disclosed before any image selection.", "Used Verify CAD instead and reached the supported CAD workflow."],
      observed: {
        url: this.page.url(),
        visible: ["Image-to-3D is not enabled", "No image has been uploaded or sent to a third party.", "Verify CAD instead", "Drop a part to begin the walk."],
        persisted: "No image was selected, uploaded, stored, or sent; the operator reached the supported Verify CAD uploader directly.",
        numeric: { capabilityStatus: capabilityResponse.status(), exposedFileInputs: 0, exposedReconstructActions: 0 },
        authorization: { authenticated: true, orgId: this.account.orgId },
        recovery: "The unavailable optional capability provides a one-tap handoff to the supported CAD workflow.",
      },
      visualSteps,
      assertions: [
        assertion("capability status", 200, capabilityResponse.status()),
        assertion("capability unavailable", false, capability.available),
        assertion("supported handoff pathname", "/verify", new URL(this.page.url()).pathname),
        assertion("supported handoff screen", "verify", new URL(this.page.url()).searchParams.get("screen")),
      ],
    };
  }

  async runSessionRecovery(definition) {
    invariant(this.account, "signup account is unavailable for login recovery");
    invariant(this.cadEvidence, "saved verification is unavailable for post-login persistence recovery");
    await this.setViewport(VIEWPORTS[2]);
    await this.goto("/verify", "session recovery origin");
    await this.clickPrimary(this.page.getByRole("button", { name: "Account", exact: true }), "Account menu for logout");
    const logoutResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/auth/logout"),
      { timeout: this.actionTimeoutMs },
    );
    const loginDestination = this.page.waitForURL((url) => url.pathname === "/login", { timeout: this.actionTimeoutMs });
    await this.clickPrimary(this.page.getByRole("menuitem", { name: "Sign out", exact: true }), "Sign out");
    const logoutResponse = await logoutResponsePromise;
    await loginDestination;
    invariant(logoutResponse.status() === 200, `logout returned HTTP ${logoutResponse.status()}`);
    await this.page.getByRole("heading", { name: "Log in to ProofShape", exact: true }).waitFor({ state: "visible" });
    const visualSteps = [await this.captureStage(
      definition.id,
      "768x1024-logged-out",
      ["Log in to ProofShape"],
    )];

    await this.goto("/verify", "gated Verify after logout");
    invariant(new URL(this.page.url()).pathname === "/login", "logged-out /verify did not remain gated at /login");
    await this.fillPrimary(this.page.getByLabel("Email"), this.account.email, "login recovery email");
    await this.fillPrimary(this.page.getByLabel("Password"), this.account.password, "login recovery password");
    const loginResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/auth/login"),
      { timeout: this.actionTimeoutMs },
    );
    const verifyDestination = this.page.waitForURL((url) => url.pathname === "/verify", { timeout: this.actionTimeoutMs });
    await this.clickPrimary(this.page.getByRole("button", { name: /^Log in$/ }), "Log in recovery");
    const loginResponse = await loginResponsePromise;
    await verifyDestination;
    invariant(loginResponse.status() === 200, `login recovery returned HTTP ${loginResponse.status()}`);
    await this.waitForSettled("restored Verify session");

    const orgResponse = await browserJson(this.page, "GET", "/api/proxy/orgs");
    invariant(orgResponse.status === 200, `restored organization context returned HTTP ${orgResponse.status}`);
    const orgBody = orgResponse.body;
    invariant(orgBody?.active_org_id === this.account.orgId, `login recovery changed active org from ${this.account.orgId} to ${orgBody?.active_org_id}`);

    await this.navigateVerifySection(VERIFY_SECTIONS[3]);
    const decisionId = this.cadEvidence.truth.savedDecisionId;
    const recordButton = this.page.getByRole("button", { name: new RegExp(escapeRegExp(this.cadEvidence.fixture.filename), "i") }).first();
    const detailResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "GET", `/api/proxy/cost-decisions/${decisionId}`),
      { timeout: this.actionTimeoutMs },
    );
    await this.clickPrimary(recordButton, "restored session saved record");
    const detailResponse = await detailResponsePromise;
    const detail = await responseJson(detailResponse, "restored session record");
    invariant(detailResponse.status() === 200, `restored record returned HTTP ${detailResponse.status()}`);
    invariant(detail.id === decisionId, `login recovery reopened ${detail.id}, expected ${decisionId}`);
    const governanceLink = this.page.getByTestId("record-disposition-summary").locator(`a[href="/cost-decisions/${decisionId}"]`);
    await this.assertPrimaryTarget(governanceLink, "restored record governance link");
    this.sessionRecoveryEvidence = {
      userId: this.account.userId,
      orgId: orgBody.active_org_id,
      decisionId: detail.id,
    };
    visualSteps.push(await this.captureStage(
      definition.id,
      "768x1024-login-restored-record",
      [this.cadEvidence.fixture.filename, "Open governance"],
    ));
    return {
      persona: "returning organization administrator recovering a signed-out tablet session",
      preconditions: ["The account password and stable organization id were captured from real signup.", "A saved verification record exists."],
      actions: ["Signed out from the account menu.", "Confirmed /verify remained gated.", "Logged in with the original credentials and reopened the exact saved record."],
      observed: {
        url: this.page.url(),
        visible: ["Log in to ProofShape", this.cadEvidence.fixture.filename, "Open governance"],
        persisted: { userId: this.account.userId, orgId: this.account.orgId, decisionId },
        numeric: { logoutStatus: logoutResponse.status(), loginStatus: loginResponse.status(), recordStatus: detailResponse.status() },
        authorization: { orgRole: this.account.orgRole, gatedWhileLoggedOut: true },
        recovery: "The restored session retained the same organization and immutable decision id.",
      },
      visualSteps,
      assertions: [
        assertion("logout status", 200, logoutResponse.status()),
        assertion("login status", 200, loginResponse.status()),
        assertion("active organization stable", this.account.orgId, orgBody.active_org_id),
        assertion("saved decision stable after login", decisionId, detail.id),
      ],
    };
  }

  async runAllOutcomes() {
    const byId = Object.fromEntries(REQUIRED_OUTCOME_DEFINITIONS.map((definition) => [definition.id, definition]));
    await this.runOutcome(byId["FULL-MOB-01"], () => this.runPublicNavigation(byId["FULL-MOB-01"]));
    await this.runOutcome(byId["FULL-MOB-02"], () => this.runSignupDayZero(byId["FULL-MOB-02"]));
    await this.runOutcome(byId["FULL-MOB-03"], () => this.runVerifySections(byId["FULL-MOB-03"]));
    await this.runOutcome(byId["FULL-MOB-04"], () => this.runVerifyCommandPalette(byId["FULL-MOB-04"]));
    await this.runOutcome(byId["FULL-MOB-05"], () => this.runSupportedCad(byId["FULL-MOB-05"]));
    await this.runOutcome(byId["FULL-MOB-06"], () => this.runDispositionPersistence(byId["FULL-MOB-06"]));
    await this.runOutcome(byId["FULL-MOB-07"], () => this.runDesignStudio(byId["FULL-MOB-07"]));
    await this.runOutcome(byId["FULL-MOB-08"], () => this.runHistory(byId["FULL-MOB-08"]));
    await this.runOutcome(byId["FULL-MOB-09"], () => this.runNotifications(byId["FULL-MOB-09"]));
    await this.runOutcome(byId["FULL-MOB-10"], () => this.runSettings(byId["FULL-MOB-10"]));
    await this.runOutcome(byId["FULL-MOB-11"], () => this.runBatchEntry(byId["FULL-MOB-11"]));
    await this.runOutcome(byId["FULL-MOB-12"], () => this.runReconstructionEntry(byId["FULL-MOB-12"]));
    await this.runOutcome(byId["FULL-MOB-13"], () => this.runSessionRecovery(byId["FULL-MOB-13"]));
  }

  ensureAllOutcomeRecords(fatalError = null) {
    const error = fatalError instanceof Error
      ? fatalError
      : new Error(fatalError ? String(fatalError) : "The runner stopped before this required outcome was attempted.");
    for (const definition of REQUIRED_OUTCOME_DEFINITIONS) {
      if (this.outcomes[definition.id]) continue;
      this.outcomes[definition.id] = failedOutcomeRecord(
        definition,
        error,
        null,
        null,
        { consoleErrors: [], requestFailures: [], unexpectedHttpErrors: [], url: this.page?.url?.() || "not-reached" },
      );
      this.defects.push({
        id: definition.id,
        title: definition.title,
        severity: "release-blocking",
        viewport: null,
        url: this.page?.url?.() || "not-reached",
        error: error.message,
        screenshot: null,
        diagnostics: { consoleErrors: [], requestFailures: [], unexpectedHttpErrors: [] },
      });
    }
  }

  async result(fatalError = null) {
    this.ensureAllOutcomeRecords(fatalError);
    const buildIdentityAtEnd = captureBuildIdentity(repoRoot);
    const validation = validateOutcomeMap(this.outcomes);
    const runnerSha256 = createHash("sha256").update(await readFile(__filename)).digest("hex");
    const buildStable = this.buildIdentityAtStart.gitHead === buildIdentityAtEnd.gitHead;
    const servedBuildIds = [...this.servedBuildIds].sort();
    const servedBuildExact = servedBuildIds.length === 1 && servedBuildIds[0] === this.expectedBuild.buildId;
    const allPrimaryTargets = this.primaryTargetChecks.length > 0 && this.primaryTargetChecks.every(
      (check) => check.visible && check.clickable && check.focusable,
    );
    const zeroOverflow = this.overflowChecks.length > 0 && this.overflowChecks.every((check) => check.pass);
    const zeroBusyTerminals = this.settleChecks.length > 0 && this.settleChecks.every((check) => check.pass);
    const zeroDiagnostics = this.consoleErrors.length === 0 && this.requestFailures.length === 0 && this.unexpectedHttpErrors.length === 0;
    const stablePersistedDecisionId = Boolean(
      this.cadEvidence?.truth?.savedDecisionId &&
      this.dispositionEvidence?.decisionId === this.cadEvidence.truth.savedDecisionId &&
      this.dispositionEvidence.reopened.length === VIEWPORTS.length &&
      this.dispositionEvidence.reopened.every((item) => item.id === this.cadEvidence.truth.savedDecisionId),
    );
    const stablePersistedDesignId = Boolean(
      this.designEvidence?.designId && this.designEvidence?.decisionId,
    );
    const stableSessionRecoveryIds = Boolean(
      this.account?.userId &&
      this.sessionRecoveryEvidence?.userId === this.account.userId &&
      this.sessionRecoveryEvidence?.orgId === this.account.orgId &&
      this.sessionRecoveryEvidence?.decisionId === this.cadEvidence?.truth?.savedDecisionId,
    );
    const acceptance = {
      allRequiredOutcomesPass: validation.valid === validation.total,
      allOutcomeRecordsSchemaVersion2: Object.values(this.outcomes).every((outcome) => outcome.schemaVersion === OUTCOME_SCHEMA_VERSION),
      noPartialOutcomeStatus: Object.values(this.outcomes).every((outcome) => outcome.status === "PASS"),
      noSkippedOutcomes: Object.keys(this.outcomes).length === REQUIRED_OUTCOME_IDS.length &&
        Object.values(this.outcomes).every((outcome) => outcome.status === "PASS"),
      allRequiredViewportsCaptured: REQUIRED_OUTCOME_DEFINITIONS.every((definition) =>
        sameStringSet(this.outcomes[definition.id]?.viewportKeys || [], definition.requiredViewportKeys)
      ),
      allPrimaryTargetsVisibleClickableFocusable: allPrimaryTargets,
      noHorizontalOverflow: zeroOverflow,
      noIndefiniteBusyOrTemporaryPlaceholder: zeroBusyTerminals,
      stablePersistedDecisionId,
      stablePersistedDesignId,
      stableSessionRecoveryIds,
      screenshotsCaptured: this.screenshots.length > 0 && this.screenshots.every((screenshot) => screenshot.bytes > 0),
      zeroUnexpectedConsoleErrors: this.consoleErrors.length === 0,
      zeroUnexpectedRequestFailures: this.requestFailures.length === 0,
      zeroUnexpectedHttpFailures: this.unexpectedHttpErrors.length === 0,
      buildIdentityStableDuringRun: buildStable,
      servedBuildIdentityExact: servedBuildExact,
    };
    const status = !fatalError && this.defects.length === 0 && validation.valid === validation.total &&
      zeroDiagnostics && Object.values(acceptance).every(Boolean)
      ? "PASS"
      : "FAIL";
    return {
      schemaVersion: OUTCOME_SCHEMA_VERSION,
      status,
      suite: "full-mobile-browser",
      runId: this.runId,
      baseUrl: this.baseUrl,
      startedAt: this.startedAt,
      generatedAt: new Date().toISOString(),
      durationMs: Date.now() - Date.parse(this.startedAt),
      viewports: VIEWPORTS,
      requiredOutcomeIds: REQUIRED_OUTCOME_IDS,
      account: this.account ? {
        email: this.account.email,
        userId: this.account.userId,
        orgId: this.account.orgId,
        platformRole: this.account.platformRole,
        orgRole: this.account.orgRole,
      } : null,
      persistedIds: {
        decisionId: this.cadEvidence?.truth?.savedDecisionId || null,
        designId: this.designEvidence?.designId || null,
        designDecisionId: this.designEvidence?.decisionId || null,
      },
      buildIdentity: {
        start: this.buildIdentityAtStart,
        end: buildIdentityAtEnd,
        expectedServedBuild: this.expectedBuild,
        servedBuildIds,
        runnerSha256,
        sameGitHead: buildStable,
      },
      outcomes: this.outcomes,
      validation,
      acceptance,
      steps: this.steps,
      defects: this.defects,
      diagnostics: {
        consoleErrors: this.consoleErrors,
        pageErrors: this.pageErrors,
        requestFailures: this.requestFailures,
        unexpectedHttpErrors: this.unexpectedHttpErrors,
        expectedRequestAborts: this.expectedRequestAborts,
      },
      contractChecks: {
        primaryTargets: this.primaryTargetChecks,
        horizontalOverflow: this.overflowChecks,
        settledTerminals: this.settleChecks,
      },
      screenshots: this.screenshots,
      artifacts: { json: this.reportPath, markdown: this.markdownPath, screenshotDir: this.screenshotDir },
      fatalError: fatalError instanceof Error ? fatalError.stack : fatalError ? String(fatalError) : null,
    };
  }

  markdown(report) {
    const outcomeRows = REQUIRED_OUTCOME_DEFINITIONS.map((definition) => {
      const outcome = report.outcomes[definition.id];
      const problems = report.validation.problems.filter((problem) => problem.id === definition.id);
      return `| ${outcome?.status || "FAIL"} | ${definition.id} | ${definition.title} | ${(outcome?.viewportKeys || []).join(", ")} | ${problems.length} | ${outcome?.screenshot || ""} |`;
    }).join("\n");
    const defects = report.defects.length
      ? report.defects.map((defect) => `- **${defect.id} · ${defect.title}** (${defect.viewport || "not reached"}) ${defect.error}${defect.screenshot ? ` — ${defect.screenshot}` : ""}`).join("\n")
      : "- None.";
    return `# Full mobile browser human-simulation report\n\n` +
      `- Status: ${report.status}\n` +
      `- Target: ${report.baseUrl}\n` +
      `- Build: ${report.buildIdentity.expectedServedBuild.buildId} (${report.buildIdentity.expectedServedBuild.source})\n` +
      `- Outcomes: ${report.validation.valid}/${report.validation.total}\n` +
      `- Viewports: ${VIEWPORTS.map((viewport) => viewport.key).join(", ")}\n` +
      `- Screenshots: ${report.screenshots.length}\n` +
      `- Console / request / HTTP failures: ${report.diagnostics.consoleErrors.length} / ${report.diagnostics.requestFailures.length} / ${report.diagnostics.unexpectedHttpErrors.length}\n\n` +
      `## Outcomes\n\n| Status | ID | Journey | Viewports | Oracle problems | Screenshot |\n| --- | --- | --- | --- | ---: | --- |\n${outcomeRows}\n\n` +
      `## Genuine defects\n\n${defects}\n\n` +
      `## Acceptance\n\n\`\`\`json\n${JSON.stringify(report.acceptance, null, 2)}\n\`\`\`\n`;
  }

  async writeReport(report) {
    await mkdir(this.outputRoot, { recursive: true });
    await writeFile(this.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    await writeFile(this.markdownPath, this.markdown(report), "utf8");
  }

  async close() {
    await this.context?.close().catch(() => {});
    await this.browser?.close().catch(() => {});
  }
}

function parseArgs(argv) {
  const options = { headed: false, help: false };
  for (const arg of argv) {
    if (arg === "--headed") options.headed = true;
    else if (arg === "--help" || arg === "-h") options.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  return options;
}

function usage() {
  return "Usage: node scripts/e2e/full-mobile-browser.mjs [--headed]\n\n" +
    "Environment: APP_URL, E2E_BUILD_ID, E2E_ARTIFACT_DIR, E2E_RUN_ID, E2E_CLIENT_IP.\n";
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(usage());
    return;
  }
  const totalTimeoutMs = Number(process.env.FULL_MOBILE_TOTAL_TIMEOUT_MS || 18 * 60_000);
  invariant(Number.isFinite(totalTimeoutMs) && totalTimeoutMs >= 60_000, "FULL_MOBILE_TOTAL_TIMEOUT_MS must be at least 60000");
  const runner = new FullMobileBrowserRun({ headed: options.headed });
  let fatalError = null;
  let timer;
  try {
    await runner.init();
    await Promise.race([
      runner.runAllOutcomes(),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`full mobile browser run exceeded ${totalTimeoutMs} ms`)), totalTimeoutMs);
      }),
    ]);
  } catch (error) {
    fatalError = error instanceof Error ? error : new Error(String(error));
  } finally {
    clearTimeout(timer);
    const report = await runner.result(fatalError);
    await runner.writeReport(report);
    await runner.close();
    process.stdout.write(`${JSON.stringify({
      status: report.status,
      outcomes: `${report.validation.valid}/${report.validation.total}`,
      defects: report.defects.length,
      consoleErrors: report.diagnostics.consoleErrors.length,
      requestFailures: report.diagnostics.requestFailures.length,
      unexpectedHttpErrors: report.diagnostics.unexpectedHttpErrors.length,
      report: report.artifacts.markdown,
      json: report.artifacts.json,
      screenshots: report.artifacts.screenshotDir,
    }, null, 2)}\n`);
    if (report.status !== "PASS") process.exitCode = 1;
  }
}

const invokedAsScript = process.argv[1] && path.resolve(process.argv[1]) === __filename;
if (invokedAsScript) {
  await main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
