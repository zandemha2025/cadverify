import { createHash, randomBytes } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  makeGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";
import { configuredClientIp } from "./run-scoped-client-ip.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const runId = process.env.E2E_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");
const clientIp = configuredClientIp(runId, "batch-design-recovery");
const faultToken = process.env.E2E_FAULT_INJECTION_TOKEN || "";
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(outputRoot, "screenshots", `batch-design-recovery-${runId}`);
const reportPath = path.join(outputRoot, `batch-design-recovery-${runId}.json`);
const trackedCubeFixture = path.join(repoRoot, "backend", "tests", "assets", "cube.step");

const OWNED_PATH_IDS = ["WORK-03", "WORK-04", "FAIL-04", "FAIL-05", "FAIL-06", "FAIL-07"];
const CSV_HEADER = "filename,status,verdict,best_process,issue_count,duration_ms,analysis_url,error";
const DESIGN_QUEUE_COPY = "Design generation is temporarily unavailable. Retry shortly.";
const CAD_KERNEL_COPY = "The CAD kernel could not generate this revision. Check the dimensions and retry.";
const OBJECT_STORE_COPY = "The generated files could not be stored. Retry this revision.";
const BATCH_QUEUE_COPY = "Batch was accepted but could not be scheduled (job queue unavailable). It has been marked failed; please retry.";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertion(name, expected, actual, pass = expected === actual) {
  return { name, expected, actual, pass };
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

async function writeDeterministicStoredZip(sourcePath, destinationPath, entryNames) {
  const data = await readFile(sourcePath);
  const locals = [];
  const centrals = [];
  let localOffset = 0;

  for (const entryName of entryNames) {
    const name = Buffer.from(entryName, "utf8");
    const checksum = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(0x21, 12);
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    const localRecord = Buffer.concat([local, name, data]);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(0x21, 14);
    central.writeUInt32LE(checksum, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(0, 38);
    central.writeUInt32LE(localOffset, 42);
    const centralRecord = Buffer.concat([central, name]);

    locals.push(localRecord);
    centrals.push(centralRecord);
    localOffset += localRecord.length;
  }

  const centralBytes = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entryNames.length, 8);
  end.writeUInt16LE(entryNames.length, 10);
  end.writeUInt32LE(centralBytes.length, 12);
  end.writeUInt32LE(localOffset, 16);
  end.writeUInt16LE(0, 20);
  const archive = Buffer.concat([...locals, centralBytes, end]);
  await writeFile(destinationPath, archive);
  return {
    path: destinationPath,
    entries: entryNames,
    source: sourcePath,
    bytes: archive.length,
    sha256: createHash("sha256").update(archive).digest("hex"),
  };
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  const headers = rows.shift() || [];
  return {
    headers,
    records: rows.filter((values) => values.some(Boolean)).map((values) =>
      Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])),
    ),
  };
}

async function inPageProxyFetch(page, pathname, options = {}) {
  assert(
    typeof pathname === "string" &&
      pathname.startsWith("/api/proxy/") &&
      !pathname.startsWith("//"),
    "in-page proxy fetch requires an absolute same-origin /api/proxy path",
  );
  const method = String(options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  return page.evaluate(
    async ({ pathname, method, headers, json, hasJson, responseType }) => {
      let body;
      if (hasJson) {
        headers["content-type"] = headers["content-type"] || "application/json";
        body = JSON.stringify(json);
      }
      const response = await fetch(pathname, {
        method,
        headers,
        body,
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
      });
      const buffer = await response.arrayBuffer();
      let text = null;
      let parsed = null;
      if (responseType !== "bytes") {
        text = new TextDecoder().decode(buffer);
        parsed = text;
        if (responseType === "json") {
          try {
            parsed = text ? JSON.parse(text) : null;
          } catch {
            // Keep the exact body so failed setup/assertion calls stay diagnosable.
          }
        }
      }
      return {
        ok: response.ok,
        status: response.status,
        body: parsed,
        text,
        byteLength: buffer.byteLength,
        headers: Object.fromEntries(response.headers.entries()),
      };
    },
    {
      pathname,
      method,
      headers,
      json: options.json,
      hasJson: Object.prototype.hasOwnProperty.call(options, "json"),
      responseType: options.responseType || "json",
    },
  );
}

function directUploadRequestKey(request) {
  if (request.method() !== "PUT") return null;
  const url = new URL(request.url());
  if (!(
    url.origin !== new URL(baseUrl).origin &&
    url.pathname.includes("/direct-uploads/") &&
    url.searchParams.has("uploadId") &&
    url.searchParams.has("partNumber")
  )) return null;
  return [
    url.origin,
    url.pathname,
    url.searchParams.get("uploadId"),
    url.searchParams.get("partNumber"),
  ].join("|");
}

function isRecoverableDirectUploadAbort(request, failure) {
  return failure === "net::ERR_ABORTED" && directUploadRequestKey(request) !== null;
}

function directUploadAbortEvidence(request, failure) {
  const url = new URL(request.url());
  return {
    key: directUploadRequestKey(request),
    recoveredStatus: null,
    evidence: {
      method: request.method(),
      origin: url.origin,
      partNumber: url.searchParams.get("partNumber"),
      error: failure,
    },
  };
}

class BatchDesignRecoveryMatrix {
  constructor() {
    this.email = `batch-design-${Date.now()}-${randomBytes(3).toString("hex")}@example.test`;
    this.password = "BatchDesign2026!";
    this.goldenPaths = {};
    this.steps = [];
    this.issues = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.unexpectedHttpResponses = [];
    this.expectedDiagnostics = [];
    this.expectedHttpStatuses = new Set();
    this.pendingDirectUploadAborts = [];
    this.successfulDirectUploadParts = new Map();
    this.artifacts = { failureScreenshots: {}, recoveryScreenshots: {}, downloads: {} };
    this.fixtures = {};
    this.postCounts = { design: 0, batch: 0 };
    this.buildIdentityAtStart = captureBuildIdentity(repoRoot);
  }

  async launch() {
    this.browser = await chromium.launch({
      channel: "chrome",
      headless: true,
      args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
    });
    this.context = await this.browser.newContext({
      baseURL: baseUrl,
      extraHTTPHeaders: { "x-real-ip": clientIp },
      viewport: { width: 1440, height: 1000 },
      acceptDownloads: true,
    });
    this.page = await this.context.newPage();
    this.attachDiagnostics();
  }

  attachDiagnostics() {
    this.page.on("console", (message) => {
      if (message.type() !== "error") return;
      const value = message.text();
      if (/favicon\.ico|vercel\/speed-insights|_next\/webpack-hmr/i.test(value)) return;
      const status = Number(value.match(/status of (\d{3})/i)?.[1]);
      if (status && this.expectedHttpStatuses.has(status)) {
        this.expectedDiagnostics.push(value);
        return;
      }
      this.consoleErrors.push(value);
    });
    this.page.on("pageerror", (error) => this.consoleErrors.push(error.message));
    this.page.on("requestfailed", (request) => {
      const failure = request.failure()?.errorText || "request failed";
      const url = request.url();
      if (/favicon\.ico|vercel\/speed-insights|_next\/webpack-hmr/i.test(url)) return;
      if (failure === "net::ERR_ABORTED" && /[?&]_rsc=/.test(url)) return;
      if (failure === "net::ERR_ABORTED" && request.method() === "GET" && /\/api\/proxy\/batches\?limit=20$/.test(url)) return;
      if (failure === "net::ERR_ABORTED" && request.method() === "GET" && /(?:\/results\/csv|\/download\.step)(?:\?|$)/.test(url)) return;
      if (isRecoverableDirectUploadAbort(request, failure)) {
        const evidence = directUploadAbortEvidence(request, failure);
        evidence.recoveredStatus = this.successfulDirectUploadParts.get(evidence.key) ?? null;
        this.pendingDirectUploadAborts.push(evidence);
        return;
      }
      this.requestFailures.push({ method: request.method(), url, error: failure });
    });
    this.page.on("response", (response) => {
      const status = response.status();
      const directUploadKey = directUploadRequestKey(response.request());
      if (directUploadKey && status >= 200 && status < 300) {
        this.successfulDirectUploadParts.set(directUploadKey, status);
        for (const pending of this.pendingDirectUploadAborts) {
          if (pending.key === directUploadKey && pending.recoveredStatus == null) {
            pending.recoveredStatus = status;
          }
        }
      }
      if (status < 400) return;
      const url = response.url();
      if (!url.startsWith(baseUrl) || /favicon\.ico/.test(url)) return;
      if (this.expectedHttpStatuses.has(status)) return;
      this.unexpectedHttpResponses.push({ status, url, method: response.request().method() });
    });
    this.page.on("request", (request) => {
      if (request.method() !== "POST") return;
      const pathname = new URL(request.url()).pathname;
      if (pathname === "/api/proxy/designs" || /\/api\/proxy\/designs\/[^/]+\/revisions$/.test(pathname)) {
        this.postCounts.design += 1;
      }
      if (pathname === "/api/proxy/batch") this.postCounts.batch += 1;
    });
  }

  confirmRecoveredDirectUploads(pathId) {
    const unrecovered = this.pendingDirectUploadAborts.filter(
      (failure) => failure.recoveredStatus == null,
    );
    assert(
      unrecovered.length === 0,
      `${pathId} had ${unrecovered.length} aborted direct-upload PUT request(s) without a matching successful HTTP response`,
    );
    for (const failure of this.pendingDirectUploadAborts.splice(0)) {
      this.expectedDiagnostics.push({
        ...failure.evidence,
        recovery: `${pathId} observed HTTP ${failure.recoveredStatus} for the exact multipart part before or after Chromium aborted the now-unneeded response body`,
      });
    }
  }

  rejectUnconfirmedDirectUploads() {
    for (const failure of this.pendingDirectUploadAborts.splice(0)) {
      this.requestFailures.push({
        ...failure.evidence,
        error: `${failure.evidence.error} without a matching successful multipart HTTP response`,
      });
    }
  }

  async screenshot(id, suffix) {
    const file = path.join(screenshotDir, `${id.toLowerCase()}-${suffix}.png`);
    await this.page.screenshot({ path: file, fullPage: true });
    return file;
  }

  async json(pathname) {
    const response = await inPageProxyFetch(this.page, pathname);
    assert(
      response.ok,
      `GET ${pathname} returned ${response.status}: ${response.text}`,
    );
    return response.body;
  }

  async designList() {
    return (await this.json("/api/proxy/designs")).designs;
  }

  async getDesign(designId) {
    return (await this.json(`/api/proxy/designs/${designId}`)).design;
  }

  async getRevisions(designId) {
    return (await this.json(`/api/proxy/designs/${designId}/revisions`)).revisions;
  }

  async batchList() {
    return (await this.json("/api/proxy/batches?limit=100")).batches;
  }

  async getBatch(batchId) {
    return this.json(`/api/proxy/batch/${batchId}`);
  }

  async getBatchItems(batchId) {
    const payload = await this.json(`/api/proxy/batch/${batchId}/items?limit=200`);
    assert(payload.has_more === false, `${batchId} unexpectedly exceeded one 200-item evidence page`);
    return payload.items;
  }

  async waitForBatch(batchId, predicate, label, timeout = 120_000) {
    const deadline = Date.now() + timeout;
    let latest = null;
    while (Date.now() < deadline) {
      latest = await this.getBatch(batchId);
      if (predicate(latest)) return latest;
      await this.page.waitForTimeout(300);
    }
    throw new Error(`${label} timed out; latest=${JSON.stringify(latest)}`);
  }

  async waitForDesign(designId, predicate, label, timeout = 150_000) {
    const deadline = Date.now() + timeout;
    let latest = null;
    while (Date.now() < deadline) {
      latest = await this.getDesign(designId);
      if (predicate(latest)) return latest;
      await this.page.waitForTimeout(400);
    }
    throw new Error(`${label} timed out; latest=${JSON.stringify(latest)}`);
  }

  async withExpectedStatus(status, work) {
    this.expectedHttpStatuses.add(status);
    try {
      return await work();
    } finally {
      this.expectedHttpStatuses.delete(status);
    }
  }

  async faultedPost(pattern, mode, expectedStatus, action) {
    let injected = 0;
    const handler = async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      injected += 1;
      await route.continue({
        headers: {
          ...route.request().headers(),
          "x-proofshape-e2e-token": faultToken,
          "x-proofshape-e2e-fault": mode,
        },
      });
    };
    await this.page.route(pattern, handler);
    try {
      const result = await this.withExpectedStatus(expectedStatus, action);
      assert(injected === 1, `${mode} should inject exactly one POST, observed ${injected}`);
      return result;
    } finally {
      await this.page.unroute(pattern, handler);
    }
  }

  async runPath(id, work) {
    const startedAt = Date.now();
    const offsets = {
      console: this.consoleErrors.length,
      request: this.requestFailures.length,
      http: this.unexpectedHttpResponses.length,
    };
    try {
      const result = await work();
      this.confirmRecoveredDirectUploads(id);
      const consoleErrors = this.consoleErrors.slice(offsets.console);
      const requestFailures = this.requestFailures.slice(offsets.request);
      const httpFailures = this.unexpectedHttpResponses.slice(offsets.http);
      assert(consoleErrors.length === 0, `${id} console errors: ${JSON.stringify(consoleErrors)}`);
      assert(requestFailures.length === 0, `${id} request failures: ${JSON.stringify(requestFailures)}`);
      assert(httpFailures.length === 0, `${id} unexpected HTTP responses: ${JSON.stringify(httpFailures)}`);
      assert(result.assertions.length > 0, `${id} has no field-level assertions`);
      for (const check of result.assertions) {
        assert(check.pass === true, `${id} assertion failed: ${check.name}; expected=${check.expected}; actual=${check.actual}`);
      }
      const envelope = makeGoldenPathEvidence({
        id,
        status: "PASS",
        persona: result.persona,
        preconditions: result.preconditions,
        actions: result.actions,
        observed: result.observed,
        screenshot: result.screenshot,
        consoleErrors,
        requestFailures,
        assertions: result.assertions,
      });
      this.goldenPaths[id] = {
        ...envelope,
        screenshotPath: result.screenshot,
        persistedOutcome: result.observed.persisted,
        numericOrAuthorizationOutcome: `${result.observed.numeric}; ${result.observed.authorization}`,
        recoveryResult: result.observed.recovery,
        consoleErrorCount: 0,
        requestFailureCount: 0,
      };
      this.steps.push({ id, status: "PASS", durationMs: Date.now() - startedAt, screenshot: result.screenshot });
      return result;
    } catch (error) {
      this.rejectUnconfirmedDirectUploads();
      const message = error instanceof Error ? error.message : String(error);
      const screenshot = await this.screenshot(id, "failure-unexpected").catch(() => null);
      this.issues.push({ id, message, screenshot });
      this.steps.push({ id, status: "FAIL", durationMs: Date.now() - startedAt, screenshot, error: message });
      return null;
    }
  }

  async signup() {
    await this.page.goto("/signup", { waitUntil: "domcontentloaded" });
    await this.page.getByLabel("Email").fill(this.email);
    await this.page.getByLabel("Password").fill(this.password);
    await this.page.getByRole("button", { name: /^Create account$/ }).click();
    await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 30_000 });
    await this.page.waitForLoadState("networkidle", { timeout: 15_000 });
    await this.page.waitForTimeout(500);
    assert((await this.context.cookies()).some((cookie) => cookie.name === "dash_session"), "signup did not establish dash_session");
  }

  async submitBatch(fixturePath, { fault = null, expectedStatus = 202, buttonName = /^Start batch$/ } = {}) {
    const responsePromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/batch",
      { timeout: 40_000 },
    );
    const action = async () => {
      await this.page.getByRole("button", { name: buttonName }).click();
      const response = await responsePromise;
      const payload = await response.json();
      assert(response.status() === expectedStatus, `batch POST expected ${expectedStatus}, got ${response.status()}: ${JSON.stringify(payload)}`);
      return { response, payload };
    };
    return fault
      ? this.faultedPost("**/api/proxy/batch", fault, expectedStatus, action)
      : action();
  }

  async fillDesign(name, note) {
    await this.page.getByLabel("Design name").fill(name);
    await this.page.getByLabel("Design note").fill(note);
  }

  async submitNewDesign({ fault, expectedStatus }) {
    const responsePromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/designs",
      { timeout: 40_000 },
    );
    const action = async () => {
      await this.page.getByRole("button", { name: /^Generate design$/ }).click();
      const response = await responsePromise;
      const payload = await response.json();
      assert(response.status() === expectedStatus, `design POST expected ${expectedStatus}, got ${response.status()}: ${JSON.stringify(payload)}`);
      return { response, payload };
    };
    return this.faultedPost("**/api/proxy/designs", fault, expectedStatus, action);
  }

  async submitRevision(designId) {
    const responsePromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === `/api/proxy/designs/${designId}/revisions`,
      { timeout: 40_000 },
    );
    await this.page.getByRole("button", { name: /^Generate new revision$/ }).click();
    const response = await responsePromise;
    const payload = await response.json();
    assert(response.status() === 202, `revision POST returned ${response.status()}: ${JSON.stringify(payload)}`);
    return payload.design;
  }

  async selectDesign(name) {
    const card = this.page.getByRole("button", { name: new RegExp(escapeRegExp(name), "i") }).first();
    await card.waitFor({ state: "visible", timeout: 30_000 });
    await card.click();
  }

  async waitForRevisionHistorySettled(designId, revisions) {
    await this.page.locator(
      `[data-revision-history-owner="${designId}"][data-revision-history-state="ready"]`,
    ).waitFor({ state: "visible", timeout: 30_000 });
    await this.page.getByText("Revision history", { exact: true }).waitFor({
      state: "visible",
      timeout: 30_000,
    });
    for (const revision of revisions) {
      await this.page
        .getByRole("button", {
          name: new RegExp(
            `^R${revision.number}\\s+${escapeRegExp(revision.status)}(?:\\s+current)?$`,
            "i",
          ),
        })
        .waitFor({ state: "visible", timeout: 30_000 });
    }
    await this.page.waitForLoadState("networkidle", { timeout: 15_000 });
    await this.page.waitForTimeout(250);
  }

  async assertRevisionHasNoArtifacts(designId, revisionNo) {
    return this.withExpectedStatus(409, async () => {
      const paths = [
        `/api/proxy/designs/${designId}/revisions/${revisionNo}/preview.stl`,
        `/api/proxy/designs/${designId}/revisions/${revisionNo}/download.step`,
      ];
      const statuses = [];
      for (const pathname of paths) {
        const response = await inPageProxyFetch(this.page, pathname);
        statuses.push(response.status);
        assert(response.status === 409, `${pathname} exposed a failed artifact with status ${response.status}`);
      }
      return statuses;
    });
  }

  async work03() {
    await this.runPath("WORK-03", async () => {
      const fixture = this.fixtures.cancel;
      const before = await this.batchList();
      await this.page.goto("/batch", { waitUntil: "domcontentloaded" });
      await this.page.locator('input[type="file"][accept=".zip"]').first().setInputFiles(fixture.path);
      await this.page.getByLabel("Concurrency limit").fill("1");
      const { payload } = await this.submitBatch(fixture.path, { fault: "batch_delay" });
      const batchId = payload.batch_id;
      await this.page.waitForURL((url) => url.pathname === `/batch/${batchId}`, { timeout: 30_000 });
      const firstSnapshot = await this.waitForBatch(
        batchId,
        (progress) => progress.status === "processing",
        "WORK-03 processing start",
      );
      await this.page.reload({ waitUntil: "domcontentloaded" });
      const afterRefresh = await this.getBatch(batchId);
      assert(afterRefresh.total_items === fixture.entries.length, "WORK-03 total changed after refresh");
      const progressed = await this.waitForBatch(
        batchId,
        (progress) => progress.completed_items >= 1 && progress.pending_items > 0,
        "WORK-03 first durable completion",
      );
      assert(progressed.status === "processing", `WORK-03 completed before cancellation: ${JSON.stringify(progressed)}`);
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.page.getByRole("button", { name: /^Cancel batch$/ }).click();
      const dialog = this.page.getByRole("alertdialog");
      await dialog.getByRole("button", { name: /^Cancel batch$/ }).click();
      const cancelled = await this.waitForBatch(
        batchId,
        (progress) => progress.status === "cancelled" && progress.pending_items === 0,
        "WORK-03 cancelled terminal arithmetic",
      );
      const items = await this.getBatchItems(batchId);
      const completed = items.filter((item) => item.status === "completed").length;
      const failed = items.filter((item) => item.status === "failed").length;
      const skipped = items.filter((item) => item.status === "skipped").length;
      const uniqueNames = new Set(items.map((item) => item.filename)).size;
      assert(completed >= 1, "WORK-03 cancellation preserved no completed work");
      assert(skipped >= 1, "WORK-03 cancellation skipped no pending work");
      assert(completed + failed + skipped === fixture.entries.length, "WORK-03 terminal arithmetic does not equal total");
      assert(cancelled.completed_items === completed, "WORK-03 progress/card completed count mismatch");
      assert(cancelled.failed_items === failed, "WORK-03 progress/card failed count mismatch");
      assert(cancelled.skipped_items === skipped, "WORK-03 progress/card skipped count mismatch");
      assert(items.filter((item) => item.status === "skipped").every((item) => item.analysis_url === null), "WORK-03 fabricated analysis for skipped work");
      await this.page.getByText(/^cancelled$/i).first().waitFor({ timeout: 10_000 });
      const screenshot = await this.screenshot("WORK-03", "cancelled-arithmetic");
      const after = await this.batchList();
      return {
        persona: "manufacturing operations engineer cancelling a long valid ZIP batch",
        preconditions: [
          `fresh authenticated analyst account ${this.email}`,
          `deterministic valid ZIP with ${fixture.entries.length} tracked STEP entries`,
          "concurrency limit 1 so completed, in-flight, and not-started cancellation states are all observable",
          "record-scoped 1.5 second worker delay authorized by the release-evidence secret",
        ],
        actions: [
          "selected the deterministic ZIP and clicked Start batch",
          "refreshed the durable batch detail route while work was processing",
          "inspected persisted progress and item rows",
          "clicked Cancel batch and confirmed the alert dialog after at least one completion",
        ],
        observed: {
          url: this.page.url(),
          visible: ["cancelled status badge", `${completed + failed + skipped} / ${fixture.entries.length} (100%)`, `${skipped} skipped`],
          persisted: `batch ${batchId} survived refresh, retained ${completed} completed item(s), and durably marked ${skipped} item(s) skipped`,
          numeric: `completed ${completed} + failed ${failed} + skipped ${skipped} = total ${fixture.entries.length}; pending 0`,
          authorization: "all batch reads and cancellation used the authenticated analyst's organization session",
          recovery: "refresh resumed from the persisted batch ID; cancellation preserved completed analyses and created no result for skipped items",
        },
        screenshot,
        assertions: [
          assertion("persisted batch count", 1, after.filter((batch) => batch.batch_ulid === batchId).length),
          assertion("total after refresh", fixture.entries.length, afterRefresh.total_items),
          assertion("completed did not regress after refresh", true, afterRefresh.completed_items >= firstSnapshot.completed_items),
          assertion("terminal arithmetic", fixture.entries.length, completed + failed + skipped),
          assertion("pending terminal count", 0, cancelled.pending_items),
          assertion("unique item filenames", fixture.entries.length, uniqueNames),
          assertion("completed work retained", true, completed >= 1),
          assertion("pending work skipped", true, skipped >= 1),
        ],
      };
    });
  }

  async work04() {
    await this.runPath("WORK-04", async () => {
      const fixture = this.fixtures.detail;
      await this.page.goto("/batch", { waitUntil: "domcontentloaded" });
      await this.page.locator('input[type="file"][accept=".zip"]').first().setInputFiles(fixture.path);
      const { payload } = await this.submitBatch(fixture.path);
      const batchId = payload.batch_id;
      await this.page.waitForURL((url) => url.pathname === `/batch/${batchId}`, { timeout: 30_000 });
      const terminal = await this.waitForBatch(
        batchId,
        (progress) => progress.status === "completed" && progress.pending_items === 0,
        "WORK-04 completed batch",
      );
      await this.page.reload({ waitUntil: "domcontentloaded" });
      const items = await this.getBatchItems(batchId);
      await this.page
        .locator('[data-batch-items-state="ready"]')
        .waitFor({ timeout: 15_000 });
      for (const entry of fixture.entries) {
        await this.page.getByText(entry, { exact: true }).waitFor({ timeout: 15_000 });
      }
      await this.page.getByRole("button", { name: /^Download CSV$/ }).waitFor({ timeout: 15_000 });
      const [download] = await Promise.all([
        this.page.waitForEvent("download", { timeout: 30_000 }),
        this.page.getByRole("button", { name: /^Download CSV$/ }).click(),
      ]);
      const csvPath = path.join(screenshotDir, `work-04-${batchId}.csv`);
      await download.saveAs(csvPath);
      const csvText = await readFile(csvPath, "utf8");
      const parsed = parseCsv(csvText);
      assert(parsed.headers.join(",") === CSV_HEADER, `WORK-04 CSV header was ${parsed.headers.join(",")}`);
      assert(parsed.records.length === items.length, `WORK-04 CSV rows ${parsed.records.length} != item cards ${items.length}`);
      const csvByFilename = new Map(parsed.records.map((row) => [row.filename, row]));
      for (const item of items) {
        const row = csvByFilename.get(item.filename);
        assert(row, `WORK-04 CSV omitted ${item.filename}`);
        const expected = {
          status: item.status,
          verdict: item.verdict ?? "",
          best_process: item.best_process ?? "",
          issue_count: item.issue_count == null ? "" : String(item.issue_count),
          duration_ms: item.duration_ms == null ? "" : String(item.duration_ms),
          analysis_url: item.analysis_url ?? "",
          error: item.error_message ?? "",
        };
        for (const [field, value] of Object.entries(expected)) {
          if (field === "duration_ms" && value !== "") {
            const csvDuration = Number(row[field]);
            const apiDuration = Number(value);
            assert(
              row[field] !== "" && Number.isFinite(csvDuration) && csvDuration === apiDuration,
              `WORK-04 ${item.filename} ${field}: CSV=${row[field]} API/card=${value}`,
            );
          } else {
            assert(row[field] === value, `WORK-04 ${item.filename} ${field}: CSV=${row[field]} API/card=${value}`);
          }
        }
      }
      const screenshot = await this.screenshot("WORK-04", "detail-csv-exact");
      this.artifacts.downloads["WORK-04"] = csvPath;
      return {
        persona: "quality engineer reconciling batch detail cards with an exported CSV",
        preconditions: [
          `completed deterministic valid ZIP batch ${batchId}`,
          `${fixture.entries.length} tracked STEP inputs with unique filenames and identical geometry, submitted concurrently against a cold account cache`,
          "browser downloads enabled",
        ],
        actions: [
          "clicked Start batch with the deterministic ZIP",
          "waited for terminal persisted progress and refreshed the detail route",
          "inspected every item result card",
          "clicked Download CSV and parsed the downloaded file field by field",
        ],
        observed: {
          url: this.page.url(),
          visible: [...fixture.entries, "Download CSV", "completed"],
          persisted: `batch ${batchId} and ${items.length} item records remained completed after refresh`,
          numeric: `${items.length} item cards = ${parsed.records.length} CSV rows; completed ${terminal.completed_items}; failed ${terminal.failed_items}; skipped ${terminal.skipped_items}`,
          authorization: "detail and CSV export were both organization-scoped through the same authenticated browser session",
          recovery: "a refresh reconstructed the same item/result state before export; no row, result URL, status, duration, or error changed",
        },
        screenshot,
        assertions: [
          assertion("exact CSV header", CSV_HEADER, parsed.headers.join(",")),
          assertion("one CSV row per item", items.length, parsed.records.length),
          assertion("one item per fixture entry", fixture.entries.length, items.length),
          assertion("unique CSV filenames", parsed.records.length, new Set(parsed.records.map((row) => row.filename)).size),
          assertion("all item rows completed", true, items.every((item) => item.status === "completed")),
          assertion("all result URLs are durable analysis URLs", true, items.every((item) => /^\/api\/v1\/analyses\/[A-Z0-9]+$/.test(item.analysis_url || ""))),
          assertion("all API/card errors agree with blank CSV errors", true, items.every((item) => item.error_message === null)),
        ],
      };
    });
  }

  async fail04() {
    await this.runPath("FAIL-04", async () => {
      const name = `Queue recovery plate ${randomBytes(3).toString("hex")}`;
      const note = "FAIL-04 retained queue inputs";
      const before = await this.designList();
      const postsBefore = this.postCounts.design;
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.fillDesign(name, note);
      const { payload } = await this.submitNewDesign({ fault: "design_queue", expectedStatus: 503 });
      assert(payload.detail?.message === DESIGN_QUEUE_COPY, `FAIL-04 response copy was ${payload.detail?.message}`);
      const failed = payload.design;
      assert(failed?.id, "FAIL-04 503 omitted the durable failed design");
      await this.page.getByRole("alert").getByText(DESIGN_QUEUE_COPY, { exact: true }).waitFor({ timeout: 15_000 });
      await this.page.getByRole("button", { name: /^Generate new revision$/ }).waitFor();
      const failureScreenshot = await this.screenshot("FAIL-04", "queue-failed-exact-copy");
      this.artifacts.failureScreenshots["FAIL-04"] = failureScreenshot;
      const durable = await this.getDesign(failed.id);
      const artifactStatuses = await this.assertRevisionHasNoArtifacts(failed.id, 1);
      assert(durable.status === "failed" && durable.current_revision === 1, "FAIL-04 durable state is not failed revision 1");
      assert(durable.revision.error?.message === DESIGN_QUEUE_COPY, "FAIL-04 revision copy differs from response copy");
      assert(Object.values(durable.revision.links).every((value) => value === null), "FAIL-04 exposed a fake artifact link");
      const failedRevisions = await this.getRevisions(failed.id);
      await this.waitForRevisionHistorySettled(failed.id, failedRevisions);

      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.selectDesign(name);
      await this.page.getByText(DESIGN_QUEUE_COPY, { exact: true }).waitFor();
      await this.page.waitForLoadState("networkidle", { timeout: 15_000 });
      await this.page.waitForTimeout(500);
      await this.page.getByRole("button", { name: /^Revise and retry$/ }).click();
      assert(await this.page.getByLabel("Width").inputValue() === "80", "FAIL-04 width was not retained");
      assert(await this.page.getByLabel("Design note").inputValue() === note, "FAIL-04 note was not retained");
      await this.submitRevision(failed.id);
      const ready = await this.waitForDesign(failed.id, (design) => design.status === "ready" && design.current_revision === 2, "FAIL-04 explicit retry");
      await this.page.getByText("Ready", { exact: true }).first().waitFor({ timeout: 20_000 });
      await this.page.waitForLoadState("networkidle", { timeout: 15_000 });
      await this.page.waitForTimeout(500);
      const revisions = await this.getRevisions(failed.id);
      const after = await this.designList();
      await this.waitForRevisionHistorySettled(failed.id, revisions);
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.selectDesign(name);
      await this.page.getByRole("link", { name: /^Download R2 STEP$/ }).waitFor({ timeout: 20_000 });
      await this.waitForRevisionHistorySettled(failed.id, revisions);
      await this.page.waitForLoadState("networkidle", { timeout: 15_000 });
      await this.page.waitForTimeout(500);
      const recoveryScreenshot = await this.screenshot("FAIL-04", "retry-ready-r2");
      this.artifacts.recoveryScreenshots["FAIL-04"] = recoveryScreenshot;
      return {
        persona: "design engineer recovering an accepted revision from a queue outage",
        preconditions: ["fresh unique design name", "authenticated analyst", "secret-authorized record-scoped design_queue fault"],
        actions: [
          "filled the design name, dimensions, and note and clicked Generate design",
          "observed the exact 503 recovery copy and durable failed revision card",
          "refreshed Design Studio and clicked Revise and retry",
          "clicked Generate new revision after the fault was removed and waited for Ready",
        ],
        observed: {
          url: this.page.url(),
          visible: [DESIGN_QUEUE_COPY, "Revise and retry", name, "Ready", "Download R2 STEP"],
          persisted: `one project ${failed.id} contains immutable failed R1 and ready R2 after refresh`,
          numeric: `project delta ${after.length - before.length}; revisions ${revisions.length}; design POSTs ${this.postCounts.design - postsBefore}; failed artifact statuses ${artifactStatuses.join("/")}`,
          authorization: "queue failure and retry remained scoped to the authenticated analyst's organization",
          recovery: "the returned failed project became the retry target, so explicit retry created R2 instead of duplicating the project or replaying R1",
        },
        screenshot: failureScreenshot,
        assertions: [
          assertion("exact queue response copy", DESIGN_QUEUE_COPY, payload.detail.message),
          assertion("exact persisted revision copy", DESIGN_QUEUE_COPY, durable.revision.error.message),
          assertion("one project with this name", 1, after.filter((design) => design.name === name).length),
          assertion("project list delta", 1, after.length - before.length),
          assertion("immutable revision count", 2, revisions.length),
          assertion("revision statuses", "ready,failed", revisions.map((revision) => revision.status).join(",")),
          assertion("current revision", 2, ready.current_revision),
          assertion("failed revision has no links", true, Object.values(revisions[1].links).every((value) => value === null)),
          assertion("failed artifact endpoints", "409,409", artifactStatuses.join(",")),
        ],
      };
    });
  }

  async exerciseDesignWorkerFailure({ id, fault, copy, revisedThickness, verifyStoredArtifacts }) {
    await this.runPath(id, async () => {
      const name = `${id} plate ${randomBytes(3).toString("hex")}`;
      const note = `${id} retained worker inputs`;
      const before = await this.designList();
      const postsBefore = this.postCounts.design;
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.fillDesign(name, note);
      const { payload } = await this.submitNewDesign({ fault, expectedStatus: 202 });
      const designId = payload.design.id;
      const failed = await this.waitForDesign(designId, (design) => design.status === "failed", `${id} worker failure`);
      await this.page.getByText(copy, { exact: true }).waitFor({ timeout: 20_000 });
      const failedHistory = await this.getRevisions(designId);
      await this.waitForRevisionHistorySettled(designId, failedHistory);
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.selectDesign(name);
      await this.page.getByText(copy, { exact: true }).waitFor({ timeout: 20_000 });
      const failureScreenshot = await this.screenshot(id, `${fault}-failed-exact-copy`);
      this.artifacts.failureScreenshots[id] = failureScreenshot;
      const artifactStatuses = await this.assertRevisionHasNoArtifacts(designId, 1);
      const failedRevision = failedHistory.find((revision) => revision.number === 1);
      assert(failedRevision, `${id} lost failed revision 1`);
      assert(failedRevision.plan.thickness_mm === 6, `${id} failed input thickness was not retained`);
      assert(failedRevision.design_note === note, `${id} failed input note was not retained`);
      assert(Object.values(failedRevision.links).every((value) => value === null), `${id} exposed a fake failed link`);

      await this.page.getByRole("button", { name: /^Revise and retry$/ }).click();
      assert(await this.page.getByLabel("Design note").inputValue() === note, `${id} retry form lost the design note`);
      if (revisedThickness !== null) await this.page.getByLabel("Thickness").fill(String(revisedThickness));
      await this.submitRevision(designId);
      const ready = await this.waitForDesign(designId, (design) => design.status === "ready" && design.current_revision === 2, `${id} restored retry`);
      const revisions = await this.getRevisions(designId);
      const after = await this.designList();
      await this.waitForRevisionHistorySettled(designId, revisions);
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.selectDesign(name);
      await this.page.getByRole("link", { name: /^Download R2 STEP$/ }).waitFor({ timeout: 20_000 });
      await this.page.locator('[data-preview-state="ready"]').waitFor({ timeout: 30_000 });
      await this.waitForRevisionHistorySettled(designId, revisions);
      const [download] = await Promise.all([
        this.page.waitForEvent("download", { timeout: 30_000 }),
        this.page.getByRole("link", { name: /^Download R2 STEP$/ }).click(),
      ]);
      const downloadPath = path.join(screenshotDir, `${id.toLowerCase()}-r2.step`);
      await download.saveAs(downloadPath);
      const stepBytes = (await readFile(downloadPath)).length;
      this.artifacts.downloads[id] = downloadPath;
      let storedEvidence = { stepStatus: 200, previewStatus: 200, hashMatches: true, previewBytes: 0 };
      if (verifyStoredArtifacts) {
        const stepResponse = await inPageProxyFetch(
          this.page,
          `/api/proxy/designs/${designId}/revisions/2/download.step`,
          { responseType: "bytes" },
        );
        const previewResponse = await inPageProxyFetch(
          this.page,
          `/api/proxy/designs/${designId}/revisions/2/preview.stl`,
          { responseType: "bytes" },
        );
        storedEvidence = {
          stepStatus: stepResponse.status,
          previewStatus: previewResponse.status,
          hashMatches: stepResponse.headers["x-geometry-sha256"] === ready.revision.geometry_hash,
          previewBytes: previewResponse.byteLength,
        };
        assert(storedEvidence.stepStatus === 200 && storedEvidence.previewStatus === 200, `${id} restored artifacts are incomplete`);
        assert(storedEvidence.hashMatches, `${id} restored STEP hash does not match revision evidence`);
        assert(storedEvidence.previewBytes > 128, `${id} restored preview is empty`);
      }
      const recoveryScreenshot = await this.screenshot(id, "retry-ready-r2");
      this.artifacts.recoveryScreenshots[id] = recoveryScreenshot;
      const revision2 = revisions.find((revision) => revision.number === 2);
      return {
        persona: "design engineer recovering a deterministic CAD generation failure",
        preconditions: ["fresh unique design", "authenticated analyst", `secret-authorized record-scoped ${fault} worker fault`],
        actions: [
          "filled a complete plate plan and clicked Generate design",
          `waited for the real worker to persist the ${fault} failure and exact copy`,
          "refreshed the project, inspected the failed immutable revision, and clicked Revise and retry",
          "submitted a new immutable revision, waited for its real STL preview to mount, and downloaded its STEP artifact",
        ],
        observed: {
          url: this.page.url(),
          visible: [copy, "Revise and retry", name, "Ready", "Download R2 STEP"],
          persisted: `design ${designId} retained failed R1 with its inputs and completed R2 with full artifact links`,
          numeric: `revisions ${revisions.length}; R1 thickness ${failedRevision.plan.thickness_mm}; R2 thickness ${revision2.plan.thickness_mm}; STEP bytes ${stepBytes}; failed endpoints ${artifactStatuses.join("/")}`,
          authorization: "worker state, artifact reads, and retry were organization-scoped to the authenticated analyst",
          recovery: verifyStoredArtifacts
            ? "the partial R1 store attempt exposed no links; explicit R2 retry produced hash-bound STEP and STL artifacts only after both were complete"
            : "the failed R1 plan remained immutable; the revised R2 plan generated successfully without replacing or fabricating R1",
        },
        screenshot: failureScreenshot,
        assertions: [
          assertion("exact persisted failure copy", copy, failed.revision.error.message),
          assertion("one project with this name", 1, after.filter((design) => design.name === name).length),
          assertion("project list delta", 1, after.length - before.length),
          assertion("immutable revision count", 2, revisions.length),
          assertion("revision statuses", "ready,failed", revisions.map((revision) => revision.status).join(",")),
          assertion("failed revision artifact links", true, Object.values(failedRevision.links).every((value) => value === null)),
          assertion("failed revision artifact endpoints", "409,409", artifactStatuses.join(",")),
          assertion("R2 plan thickness", String(revisedThickness ?? 6), String(revision2.plan.thickness_mm)),
          assertion("R2 STEP download nonempty", true, stepBytes > 128),
          assertion("R2 interactive preview mounted", "ready", await this.page.locator('[data-preview-state]').getAttribute("data-preview-state")),
          assertion("design POST count", 2, this.postCounts.design - postsBefore),
          assertion("restored artifact hash", true, storedEvidence.hashMatches),
        ],
      };
    });
  }

  async fail05() {
    return this.exerciseDesignWorkerFailure({
      id: "FAIL-05",
      fault: "cad_kernel",
      copy: CAD_KERNEL_COPY,
      revisedThickness: 7,
      verifyStoredArtifacts: false,
    });
  }

  async fail06() {
    return this.exerciseDesignWorkerFailure({
      id: "FAIL-06",
      fault: "object_store",
      copy: OBJECT_STORE_COPY,
      revisedThickness: null,
      verifyStoredArtifacts: true,
    });
  }

  async fail07() {
    await this.runPath("FAIL-07", async () => {
      const fixture = this.fixtures.queue;
      const before = await this.batchList();
      const postsBefore = this.postCounts.batch;
      await this.page.goto("/batch", { waitUntil: "domcontentloaded" });
      await this.page.locator('input[type="file"][accept=".zip"]').first().setInputFiles(fixture.path);
      const { payload } = await this.submitBatch(fixture.path, { fault: "batch_queue", expectedStatus: 503 });
      const failure = payload.detail && typeof payload.detail === "object" ? payload.detail : payload;
      assert(failure?.message === BATCH_QUEUE_COPY, `FAIL-07 response copy was ${failure?.message}: ${JSON.stringify(payload)}`);
      const failedBatch = failure?.accepted_batch;
      assert(failedBatch?.batch_id, "FAIL-07 503 omitted accepted_batch identity");
      await this.page.getByRole("alert").getByText(BATCH_QUEUE_COPY, { exact: true }).waitFor({ timeout: 15_000 });
      await this.page.getByRole("button", { name: /^Retry this ZIP$/ }).waitFor();
      const failureScreenshot = await this.screenshot("FAIL-07", "queue-failed-explicit-retry");
      this.artifacts.failureScreenshots["FAIL-07"] = failureScreenshot;
      const failedProgress = await this.getBatch(failedBatch.batch_id);
      const failedItems = await this.getBatchItems(failedBatch.batch_id);
      assert(failedProgress.status === "failed", `FAIL-07 accepted batch status ${failedProgress.status}`);
      assert(failedProgress.input_mode === "direct_upload", `FAIL-07 accepted batch input mode ${failedProgress.input_mode}`);
      assert(failedProgress.pending_items === 0, "FAIL-07 failed batch retained pending work");
      assert(failedProgress.total_items === 0, "FAIL-07 queue outage materialized direct-upload items before worker extraction");
      assert(failedItems.length === 0, "FAIL-07 queue outage created item rows before worker extraction");

      const responsePromise = this.page.waitForResponse(
        (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/batch",
        { timeout: 40_000 },
      );
      await this.page.getByRole("button", { name: /^Retry this ZIP$/ }).click();
      const retryResponse = await responsePromise;
      const retryPayload = await retryResponse.json();
      assert(retryResponse.status() === 202, `FAIL-07 retry returned ${retryResponse.status()}: ${JSON.stringify(retryPayload)}`);
      const retryId = retryPayload.batch_id;
      assert(retryId !== failedBatch.batch_id, "FAIL-07 retry reused the failed batch ID");
      await this.page.waitForURL((url) => url.pathname === `/batch/${retryId}`, { timeout: 30_000 });
      const retryProgress = await this.waitForBatch(
        retryId,
        (progress) => progress.status === "completed" && progress.pending_items === 0,
        "FAIL-07 retry completion",
      );
      const retryItems = await this.getBatchItems(retryId);
      const after = await this.batchList();
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.page.getByRole("button", { name: /^Download CSV$/ }).waitFor({ timeout: 15_000 });
      const recoveryScreenshot = await this.screenshot("FAIL-07", "retry-completed-once");
      this.artifacts.recoveryScreenshots["FAIL-07"] = recoveryScreenshot;
      const createdIds = after
        .filter((batch) => !before.some((previous) => previous.batch_ulid === batch.batch_ulid))
        .map((batch) => batch.batch_ulid);
      return {
        persona: "batch operator recovering an accepted ZIP from a coordinator queue outage",
        preconditions: [
          `deterministic valid ZIP with ${fixture.entries.length} tracked STEP entries`,
          "authenticated analyst",
          "secret-authorized record-scoped batch_queue fault",
        ],
        actions: [
          "selected the ZIP and clicked Start batch",
          "observed the exact accepted-but-failed queue copy and retained file",
          "inspected the durable failed batch state through its returned ID",
          "clicked Retry this ZIP after the fault was removed and waited for the new batch to complete",
        ],
        observed: {
          url: this.page.url(),
          visible: [BATCH_QUEUE_COPY, "Retry this ZIP", "completed", "Download CSV"],
          persisted: `failed direct-upload batch ${failedBatch.batch_id} remains terminal with zero pre-worker item rows; one retry batch ${retryId} completed`,
          numeric: `new batch records ${createdIds.length}; POSTs ${this.postCounts.batch - postsBefore}; original materialized items ${failedItems.length}; retry completed ${retryProgress.completed_items}`,
          authorization: "both accepted failure and retry were scoped to the same authenticated organization",
          recovery: "explicit retry reused the retained browser File once, created one new durable batch, and never processed the original failed items",
        },
        screenshot: failureScreenshot,
        assertions: [
          assertion("exact queue copy", BATCH_QUEUE_COPY, failure.message),
          assertion("original durable status", "failed", failedProgress.status),
          assertion("original input mode", "direct_upload", failedProgress.input_mode),
          assertion("original pending count", 0, failedProgress.pending_items),
          assertion("original total before worker extraction", 0, failedProgress.total_items),
          assertion("original completed count", 0, failedProgress.completed_items),
          assertion("original skipped count", 0, failedProgress.skipped_items),
          assertion("original materialized item count", 0, failedItems.length),
          assertion("original fake result count", 0, failedItems.filter((item) => item.analysis_url).length),
          assertion("new durable batch records", 2, createdIds.length),
          assertion("batch POST count", 2, this.postCounts.batch - postsBefore),
          assertion("retry item count", fixture.entries.length, retryItems.length),
          assertion("retry items completed once", true, retryItems.every((item) => item.status === "completed")),
          assertion("retry unique filenames", fixture.entries.length, new Set(retryItems.map((item) => item.filename)).size),
          assertion("failed and retry IDs both listed once", 2, [failedBatch.batch_id, retryId].filter((id) => after.filter((batch) => batch.batch_ulid === id).length === 1).length),
        ],
      };
    });
  }

  async writeReport(fatalError = null) {
    this.rejectUnconfirmedDirectUploads();
    const validation = validateGoldenPathMap(OWNED_PATH_IDS, this.goldenPaths);
    const buildIdentityAtEnd = captureBuildIdentity(repoRoot);
    const buildStable = this.buildIdentityAtStart.gitHead === buildIdentityAtEnd.gitHead;
    const status = !fatalError && this.issues.length === 0 && validation.valid === validation.total
      && this.consoleErrors.length === 0 && this.requestFailures.length === 0
      && this.unexpectedHttpResponses.length === 0 && buildStable
      ? "PASS"
      : "FAIL";
    const report = {
      status,
      health: status === "PASS" ? 100 : Math.round((validation.valid / OWNED_PATH_IDS.length) * 100),
      suite: "batch-design-recovery-golden-matrix",
      runId,
      generatedAt: new Date().toISOString(),
      baseUrl,
      account: { email: this.email },
      ownedPathIds: OWNED_PATH_IDS,
      buildIdentity: buildIdentityAtEnd,
      captureBuildIdentity: {
        start: this.buildIdentityAtStart,
        end: buildIdentityAtEnd,
        stable: buildStable,
      },
      fixtures: this.fixtures,
      artifacts: this.artifacts,
      steps: this.steps,
      issues: this.issues,
      fatalError: fatalError ? (fatalError instanceof Error ? fatalError.message : String(fatalError)) : null,
      diagnostics: {
        consoleErrors: this.consoleErrors,
        requestFailures: this.requestFailures,
        unexpectedHttpResponses: this.unexpectedHttpResponses,
        expectedDiagnostics: this.expectedDiagnostics,
      },
      releaseEvidence: {
        schemaVersion: 1,
        goldenPaths: this.goldenPaths,
        validation,
      },
    };
    await mkdir(outputRoot, { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
    return report;
  }

  async close() {
    await this.context?.close().catch(() => undefined);
    await this.browser?.close().catch(() => undefined);
  }
}

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  const matrix = new BatchDesignRecoveryMatrix();
  let fatalError = null;
  let report = null;
  try {
    assert(faultToken.length >= 16, "E2E_FAULT_INJECTION_TOKEN (16+ characters) must match the rebuilt backend environment");
    matrix.fixtures.cancel = await writeDeterministicStoredZip(
      trackedCubeFixture,
      path.join(screenshotDir, "work-03-valid-cancel.zip"),
      Array.from({ length: 8 }, (_, index) => `cancel-part-${index + 1}.step`),
    );
    matrix.fixtures.detail = await writeDeterministicStoredZip(
      trackedCubeFixture,
      path.join(screenshotDir, "work-04-valid-detail.zip"),
      ["detail-alpha.step", "detail-beta.step", "detail-gamma.step"],
    );
    matrix.fixtures.queue = await writeDeterministicStoredZip(
      trackedCubeFixture,
      path.join(screenshotDir, "fail-07-valid-queue.zip"),
      ["queue-alpha.step", "queue-beta.step"],
    );
    await matrix.launch();
    await matrix.signup();
    // Run the duplicate-geometry batch first so concurrent analysis de-duplication
    // is exercised against a cold per-account cache instead of taking cache hits.
    await matrix.work04();
    await matrix.work03();
    await matrix.fail04();
    await matrix.fail05();
    await matrix.fail06();
    await matrix.fail07();
  } catch (error) {
    fatalError = error;
  } finally {
    report = await matrix.writeReport(fatalError);
    await matrix.close();
  }

  process.stdout.write(`${JSON.stringify({
    status: report.status,
    reportPath,
    validation: report.releaseEvidence.validation,
    diagnostics: {
      consoleErrors: report.diagnostics.consoleErrors.length,
      requestFailures: report.diagnostics.requestFailures.length,
      unexpectedHttpResponses: report.diagnostics.unexpectedHttpResponses.length,
    },
  }, null, 2)}\n`);
  if (report.status !== "PASS") process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}

export {
  OWNED_PATH_IDS,
  inPageProxyFetch,
  parseCsv,
  writeDeterministicStoredZip,
};
