#!/usr/bin/env node

/**
 * Representative real-CAD human-browser runner.
 *
 * This is deliberately a bounded complement to real_cad_corpus.py's exhaustive
 * parser matrix.  Every supported fixture enters through the real Verify file
 * input, waits for the visible pipeline dialog to appear and disappear, proves
 * nonzero response geometry against terminal UI text, records a disposition,
 * refreshes, and reopens the exact immutable record. The native SolidWorks
 * assembly is retained as an explicit unsupported control: the real file-input
 * branch must provide an actionable STEP-export path without starting network
 * compute or reporting a successful verification.
 */

import { createHash, randomBytes } from "node:crypto";
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const requireFromFrontend = createRequire(new URL("../../frontend/package.json", import.meta.url));

export const REQUIRED_COVERAGE = Object.freeze([
  "ap203_geometry",
  "ap203_pmi",
  "ap242_e1",
  "ap242_e2",
  "ap242_e3",
  "ap242_embedded_tessellation",
  "tracked_periodic_step",
  "native_assembly_unsupported",
]);
export const OPTIONAL_COVERAGE = Object.freeze(["iges"]);
export const MAX_SUPPORTED_CASES = 7;

const EXPECTED_ARCHIVE_HASHES = new Map([
  ["nist_pmi_step", "8fa78429e6d8d9b0d7681d223b6aa9ec98c3772185c55b1a0e3679b21c181911"],
  ["nist_mtc_assembly", "9aeb53e54f682ea1732857d06a7f0513c71667a2d84407396325fa6ce5340bbc"],
]);
const FIXTURE_BINDING_FIELDS = Object.freeze([
  "id",
  "relative_path",
  "file_sha256",
  "bytes",
  "support_status",
  "expected_browser_outcome",
  "source_ref",
]);
const SUPPORTED_SUFFIXES = new Set([".stl", ".step", ".stp", ".iges", ".igs"]);
const ALLOWED_PROVENANCE = new Set(["MEASURED", "SHOP", "USER", "DEFAULT"]);
const FAILURE_COPY = /Cost request failed|Validation failed|Network error|Geometry invalid|repair required|Could not analyze|should-cost unavailable/i;

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isSha256(value) {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function finitePositive(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function positiveVector(value, length = 3) {
  return Array.isArray(value) && value.length === length && value.every(finitePositive);
}

function sha256Bytes(value) {
  return createHash("sha256").update(value).digest("hex");
}

function slug(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function responsePath(response) {
  try {
    return new URL(response.url()).pathname;
  } catch {
    return response.url();
  }
}

function isResponse(response, method, pathname) {
  return response.request().method() === method && responsePath(response) === pathname;
}

/**
 * Next.js may cancel an in-flight React Server Component prefetch when real
 * navigation wins the race. Classify only that narrow, same-origin case as an
 * expected browser diagnostic; every other failed request remains fatal.
 */
export function isExpectedNextRscPrefetchAbort(item, appUrl) {
  if (
    item?.error !== "net::ERR_ABORTED" ||
    item?.method !== "GET" ||
    item?.resourceType !== "fetch"
  ) {
    return false;
  }
  try {
    const requestUrl = new URL(item.url);
    const expectedOrigin = new URL(appUrl).origin;
    return requestUrl.origin === expectedOrigin && Boolean(requestUrl.searchParams.get("_rsc"));
  } catch {
    return false;
  }
}

function relativeDifference(a, b) {
  return Math.abs(a - b) / Math.max(Math.abs(a), Math.abs(b), 1e-12);
}

function currencyRegex() {
  return /\$\s?\d[\d,.]*\s*\/unit/i;
}

export function fixtureSetBindingSha256(fixtures) {
  invariant(Array.isArray(fixtures), "manifest fixtures must be an array");
  const rows = [...fixtures]
    .sort((a, b) => String(a.id).localeCompare(String(b.id)))
    .map((fixture) => {
      const values = FIXTURE_BINDING_FIELDS.map((field) => String(fixture?.[field]));
      invariant(values.every((value) => !/[\t\n]/.test(value)), "fixture binding fields may not contain tabs/newlines");
      return values.join("\t");
    });
  return sha256Bytes(`${rows.join("\n")}\n`);
}

/** Load, schema-check, path-confine, and byte-verify the materialized set. */
export function loadRepresentativeManifest(manifestPath) {
  const absoluteManifest = path.resolve(manifestPath);
  const manifestRoot = path.dirname(absoluteManifest);
  const manifestBytes = readFileSync(absoluteManifest);
  let manifest;
  try {
    manifest = JSON.parse(manifestBytes.toString("utf8"));
  } catch (error) {
    throw new Error(`representative manifest is not valid JSON: ${error.message}`);
  }

  invariant(manifest.schema_version === 1, `unsupported representative manifest schema ${manifest.schema_version}`);
  invariant(manifest.set_id === "nist-representative-browser-v1", `unexpected fixture set ${manifest.set_id}`);
  invariant(Array.isArray(manifest.fixtures) && manifest.fixtures.length > 0, "representative manifest has no fixtures");
  invariant(isObject(manifest.coverage), "representative manifest has no coverage map");
  invariant(Array.isArray(manifest.source_archives), "representative manifest has no source archive list");
  invariant(Array.isArray(manifest.omissions), "representative manifest omissions must be an array");
  invariant(
    JSON.stringify(manifest.binding_fields) === JSON.stringify(FIXTURE_BINDING_FIELDS),
    "representative manifest binding fields changed",
  );

  for (const [sourceId, expectedHash] of EXPECTED_ARCHIVE_HASHES) {
    const source = manifest.source_archives.find((item) => item?.id === sourceId);
    invariant(source, `manifest is missing pinned source archive ${sourceId}`);
    invariant(source.zip_sha256 === expectedHash, `${sourceId} archive hash is not pinned to ${expectedHash}`);
    invariant(Number.isInteger(source.zip_bytes) && source.zip_bytes > 0, `${sourceId} archive byte count is invalid`);
  }

  for (const tag of REQUIRED_COVERAGE) {
    invariant(Array.isArray(manifest.coverage[tag]) && manifest.coverage[tag].length > 0, `required browser family ${tag} is missing`);
  }
  for (const tag of OPTIONAL_COVERAGE) {
    const covered = Array.isArray(manifest.coverage[tag]) && manifest.coverage[tag].length > 0;
    const omitted = manifest.omissions.some((item) => item?.coverage_tags?.includes(tag) && typeof item.reason === "string");
    invariant(covered || omitted, `optional family ${tag} is neither materialized nor honestly omitted`);
  }

  const ids = new Set();
  const paths = new Set();
  const fixtures = manifest.fixtures.map((fixture) => {
    invariant(isObject(fixture), "fixture entry is not an object");
    invariant(typeof fixture.id === "string" && fixture.id.length > 0, "fixture id is missing");
    invariant(!ids.has(fixture.id), `duplicate fixture id ${fixture.id}`);
    ids.add(fixture.id);
    invariant(typeof fixture.relative_path === "string" && fixture.relative_path.length > 0, `${fixture.id} path is missing`);
    invariant(!path.isAbsolute(fixture.relative_path), `${fixture.id} path must be relative`);
    invariant(!paths.has(fixture.relative_path), `duplicate fixture path ${fixture.relative_path}`);
    paths.add(fixture.relative_path);
    invariant(isSha256(fixture.file_sha256), `${fixture.id} has an invalid SHA-256`);
    invariant(Number.isInteger(fixture.bytes) && fixture.bytes > 0, `${fixture.id} has an invalid byte count`);
    invariant(Array.isArray(fixture.coverage_tags) && fixture.coverage_tags.length > 0, `${fixture.id} has no coverage tags`);
    invariant(typeof fixture.source_ref === "string" && fixture.source_ref.length > 0, `${fixture.id} has no source binding`);

    const absolutePath = path.resolve(manifestRoot, fixture.relative_path);
    invariant(
      absolutePath.startsWith(`${manifestRoot}${path.sep}`),
      `${fixture.id} escapes the materialized fixture directory`,
    );
    const bytes = readFileSync(absolutePath);
    invariant(bytes.length === fixture.bytes, `${fixture.id} byte count changed: expected ${fixture.bytes}, got ${bytes.length}`);
    const digest = sha256Bytes(bytes);
    invariant(digest === fixture.file_sha256, `${fixture.id} SHA-256 changed: expected ${fixture.file_sha256}, got ${digest}`);

    const suffix = path.extname(fixture.filename || fixture.relative_path).toLowerCase();
    if (fixture.support_status === "supported") {
      invariant(fixture.expected_browser_outcome === "verified_and_saved", `${fixture.id} has an untruthful supported outcome`);
      invariant(SUPPORTED_SUFFIXES.has(suffix), `${fixture.id} is marked supported with unsupported suffix ${suffix}`);
    } else {
      invariant(fixture.support_status === "unsupported", `${fixture.id} has unknown support status ${fixture.support_status}`);
      invariant(
        fixture.expected_browser_outcome === "unsupported_native_assembly",
        `${fixture.id} must remain an unsupported native-assembly control`,
      );
      invariant(!SUPPORTED_SUFFIXES.has(suffix), `${fixture.id} unsupported control uses a supported suffix`);
    }
    return { ...fixture, absolutePath };
  });

  const supported = fixtures.filter((fixture) => fixture.support_status === "supported");
  const unsupported = fixtures.filter((fixture) => fixture.support_status === "unsupported");
  invariant(supported.length >= 6, `representative browser set is too narrow (${supported.length} supported cases)`);
  invariant(supported.length <= MAX_SUPPORTED_CASES, `representative browser set exceeds bounded cap ${MAX_SUPPORTED_CASES}`);
  invariant(unsupported.length === 1, `expected exactly one unsupported native control, got ${unsupported.length}`);
  invariant(
    unsupported[0].coverage_tags.includes("native_assembly_unsupported"),
    "unsupported control is not the native-assembly boundary",
  );

  const binding = fixtureSetBindingSha256(manifest.fixtures);
  invariant(isSha256(manifest.fixture_set_sha256), "manifest fixture-set hash is invalid");
  invariant(binding === manifest.fixture_set_sha256, `fixture-set binding changed: expected ${manifest.fixture_set_sha256}, got ${binding}`);

  return {
    manifest,
    manifestPath: absoluteManifest,
    manifestSha256: sha256Bytes(manifestBytes),
    fixtures,
    supported,
    unsupported,
  };
}

function provenanceValues(cost) {
  const values = [];
  for (const assumption of cost?.assumptions || []) values.push(assumption?.provenance);
  for (const estimate of cost?.estimates || []) {
    for (const driver of estimate?.drivers || []) values.push(driver?.provenance);
  }
  return [...new Set(values.filter((value) => typeof value === "string"))].sort();
}

/** The human outcome must agree with the engine's selected-route boundary. */
export function dispositionForCost(cost) {
  const process = cost?.decision?.make_now_process;
  const selected = Array.isArray(cost?.estimates)
    ? cost.estimates.filter((estimate) => !process || estimate?.process === process)
    : [];
  const blocked = selected.some((estimate) =>
    estimate?.dfm_ready === false ||
    estimate?.dfm_verdict === "fail" ||
    estimate?.environment_excluded === true ||
    (Array.isArray(estimate?.dfm_blockers) && estimate.dfm_blockers.length > 0)
  );
  return blocked
    ? { key: "redesign", label: "Redesign" }
    : { key: "inhouse", label: "Make in-house" };
}

/** Pure supported-case oracle used by the live runner and targeted unit tests. */
export function assertTruthfulTerminalCase({ fixture, validation, cost, visibleText }) {
  invariant(fixture?.support_status === "supported", `${fixture?.id || "case"} is not a supported browser case`);
  invariant(fixture.expected_browser_outcome === "verified_and_saved", `${fixture.id} is not expected to verify and save`);
  invariant(isObject(validation), `${fixture.id} validation response is missing`);
  invariant(isObject(cost), `${fixture.id} cost response is missing`);
  invariant(typeof visibleText === "string" && visibleText.length > 0, `${fixture.id} terminal UI text is missing`);

  const measured = validation.geometry;
  invariant(isObject(measured), `${fixture.id} validation omitted measured geometry`);
  invariant(positiveVector(measured.bounding_box_mm), `${fixture.id} validation bounding box is not positive`);
  invariant(finitePositive(measured.volume_mm3), `${fixture.id} validation volume_mm3 is not positive`);
  invariant(finitePositive(measured.surface_area_mm2), `${fixture.id} validation surface_area_mm2 is not positive`);
  invariant(measured.is_watertight === true, `${fixture.id} validation geometry is not watertight`);
  invariant(validation.filename === fixture.filename, `${fixture.id} validation filename changed to ${validation.filename}`);
  invariant(typeof validation.overall_verdict === "string" && validation.overall_verdict.length > 0, `${fixture.id} has no DFM verdict`);

  const costGeometry = cost.geometry;
  invariant(cost.status === "OK", `${fixture.id} cost status was ${cost.status}`);
  invariant(isObject(costGeometry), `${fixture.id} cost omitted geometry`);
  invariant(positiveVector(costGeometry.bbox_mm), `${fixture.id} cost bounding box is not positive`);
  invariant(finitePositive(costGeometry.volume_cm3), `${fixture.id} cost volume_cm3 is not positive`);
  invariant(Number.isInteger(costGeometry.face_count) && costGeometry.face_count > 0, `${fixture.id} cost face_count is not positive`);
  invariant(costGeometry.watertight === true, `${fixture.id} cost geometry is not watertight`);
  invariant(
    relativeDifference(measured.volume_mm3 / 1000, costGeometry.volume_cm3) <= 0.02,
    `${fixture.id} validation/cost volumes disagree: ${measured.volume_mm3} mm3 vs ${costGeometry.volume_cm3} cm3`,
  );

  invariant(isObject(cost.decision) && typeof cost.decision.make_now_process === "string", `${fixture.id} has no make-now decision`);
  invariant(Array.isArray(cost.estimates) && cost.estimates.length > 0, `${fixture.id} has no cost estimates`);
  const costed = cost.estimates.filter((estimate) => finitePositive(estimate?.unit_cost_usd));
  invariant(costed.length > 0, `${fixture.id} has no positive unit cost`);
  for (const estimate of costed) {
    invariant(isObject(estimate.line_items) && Object.keys(estimate.line_items).length > 0, `${fixture.id} estimate has no line items`);
    const lineItemTotal = Object.values(estimate.line_items).reduce((sum, value) => sum + Number(value), 0);
    invariant(Number.isFinite(lineItemTotal), `${fixture.id} line-item sum is non-finite`);
    invariant(Math.abs(estimate.unit_cost_usd - Math.round(lineItemTotal * 100) / 100) < 0.02, `${fixture.id} unit cost does not reconcile to line items`);
    invariant(Array.isArray(estimate.drivers) && estimate.drivers.length > 0, `${fixture.id} estimate has no provenance-bearing drivers`);
  }

  const provenance = provenanceValues(cost);
  invariant(provenance.length > 0, `${fixture.id} cost response has no provenance values`);
  const badProvenance = provenance.filter((value) => !ALLOWED_PROVENANCE.has(value));
  invariant(badProvenance.length === 0, `${fixture.id} has unexpected provenance ${badProvenance.join(", ")}`);
  invariant(isObject(cost.saved) && typeof cost.saved.id === "string" && cost.saved.id.length > 0, `${fixture.id} has no durable saved decision id`);

  invariant(!FAILURE_COPY.test(visibleText), `${fixture.id} terminal UI contains failure copy`);
  invariant(visibleText.includes(fixture.filename), `${fixture.id} filename is not visible at terminal state`);
  invariant(/What it really takes/i.test(visibleText), `${fixture.id} terminal should-cost section is not visible`);
  invariant(/SHOULD-COST COMPUTED|Should-cost\s+\$/i.test(visibleText), `${fixture.id} terminal verdict does not claim a real computed should-cost`);
  invariant(currencyRegex().test(visibleText), `${fixture.id} has no visible unit cost`);
  invariant(/MEASURED/.test(visibleText), `${fixture.id} has no visible MEASURED provenance`);
  invariant(provenance.some((value) => visibleText.includes(value)), `${fixture.id} cost provenance is not visible`);
  invariant(/cm³/.test(visibleText), `${fixture.id} has no visible measured volume`);
  const bboxText = costGeometry.bbox_mm.map((value) => value.toFixed(1)).join(" × ");
  invariant(visibleText.includes(bboxText), `${fixture.id} exact measured bounding box is not visible`);
  invariant(visibleText.includes(`${costGeometry.volume_cm3.toFixed(2)} cm³`), `${fixture.id} exact measured volume is not visible`);

  return {
    validationGeometry: {
      boundingBoxMm: measured.bounding_box_mm,
      volumeMm3: measured.volume_mm3,
      surfaceAreaMm2: measured.surface_area_mm2,
      watertight: measured.is_watertight,
    },
    costGeometry: {
      boundingBoxMm: costGeometry.bbox_mm,
      volumeCm3: costGeometry.volume_cm3,
      faceCount: costGeometry.face_count,
      watertight: costGeometry.watertight,
    },
    overallVerdict: validation.overall_verdict,
    makeNowProcess: cost.decision.make_now_process,
    positiveEstimateCount: costed.length,
    firstUnitCostUsd: costed[0].unit_cost_usd,
    provenance,
    savedDecisionId: cost.saved.id,
  };
}

/** The lifecycle oracle: API completion alone is insufficient. */
export async function waitForVerificationPipeline(page, { timeoutMs = 135_000 } = {}) {
  const dialog = page.getByRole("dialog", { name: "Verification pipeline", exact: true });
  await dialog.waitFor({ state: "visible", timeout: Math.min(timeoutMs, 15_000) });
  await dialog.waitFor({ state: "hidden", timeout: timeoutMs });
  return { appeared: true, disappeared: true };
}

/** A screenshot is evidence only after initial async cards have left loading copy. */
export async function waitForSettledHome(page, { timeoutMs = 20_000 } = {}) {
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return !/(?:loading…|checking (?:inventory|records|programs|ground truth|machine rates)\.\.\.)/i.test(text);
    },
    undefined,
    { timeout: timeoutMs },
  );
}

function parseArgs(argv) {
  const options = { manifest: null, offline: false, headed: false, materializeOnly: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--manifest") {
      invariant(argv[index + 1], "--manifest requires a path");
      options.manifest = path.resolve(argv[++index]);
    } else if (arg === "--offline") {
      options.offline = true;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--materialize-only") {
      options.materializeOnly = true;
    } else if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  return options;
}

function usage() {
  return `Usage: node scripts/e2e/representative-cad-browser.mjs [options]\n\n` +
    `  --manifest PATH       use an existing materialized manifest\n` +
    `  --offline             forbid public NIST downloads during materialization\n` +
    `  --headed              show the browser\n` +
    `  --materialize-only    verify/materialize fixtures without launching a browser\n`;
}

function pythonExecutable() {
  if (process.env.CADVERIFY_PYTHON) return process.env.CADVERIFY_PYTHON;
  const venvPython = path.join(repoRoot, "backend", ".venv", "bin", "python");
  return existsSync(venvPython) ? venvPython : "python3";
}

function materializeManifest(fixtureDir, offline) {
  const script = path.join(repoRoot, "scripts", "prehuman", "real_cad_corpus.py");
  const args = [script, "--materialize-browser-set", fixtureDir];
  if (offline) args.push("--offline");
  const result = spawnSync(pythonExecutable(), args, {
    cwd: repoRoot,
    encoding: "utf8",
    timeout: Number(process.env.CAD_BROWSER_MATERIALIZE_TIMEOUT_MS || 240_000),
    env: process.env,
  });
  if (result.error) throw new Error(`representative materialization failed: ${result.error.message}`);
  if (result.status !== 0) {
    throw new Error(
      `representative materialization exited ${result.status}: ${(result.stderr || result.stdout || "").slice(-2000)}`,
    );
  }
  const manifestPath = path.join(fixtureDir, "representative-cad-manifest.json");
  invariant(existsSync(manifestPath), `materializer did not emit ${manifestPath}`);
  return manifestPath;
}

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${timeoutMs} ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function responseJson(response, label) {
  try {
    return await response.json();
  } catch (error) {
    const text = await response.text().catch(() => "");
    throw new Error(`${label} did not return JSON: ${text.slice(0, 500)} (${error.message})`);
  }
}

class RepresentativeCadBrowser {
  constructor({ fixtureSet, baseUrl, runId, outputRoot, headed, caseTimeoutMs, totalTimeoutMs }) {
    this.fixtureSet = fixtureSet;
    this.baseUrl = baseUrl;
    this.runId = runId;
    this.outputRoot = outputRoot;
    this.headed = headed;
    this.caseTimeoutMs = caseTimeoutMs;
    this.totalTimeoutMs = totalTimeoutMs;
    this.screenshotDir = path.join(outputRoot, "screenshots", `representative-cad-browser-${runId}`);
    this.artifacts = {
      json: path.join(outputRoot, `representative-cad-browser-${runId}.json`),
      md: path.join(outputRoot, `qa-report-representative-cad-browser-${runId}.md`),
    };
    this.consoleErrors = [];
    this.expectedConsoleDiagnostics = [];
    this.requestFailures = [];
    this.expectedRequestAborts = [];
    this.unexpectedHttpErrors = [];
    this.expectedHttpBoundaries = [];
    this.pageErrors = [];
    this.cases = [];
    this.failures = [];
    this.currentCaseId = null;
    this.shotIndex = 0;
    this.account = null;
    this.startedAt = new Date().toISOString();
  }

  async init() {
    await mkdir(this.screenshotDir, { recursive: true });
    const { chromium } = requireFromFrontend("playwright-core");
    const launch = { headless: !this.headed };
    try {
      this.browser = await chromium.launch({ ...launch, channel: "chrome" });
    } catch {
      this.browser = await chromium.launch(launch);
    }
    const ipOctet = 20 + (randomBytes(1)[0] % 200);
    this.context = await this.browser.newContext({
      baseURL: this.baseUrl,
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      extraHTTPHeaders: { "x-real-ip": `198.51.100.${ipOctet}` },
    });
    this.page = await this.context.newPage();
    this.page.setDefaultTimeout(20_000);
    this.watch(this.page);
  }

  watch(page) {
    page.on("console", (message) => {
      if (message.type() === "error") {
        const item = {
          caseId: this.currentCaseId,
          url: page.url(),
          text: message.text(),
          location: message.location(),
        };
        const diagnosticUrl = item.location?.url || "";
        const expectedHomeRecoveryFailure =
          this.currentCaseId === "HOME-RECOVERY" &&
          /\/api\/proxy\/machine-inventory(?:\?|$)/.test(diagnosticUrl) &&
          /status of 503|Failed to load resource/i.test(item.text);
        if (expectedHomeRecoveryFailure) this.expectedConsoleDiagnostics.push({ ...item, boundary: "home-data-retry" });
        else this.consoleErrors.push(item);
      }
    });
    page.on("pageerror", (error) => {
      const item = { caseId: this.currentCaseId, url: page.url(), text: error.message };
      this.pageErrors.push(item);
      this.consoleErrors.push(item);
    });
    page.on("requestfailed", (request) => {
      const item = {
        caseId: this.currentCaseId,
        url: request.url(),
        method: request.method(),
        resourceType: request.resourceType(),
        error: request.failure()?.errorText || "request failed",
      };
      if (isExpectedNextRscPrefetchAbort(item, this.baseUrl)) this.expectedRequestAborts.push(item);
      else this.requestFailures.push(item);
    });
    page.on("response", (response) => {
      if (response.status() >= 400) {
        const item = {
          caseId: this.currentCaseId,
          url: response.url(),
          method: response.request().method(),
          status: response.status(),
        };
        const expectedHomeRecoveryFailure =
          this.currentCaseId === "HOME-RECOVERY" &&
          item.method === "GET" &&
          responsePath(response) === "/api/proxy/machine-inventory" &&
          item.status === 503;
        if (expectedHomeRecoveryFailure) this.expectedHttpBoundaries.push({ ...item, boundary: "home-data-retry" });
        else this.unexpectedHttpErrors.push(item);
      }
    });
    page.on("crash", () => {
      this.consoleErrors.push({ caseId: this.currentCaseId, url: page.url(), text: "page crashed" });
    });
  }

  offsets() {
    return {
      console: this.consoleErrors.length,
      requests: this.requestFailures.length,
      http: this.unexpectedHttpErrors.length,
    };
  }

  errorsSince(offsets) {
    return {
      consoleErrors: this.consoleErrors.slice(offsets.console),
      requestFailures: this.requestFailures.slice(offsets.requests),
      unexpectedHttpErrors: this.unexpectedHttpErrors.slice(offsets.http),
    };
  }

  assertNoErrorsSince(offsets, label) {
    const errors = this.errorsSince(offsets);
    invariant(errors.consoleErrors.length === 0, `${label} produced console errors: ${JSON.stringify(errors.consoleErrors)}`);
    invariant(errors.requestFailures.length === 0, `${label} produced request failures: ${JSON.stringify(errors.requestFailures)}`);
    invariant(errors.unexpectedHttpErrors.length === 0, `${label} produced unexpected HTTP errors: ${JSON.stringify(errors.unexpectedHttpErrors)}`);
    return errors;
  }

  async screenshot(label, { fullPage = false } = {}) {
    this.shotIndex += 1;
    const filename = path.join(
      this.screenshotDir,
      `${String(this.shotIndex).padStart(2, "0")}-${slug(label)}.png`,
    );
    await this.page.screenshot({
      path: filename,
      fullPage,
      animations: "disabled",
      caret: "initial",
    });
    return filename;
  }

  async signup() {
    this.currentCaseId = "HOME-RECOVERY";
    const offsets = this.offsets();
    const email = `representative-cad-${Date.now()}-${process.pid}-${randomBytes(5).toString("hex")}@example.com`;
    const password = "RepresentativePass123";
    let failureInjected = false;
    const machineRoute = "**/api/proxy/machine-inventory*";
    const injectOneMachineFailure = async (route) => {
      const request = route.request();
      const requestUrl = new URL(request.url());
      if (
        !failureInjected &&
        request.method() === "GET" &&
        requestUrl.pathname === "/api/proxy/machine-inventory"
      ) {
        failureInjected = true;
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Injected one-shot home recovery proof" }),
        });
        return;
      }
      await route.continue();
    };
    await this.context.route(machineRoute, injectOneMachineFailure);
    try {
      await this.page.goto("/signup", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await this.page.getByLabel("Email").fill(email);
      await this.page.getByLabel("Password").fill(password);
      await this.page.getByRole("button", { name: /^Create account$/ }).click();
      await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });
      await this.page.getByText("DAY ZERO SETUP").waitFor({ timeout: 20_000 });

      const recoveryAlert = this.page
        .getByRole("alert")
        .filter({ hasText: /Couldn.*load machine inventory/i });
      await recoveryAlert.waitFor({ state: "visible", timeout: 20_000 });
      invariant(failureInjected, "home recovery proof did not inject the machine-inventory failure");
      await this.page.getByText("MACHINES · RETRY NEEDED", { exact: true }).waitFor({ timeout: 10_000 });
      const failedText = await this.page.locator("body").innerText();
      invariant(!/checking machine rates\.\.\./i.test(failedText), "failed machine inventory remained in a checking state");
      const failureScreenshot = await this.screenshot("fresh-account-home-retry-needed");

      const recoveryResponsePromise = this.page.waitForResponse(
        (response) => isResponse(response, "GET", "/api/proxy/machine-inventory") && response.status() === 200,
        { timeout: 20_000 },
      );
      await this.page.getByRole("button", { name: "Retry organization data", exact: true }).click();
      const recoveryResponse = await recoveryResponsePromise;
      await recoveryAlert.waitFor({ state: "hidden", timeout: 20_000 });
      await waitForSettledHome(this.page, { timeoutMs: 20_000 });
      const screenshot = await this.screenshot("fresh-account-recovered");
      const errors = this.assertNoErrorsSince(offsets, "fresh-account signup and home recovery");
      this.account = {
        email,
        createdViaRealSignup: true,
        screenshot,
        errors,
        homeEndpointRecovery: {
          endpoint: "/api/proxy/machine-inventory",
          injectedStatus: 503,
          failurePresentedAsEmpty: false,
          retryResponseStatus: recoveryResponse.status(),
          recovered: true,
          screenshots: { retryNeeded: failureScreenshot, recovered: screenshot },
        },
      };
    } finally {
      await this.context.unroute(machineRoute, injectOneMachineFailure);
    }
  }

  async openVerify() {
    if (new URL(this.page.url()).pathname !== "/verify") {
      await this.page.goto("/verify", { waitUntil: "domcontentloaded", timeout: 30_000 });
    }
    await this.page.getByRole("button", { name: "Verify", exact: true }).click();
    await this.page.getByTestId("verify-part-cad-input").waitFor({ state: "attached" });
  }

  async runSupportedCaseCore(fixture) {
    this.currentCaseId = fixture.id;
    const offsets = this.offsets();
    await this.openVerify();
    const input = this.page.getByTestId("verify-part-cad-input");
    const accept = await input.getAttribute("accept");
    invariant(accept?.toLowerCase().includes(path.extname(fixture.filename).toLowerCase()), `${fixture.id} real Verify control does not accept ${fixture.filename}`);

    const validationPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate"),
      { timeout: this.caseTimeoutMs },
    );
    const costPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate/cost"),
      { timeout: this.caseTimeoutMs },
    );
    const assemblyPromise = this.page.waitForResponse(
      (response) => isResponse(response, "POST", "/api/proxy/validate/assembly"),
      { timeout: this.caseTimeoutMs },
    );
    const pipelinePromise = waitForVerificationPipeline(this.page, { timeoutMs: this.caseTimeoutMs });
    const started = Date.now();
    await input.setInputFiles(fixture.absolutePath);
    const [validationResponse, costResponse, assemblyResponse, pipeline] = await Promise.all([
      validationPromise,
      costPromise,
      assemblyPromise,
      pipelinePromise,
    ]);
    invariant(validationResponse.status() === 200, `${fixture.id} validation returned HTTP ${validationResponse.status()}`);
    invariant(costResponse.status() === 200, `${fixture.id} cost returned HTTP ${costResponse.status()}`);
    const [validation, cost] = await Promise.all([
      responseJson(validationResponse, `${fixture.id} validation`),
      responseJson(costResponse, `${fixture.id} cost`),
    ]);
    const assemblyBody = await responseJson(assemblyResponse, `${fixture.id} assembly classification`);
    invariant(assemblyResponse.status() === 200, `${fixture.id} assembly classification returned HTTP ${assemblyResponse.status()}`);
    invariant(assemblyBody.kind === "single_part", `${fixture.id} classified as ${assemblyBody.kind}, not a single part`);
    invariant(assemblyBody.part_count === 1, `${fixture.id} assembly probe found ${assemblyBody.part_count} parts`);
    const assemblyProbe = { status: 200, classification: "single_part", partCount: 1 };

    await this.page.getByText("What it really takes", { exact: true }).waitFor({ timeout: 20_000 });
    const visibleText = await this.page.locator("body").innerText();
    const truth = assertTruthfulTerminalCase({ fixture, validation, cost, visibleText });
    const terminalScreenshot = await this.screenshot(`${fixture.id}-terminal`);

    const expectedDisposition = dispositionForCost(cost);
    const disposition = this.page.getByTestId(`verify-disposition-${expectedDisposition.key}`);
    await disposition.scrollIntoViewIfNeeded();
    await disposition.waitFor({ state: "visible", timeout: 20_000 });
    await this.page.getByTestId("verify-disposition-status").filter({ hasText: /next → pick one above/i }).waitFor({ timeout: 20_000 });
    const dispositionResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "PUT", `/api/proxy/cost-decisions/${truth.savedDecisionId}/disposition`),
      { timeout: 20_000 },
    );
    await disposition.click();
    const dispositionResponse = await dispositionResponsePromise;
    invariant(dispositionResponse.status() === 200, `${fixture.id} disposition returned HTTP ${dispositionResponse.status()}`);
    await this.page.getByTestId("verify-disposition-status").filter({ hasText: `✓ ${expectedDisposition.label} — recorded` }).waitFor({ timeout: 20_000 });
    invariant((await disposition.getAttribute("aria-pressed")) === "true", `${fixture.id} disposition is not visibly selected`);
    const decisionScreenshot = await this.screenshot(`${fixture.id}-decision`);

    // A refresh destroys the in-memory Verify result.  Records must rebuild the
    // exact artifact and user disposition from durable backend state.
    await this.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    await this.page.getByRole("button", { name: "Records", exact: true }).click();
    await this.page.getByRole("heading", { name: "Records", exact: true }).waitFor({ timeout: 20_000 });
    const recordName = this.page.getByText(fixture.filename, { exact: true }).first();
    await recordName.waitFor({ timeout: 20_000 });
    const recordResponsePromise = this.page.waitForResponse(
      (response) => isResponse(response, "GET", `/api/proxy/cost-decisions/${truth.savedDecisionId}`),
      { timeout: 20_000 },
    );
    await recordName.click();
    const recordResponse = await recordResponsePromise;
    invariant(recordResponse.status() === 200, `${fixture.id} Records detail returned HTTP ${recordResponse.status()}`);
    const record = await responseJson(recordResponse, `${fixture.id} Records detail`);
    invariant(record.id === truth.savedDecisionId, `${fixture.id} Records reopened ${record.id}, expected ${truth.savedDecisionId}`);
    invariant(record.filename === fixture.filename, `${fixture.id} Records filename changed to ${record.filename}`);
    invariant(record.user_disposition === expectedDisposition.key, `${fixture.id} durable disposition was ${record.user_disposition}`);
    const recordSummary = this.page.getByTestId("record-disposition-summary");
    await recordSummary.getByText(expectedDisposition.label, { exact: true }).waitFor({ timeout: 20_000 });
    const governanceLink = recordSummary.locator(`a[href="/cost-decisions/${truth.savedDecisionId}"]`);
    invariant((await governanceLink.count()) === 1, `${fixture.id} Records did not reopen the exact saved decision id`);
    const recordsScreenshot = await this.screenshot(`${fixture.id}-records-after-refresh`);

    const errors = this.assertNoErrorsSince(offsets, fixture.id);
    return {
      id: fixture.id,
      status: "PASS",
      supportStatus: fixture.support_status,
      expectedOutcome: fixture.expected_browser_outcome,
      filename: fixture.filename,
      fixtureSha256: fixture.file_sha256,
      fixtureBytes: fixture.bytes,
      coverageTags: fixture.coverage_tags,
      source: fixture.source,
      elapsedMs: Date.now() - started,
      pipeline,
      assemblyProbe,
      http: {
        assemblyClassification: assemblyResponse.status(),
        validation: validationResponse.status(),
        cost: costResponse.status(),
        disposition: dispositionResponse.status(),
        recordsDetail: recordResponse.status(),
      },
      ...truth,
      durableDecision: {
        id: record.id,
        filename: record.filename,
        userDisposition: record.user_disposition,
        userDispositionLabel: expectedDisposition.label,
        reopenedAfterRefresh: true,
      },
      screenshots: {
        terminal: terminalScreenshot,
        decision: decisionScreenshot,
        recordsAfterRefresh: recordsScreenshot,
      },
      errors,
    };
  }

  async runSupportedCase(fixture) {
    try {
      const result = await withTimeout(
        this.runSupportedCaseCore(fixture),
        this.caseTimeoutMs,
        fixture.id,
      );
      this.cases.push(result);
    } catch (error) {
      const screenshot = await this.screenshot(`${fixture.id}-failure`).catch(() => null);
      const failure = {
        id: fixture.id,
        status: "FAIL",
        supportStatus: fixture.support_status,
        expectedOutcome: fixture.expected_browser_outcome,
        filename: fixture.filename,
        fixtureSha256: fixture.file_sha256,
        fixtureBytes: fixture.bytes,
        coverageTags: fixture.coverage_tags,
        error: error instanceof Error ? error.message : String(error),
        screenshot,
      };
      this.cases.push(failure);
      this.failures.push({ id: fixture.id, error: failure.error });
      await this.page.goto("/verify", { waitUntil: "domcontentloaded", timeout: 30_000 }).catch(() => {});
    }
  }

  async verifyUnsupportedControl(fixture) {
    this.currentCaseId = fixture.id;
    const offsets = this.offsets();
    const computeRequests = [];
    const onRequest = (request) => {
      const url = new URL(request.url());
      if (
        request.method() === "POST" &&
        /^\/api\/proxy\/validate(?:\/assembly|\/cost)?\/?$/.test(url.pathname)
      ) {
        computeRequests.push({ method: request.method(), path: url.pathname });
      }
    };
    this.page.on("request", onRequest);
    try {
      await this.openVerify();
      const input = this.page.getByTestId("verify-part-cad-input");
      const accept = (await input.getAttribute("accept")) || "";
      const suffix = path.extname(fixture.filename).toLowerCase();
      invariant(!accept.toLowerCase().split(",").includes(suffix), `${fixture.id} native assembly unexpectedly appears in Verify accept list`);
      await input.setInputFiles(fixture.absolutePath);
      const rejection = this.page.getByTestId("verify-upload-rejection");
      await rejection.waitFor({ state: "visible", timeout: 10_000 });
      const rejectionText = (await rejection.innerText()).replace(/\s+/g, " ").trim();
      invariant(rejectionText.includes(fixture.filename), `${fixture.id} rejection does not name the selected file`);
      invariant(/SolidWorks files need a STEP export/i.test(rejectionText), `${fixture.id} rejection does not identify the native format boundary`);
      invariant(/STEP AP242 \(\.step or \.stp\)/i.test(rejectionText), `${fixture.id} rejection has no actionable neutral-export path`);
      invariant(/No analysis was started and no record was created/i.test(rejectionText), `${fixture.id} rejection does not state the persistence boundary`);
      await this.page.waitForTimeout(300);
      invariant(computeRequests.length === 0, `${fixture.id} unsupported selection reached compute: ${JSON.stringify(computeRequests)}`);
      const screenshot = await this.screenshot(`${fixture.id}-unsupported-control`);
      const errors = this.assertNoErrorsSince(offsets, fixture.id);
      this.cases.push({
        id: fixture.id,
        status: "EXPECTED_UNSUPPORTED",
        supportStatus: fixture.support_status,
        expectedOutcome: fixture.expected_browser_outcome,
        filename: fixture.filename,
        fixtureSha256: fixture.file_sha256,
        fixtureBytes: fixture.bytes,
        coverageTags: fixture.coverage_tags,
        source: fixture.source,
        browserAccept: accept,
        selectionAttempted: true,
        networkUploadAttempted: false,
        computeRequests,
        successClaimed: false,
        visibleGuidance: rejectionText,
        reason: "The real browser selection was rejected before network compute and gave the user a STEP AP242 export path; no verification, geometry, cost, or saved record is claimed.",
        screenshot,
        errors,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.cases.push({
        id: fixture.id,
        status: "FAIL",
        supportStatus: fixture.support_status,
        expectedOutcome: fixture.expected_browser_outcome,
        filename: fixture.filename,
        fixtureSha256: fixture.file_sha256,
        error: message,
      });
      this.failures.push({ id: fixture.id, error: message });
    } finally {
      this.page.off("request", onRequest);
    }
  }

  async run() {
    await this.signup();
    for (const fixture of this.fixtureSet.supported) {
      await this.runSupportedCase(fixture);
    }
    await this.verifyUnsupportedControl(this.fixtureSet.unsupported[0]);
  }

  buildIdentity() {
    const identity = captureBuildIdentity(repoRoot);
    let dirtyPaths = [];
    try {
      dirtyPaths = execFileSync("git", ["status", "--porcelain", "--untracked-files=all"], {
        cwd: repoRoot,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      }).trim().split("\n").filter(Boolean);
    } catch {}
    return {
      ...identity,
      dirtyPaths,
      runnerSha256: sha256Bytes(readFileSync(__filename)),
      corpusScriptSha256: sha256Bytes(readFileSync(path.join(repoRoot, "scripts", "prehuman", "real_cad_corpus.py"))),
    };
  }

  result() {
    const supportedComplete = this.fixtureSet.supported.every((fixture) =>
      this.cases.some((item) => item.id === fixture.id && item.status === "PASS" && item.durableDecision?.reopenedAfterRefresh === true)
    );
    const unsupportedTruthful = this.fixtureSet.unsupported.every((fixture) =>
      this.cases.some((item) => item.id === fixture.id && item.status === "EXPECTED_UNSUPPORTED" && item.successClaimed === false)
    );
    const clean = this.consoleErrors.length === 0 && this.requestFailures.length === 0 && this.unexpectedHttpErrors.length === 0;
    const accountReady =
      this.account?.createdViaRealSignup === true &&
      this.account?.homeEndpointRecovery?.recovered === true &&
      this.account?.homeEndpointRecovery?.failurePresentedAsEmpty === false;
    const status = accountReady && supportedComplete && unsupportedTruthful && clean && this.failures.length === 0 ? "PASS" : "FAIL";
    return {
      schemaVersion: 1,
      status,
      runId: this.runId,
      startedAt: this.startedAt,
      generatedAt: new Date().toISOString(),
      appUrl: this.baseUrl,
      credentialBoundary: "No cloud credentials are read or required; account creation and every supported upload use the real browser UI.",
      runtimeBounds: {
        representativeSupportedCaseCap: MAX_SUPPORTED_CASES,
        selectedSupportedCases: this.fixtureSet.supported.length,
        perCaseTimeoutMs: this.caseTimeoutMs,
        totalTimeoutMs: this.totalTimeoutMs,
        exhaustiveCorpusRemainsIn: "scripts/prehuman/real_cad_corpus.py",
      },
      buildIdentity: this.buildIdentity(),
      fixtureManifest: {
        path: this.fixtureSet.manifestPath,
        sha256: this.fixtureSet.manifestSha256,
        setId: this.fixtureSet.manifest.set_id,
        fixtureSetSha256: this.fixtureSet.manifest.fixture_set_sha256,
        sourceArchives: this.fixtureSet.manifest.source_archives,
        omissions: this.fixtureSet.manifest.omissions,
      },
      exactFixtureHashes: this.fixtureSet.fixtures.map((fixture) => ({
        id: fixture.id,
        filename: fixture.filename,
        sha256: fixture.file_sha256,
        bytes: fixture.bytes,
        supportStatus: fixture.support_status,
        coverageTags: fixture.coverage_tags,
      })),
      account: this.account ? { ...this.account, password: undefined } : null,
      cases: this.cases,
      acceptance: {
        freshAccountCreated: Boolean(this.account?.createdViaRealSignup),
        homeEndpointFailureRecovered: Boolean(this.account?.homeEndpointRecovery?.recovered),
        homeEndpointFailureWasNotPresentedAsEmpty: this.account?.homeEndpointRecovery?.failurePresentedAsEmpty === false,
        allSupportedCasesTerminalAndSaved: supportedComplete,
        nativeAssemblyTruthfullyUnsupported: unsupportedTruthful,
        zeroConsoleErrors: this.consoleErrors.length === 0,
        zeroRequestFailures: this.requestFailures.length === 0,
        zeroUnexpectedHttpErrors: this.unexpectedHttpErrors.length === 0,
        expectedFallbackBoundariesClassified: this.expectedHttpBoundaries.every((item) =>
          (item.boundary === "home-data-retry" && item.status === 503 && item.method === "GET" && /\/machine-inventory/.test(item.url))
        ),
      },
      consoleErrors: this.consoleErrors,
      expectedConsoleDiagnostics: this.expectedConsoleDiagnostics,
      requestFailures: this.requestFailures,
      expectedRequestAborts: this.expectedRequestAborts,
      unexpectedHttpErrors: this.unexpectedHttpErrors,
      expectedHttpBoundaries: this.expectedHttpBoundaries,
      failures: this.failures,
      screenshotDir: this.screenshotDir,
      artifacts: this.artifacts,
    };
  }

  async writeReport(data) {
    await mkdir(this.outputRoot, { recursive: true });
    await writeFile(this.artifacts.json, `${JSON.stringify(data, null, 2)}\n`, "utf8");
    const fixtureRows = data.exactFixtureHashes.map((fixture) =>
      `| ${fixture.supportStatus === "supported" ? "SUPPORTED" : "UNSUPPORTED CONTROL"} | ${fixture.id} | \`${fixture.sha256}\` | ${fixture.bytes} | ${fixture.filename} |`
    ).join("\n");
    const caseRows = data.cases.map((item) => {
      const screenshot = item.screenshots?.recordsAfterRefresh || item.screenshots?.terminal || item.screenshot || "—";
      const evidence = item.status === "PASS"
        ? `${item.costGeometry.volumeCm3} cm³ · ${item.firstUnitCostUsd} USD/unit · ${item.savedDecisionId}`
        : item.reason || item.error || "—";
      return `| ${item.status} | ${item.id} | ${String(evidence).replaceAll("|", "\\|")} | ${screenshot} |`;
    }).join("\n");
    const omissionRows = data.fixtureManifest.omissions.length > 0
      ? data.fixtureManifest.omissions.map((item) =>
          `| ${item.id} | ${item.candidate_sha256 ? `\`${item.candidate_sha256}\`` : "—"} | ${String(item.reason).replaceAll("|", "\\|")} |`
        ).join("\n")
      : "| none | — | all optional fixtures passed feasibility |";
    const markdown = `# Current-build representative CAD browser report\n\n` +
      `- Run: ${data.runId}\n` +
      `- Status: ${data.status}\n` +
      `- Build commit: \`${data.buildIdentity.gitHead}\`\n` +
      `- Build id: \`${data.buildIdentity.buildId}\` (${data.buildIdentity.buildIdSource})\n` +
      `- Git dirty: ${data.buildIdentity.gitDirty}\n` +
      `- Fixture-set binding: \`${data.fixtureManifest.fixtureSetSha256}\`\n` +
      `- Manifest SHA-256: \`${data.fixtureManifest.sha256}\`\n` +
      `- Fresh account: ${data.account?.email || "not created"}\n` +
      `- Console errors: ${data.consoleErrors.length}\n` +
      `- Expected classified boundary diagnostics: ${data.expectedConsoleDiagnostics.length}\n` +
      `- Request failures: ${data.requestFailures.length}\n` +
      `- Unexpected HTTP errors: ${data.unexpectedHttpErrors.length}\n\n` +
      `## Exact fixtures\n\n` +
      `| Boundary | Fixture | SHA-256 | Bytes | File |\n| --- | --- | --- | ---: | --- |\n${fixtureRows}\n\n` +
      `## Optional fixture feasibility\n\n` +
      `| Candidate | Candidate SHA-256 | Outcome |\n| --- | --- | --- |\n${omissionRows}\n\n` +
      `## Browser outcomes\n\n` +
      `| Result | Case | Terminal/durable evidence | Screenshot |\n| --- | --- | --- | --- |\n${caseRows}\n\n` +
      `## Acceptance\n\n\`\`\`json\n${JSON.stringify(data.acceptance, null, 2)}\n\`\`\`\n`;
    await writeFile(this.artifacts.md, markdown, "utf8");
  }

  async close() {
    await this.context?.close().catch(() => {});
    await this.browser?.close().catch(() => {});
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(usage());
    return;
  }
  const runId = process.env.E2E_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");
  const outputRoot = process.env.E2E_ARTIFACT_DIR
    ? path.resolve(process.env.E2E_ARTIFACT_DIR)
    : path.join(repoRoot, ".gstack", "qa-reports");
  const fixtureDir = path.join(outputRoot, "representative-cad-fixtures", runId);
  const manifestPath = options.manifest || materializeManifest(fixtureDir, options.offline);
  const fixtureSet = loadRepresentativeManifest(manifestPath);
  if (options.materializeOnly) {
    process.stdout.write(`${JSON.stringify({
      status: "PASS",
      manifest: fixtureSet.manifestPath,
      manifestSha256: fixtureSet.manifestSha256,
      fixtureSetSha256: fixtureSet.manifest.fixture_set_sha256,
      fixtures: fixtureSet.fixtures.map((fixture) => ({
        id: fixture.id,
        filename: fixture.filename,
        sha256: fixture.file_sha256,
        bytes: fixture.bytes,
        supportStatus: fixture.support_status,
      })),
    }, null, 2)}\n`);
    return;
  }

  const baseUrl = process.env.APP_URL || "http://localhost:3000";
  const caseTimeoutMs = Number(process.env.CAD_BROWSER_CASE_TIMEOUT_MS || 135_000);
  const totalTimeoutMs = Number(process.env.CAD_BROWSER_TOTAL_TIMEOUT_MS || 12 * 60_000);
  invariant(Number.isFinite(caseTimeoutMs) && caseTimeoutMs >= 30_000, "CAD_BROWSER_CASE_TIMEOUT_MS must be at least 30000");
  invariant(Number.isFinite(totalTimeoutMs) && totalTimeoutMs >= caseTimeoutMs, "CAD_BROWSER_TOTAL_TIMEOUT_MS must cover one case");
  const runner = new RepresentativeCadBrowser({
    fixtureSet,
    baseUrl,
    runId,
    outputRoot,
    headed: options.headed,
    caseTimeoutMs,
    totalTimeoutMs,
  });

  let data;
  try {
    await runner.init();
    await withTimeout(runner.run(), totalTimeoutMs, "representative CAD browser run");
  } catch (error) {
    runner.failures.push({ id: runner.currentCaseId || "RUNNER", error: error instanceof Error ? error.message : String(error) });
  } finally {
    data = runner.result();
    await runner.writeReport(data);
    await runner.close();
  }

  process.stdout.write(`${JSON.stringify({
    status: data.status,
    cases: data.cases.map((item) => ({ id: item.id, status: item.status })),
    fixtureSetSha256: data.fixtureManifest.fixtureSetSha256,
    consoleErrors: data.consoleErrors.length,
    requestFailures: data.requestFailures.length,
    unexpectedHttpErrors: data.unexpectedHttpErrors.length,
    expectedHttpBoundaries: data.expectedHttpBoundaries.length,
    report: data.artifacts.md,
    json: data.artifacts.json,
  }, null, 2)}\n`);
  if (data.status !== "PASS") process.exitCode = 1;
}

const invokedAsScript = process.argv[1] && path.resolve(process.argv[1]) === __filename;
if (invokedAsScript) {
  await main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
